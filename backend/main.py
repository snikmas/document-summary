import logging
import unicodedata
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePath

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.config import Settings, Status, get_settings
from backend.jobs import CorruptJobResultError, JobRecord, JobRepository
from backend.models import (
    DocumentSummary,
    ErrorDetail,
    HealthResponse,
    JobAccepted,
    JobStatusResponse,
)
from backend.pipeline.chunker import chunk_text
from backend.pipeline.cleaner import clean_text
from backend.pipeline.extractor import ExtractionError, extract_text
from backend.pipeline.llm import ProviderError, build_provider, get_summary_from_llm

log = logging.getLogger("pipeline.api")

SUPPORTED_EXTENSIONS = {"pdf", "docx", "txt", "html", "csv"}
SAFE_PROCESSING_ERROR = "The document could not be processed. Please verify it and try again."


class IntakeError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorDetail(code=code, message=message).model_dump(),
    )


def _safe_filename(filename: str | None) -> tuple[str, str]:
    if not filename or not filename.strip():
        raise IntakeError("filename_missing", "A filename is required.")
    basename = PurePath(filename.replace("\\", "/")).name.strip()
    if (
        not basename
        or basename in {".", ".."}
        or any(unicodedata.category(character).startswith("C") for character in basename)
    ):
        raise IntakeError("filename_invalid", "The filename is invalid.")
    if "." not in basename:
        raise IntakeError(
            "unsupported_format",
            "Supported formats are PDF, DOCX, TXT, HTML, and CSV.",
            status_code=415,
        )
    extension = basename.rsplit(".", 1)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise IntakeError(
            "unsupported_format",
            "Supported formats are PDF, DOCX, TXT, HTML, and CSV.",
            status_code=415,
        )
    return basename, extension


def _validate_and_extract(
    file_bytes: bytes,
    *,
    filename: str | None,
    max_upload_bytes: int,
) -> tuple[str, str, str]:
    safe_name, extension = _safe_filename(filename)
    if not file_bytes:
        raise IntakeError("empty_file", "The uploaded file is empty.")
    if len(file_bytes) > max_upload_bytes:
        raise IntakeError(
            "file_too_large",
            f"The file exceeds the {max_upload_bytes}-byte upload limit.",
            status_code=413,
        )
    try:
        extracted = extract_text(file_bytes, expected_format=extension)
    except ExtractionError as exc:
        raise IntakeError(exc.code, exc.message, status_code=exc.status_code) from exc
    cleaned = clean_text(extracted)
    if not cleaned:
        raise IntakeError(
            "empty_document",
            "No readable text was found. OCR for scanned documents is not supported.",
        )
    return safe_name, extension, cleaned


def _job_status(record: JobRecord) -> JobStatusResponse:
    error = None
    if record.error_code and record.error_message:
        error = ErrorDetail(code=record.error_code, message=record.error_message)
    return JobStatusResponse(
        job_id=record.id,
        status=record.status,
        filename=record.filename,
        input_format=record.input_format,
        byte_size=record.byte_size,
        created_at=record.created_at,
        updated_at=record.updated_at,
        error=error,
    )


async def run_pipeline(
    app: FastAPI,
    job_id: str,
    cleaned_text: str,
    input_format: str,
) -> None:
    repository: JobRepository = app.state.jobs
    try:
        repository.mark_processing(job_id)
        chunks = chunk_text(cleaned_text, max_chars=app.state.settings.max_chunk_size)
        if not chunks:
            raise ValueError("cleaning produced no chunks")
        result = get_summary_from_llm(
            chunks,
            provider=app.state.provider,
            input_format=input_format,
        )
        repository.complete(job_id, result)
        log.info("job_completed job_id=%s", job_id)
    except ProviderError as exc:
        repository.fail(job_id, code=exc.code, message=str(exc))
        log.warning("job_failed job_id=%s code=%s", job_id, exc.code)
    except Exception as exc:
        repository.fail(job_id, code="processing_failed", message=SAFE_PROCESSING_ERROR)
        log.error(
            "job_failed job_id=%s code=processing_failed exception_type=%s",
            job_id,
            type(exc).__name__,
        )


def create_app(
    settings: Settings | None = None,
    *,
    repository: JobRepository | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    job_repository = repository or JobRepository(app_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        job_repository.initialize()
        interrupted = job_repository.resolve_interrupted()
        if interrupted:
            log.warning("resolved_interrupted_jobs count=%d", interrupted)
        yield

    application = FastAPI(
        title="Document Intelligence Pipeline",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.jobs = job_repository
    application.state.provider = build_provider(app_settings)

    @application.exception_handler(RequestValidationError)
    async def stable_process_validation_error(
        request: Request,
        exc: RequestValidationError,
    ):
        missing_file = request.url.path == "/process" and any(
            error.get("type") == "missing" and tuple(error.get("loc", ())) == ("body", "file")
            for error in exc.errors()
        )
        if not missing_file:
            return await request_validation_exception_handler(request, exc)
        detail = ErrorDetail(
            code="file_missing",
            message="A file upload is required.",
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": detail.model_dump()},
        )

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        try:
            job_repository.healthcheck()
        except Exception as exc:
            log.error("healthcheck_failed exception_type=%s", type(exc).__name__)
            raise _http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "database_unavailable",
                "The job database is unavailable.",
            ) from exc
        return HealthResponse(status="ok", mode=app_settings.summary_mode)

    @application.post(
        "/process",
        response_model=JobAccepted,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def upload_file(
        file: UploadFile,
        background_tasks: BackgroundTasks,
    ) -> JobAccepted:
        file_bytes = await file.read(app_settings.max_upload_bytes + 1)
        await file.close()
        try:
            safe_name, input_format, cleaned_text = _validate_and_extract(
                file_bytes,
                filename=file.filename,
                max_upload_bytes=app_settings.max_upload_bytes,
            )
        except IntakeError as exc:
            raise _http_error(exc.status_code, exc.code, exc.message) from exc

        requested_model = (
            app_settings.openrouter_model
            if app_settings.summary_mode == "openrouter"
            else "deterministic-extractive-v1"
        )
        record = job_repository.create(
            filename=safe_name,
            input_format=input_format,
            byte_size=len(file_bytes),
            mode=app_settings.summary_mode,
            requested_model=requested_model,
        )
        background_tasks.add_task(
            run_pipeline,
            application,
            record.id,
            cleaned_text,
            input_format,
        )
        log.info(
            "job_created job_id=%s input_format=%s byte_size=%d",
            record.id,
            input_format,
            len(file_bytes),
        )
        return JobAccepted(job_id=record.id, status=record.status)

    @application.get("/jobs/{job_id}", response_model=JobStatusResponse)
    async def get_job(job_id: str) -> JobStatusResponse:
        try:
            record = job_repository.get(job_id)
        except CorruptJobResultError as exc:
            raise _http_error(
                500,
                "stored_result_invalid",
                "The stored job result is invalid.",
            ) from exc
        if record is None:
            raise _http_error(404, "job_not_found", "Job not found.")
        return _job_status(record)

    @application.get("/jobs/{job_id}/result", response_model=DocumentSummary)
    async def get_result_job(job_id: str) -> DocumentSummary:
        try:
            record = job_repository.get(job_id)
        except CorruptJobResultError as exc:
            raise _http_error(
                500,
                "stored_result_invalid",
                "The stored job result is invalid.",
            ) from exc
        if record is None:
            raise _http_error(404, "job_not_found", "Job not found.")
        if record.status is Status.FAILED:
            raise _http_error(
                409,
                record.error_code or "job_failed",
                record.error_message or SAFE_PROCESSING_ERROR,
            )
        if record.status is not Status.COMPLETED or record.result is None:
            raise _http_error(409, "job_not_ready", "The result is not ready.")
        return record.result

    return application


app = create_app()
