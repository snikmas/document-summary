import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from fastapi import FastAPI

from backend.config import Settings, Status
from backend.jobs import JobRepository
from backend.main import create_app

AsyncCheck = Callable[[httpx.AsyncClient, FastAPI], Awaitable[None]]


def run_with_app(settings: Settings, check: AsyncCheck, *, repository=None) -> None:
    async def run() -> None:
        app = create_app(settings, repository=repository)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                await check(client, app)

    asyncio.run(run())


async def upload_txt(
    client: httpx.AsyncClient,
    content: bytes = b"Revenue increased. Support improved.",
):
    return await client.post(
        "/process",
        files={"file": ("quarterly.txt", content, "text/plain")},
    )


def test_health_exposes_mode_without_secrets(settings: Settings) -> None:
    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "mode": "demo"}
        assert "key" not in response.text.lower()

    run_with_app(settings, check)


def test_process_status_and_result_contract(settings: Settings) -> None:
    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        accepted = await upload_txt(client)

        assert accepted.status_code == 202
        assert accepted.json()["status"] == Status.PENDING.value
        job_id = accepted.json()["job_id"]

        status_response = await client.get(f"/jobs/{job_id}")
        assert status_response.status_code == 200
        status_body = status_response.json()
        assert status_body["job_id"] == job_id
        assert status_body["status"] == Status.COMPLETED.value
        assert status_body["filename"] == "quarterly.txt"
        assert status_body["input_format"] == "txt"
        assert status_body["error"] is None

        result_response = await client.get(f"/jobs/{job_id}/result")
        assert result_response.status_code == 200
        result = result_response.json()
        assert result["summary"]
        assert result["key_points"]
        assert result["word_count"] == 4
        assert result["metadata"]["mode"] == "demo"
        assert result["metadata"]["input_format"] == "txt"

    run_with_app(settings, check)


def test_result_openapi_schema_is_document_summary(settings: Settings) -> None:
    app = create_app(settings)

    schema = app.openapi()["paths"]["/jobs/{job_id}/result"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert schema == {"$ref": "#/components/schemas/DocumentSummary"}


def test_completed_result_survives_application_restart(settings: Settings) -> None:
    job_id = ""

    async def create(client: httpx.AsyncClient, app: FastAPI) -> None:
        nonlocal job_id
        job_id = (await upload_txt(client)).json()["job_id"]

    run_with_app(settings, create)

    async def read(client: httpx.AsyncClient, app: FastAPI) -> None:
        response = await client.get(f"/jobs/{job_id}/result")
        assert response.status_code == 200
        assert response.json()["summary"]

    run_with_app(settings, read)


def test_startup_marks_interrupted_processing_failed(settings: Settings) -> None:
    repository = JobRepository(settings.database_url)
    repository.initialize()
    job = repository.create(
        filename="safe.txt",
        input_format="txt",
        byte_size=10,
        mode="demo",
        requested_model="deterministic-extractive-v1",
    )
    repository.mark_processing(job.id)

    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        response = await client.get(f"/jobs/{job.id}")
        assert response.status_code == 200
        assert response.json()["status"] == Status.FAILED.value
        assert response.json()["error"]["code"] == "processing_interrupted"

    run_with_app(settings, check)


def test_invalid_uploads_do_not_create_jobs(settings: Settings) -> None:
    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        repository: JobRepository = app.state.jobs
        cases = [
            (("empty.txt", b"", "text/plain"), 422, "empty_file"),
            (("malware.exe", b"MZ pretend", "application/octet-stream"), 415, "unsupported_format"),
            (("wrong.pdf", b"plain text", "application/pdf"), 415, "format_mismatch"),
            (("large.txt", b"x" * 2_049, "text/plain"), 413, "file_too_large"),
        ]

        for file_data, expected_status, expected_code in cases:
            before = repository.count()
            response = await client.post("/process", files={"file": file_data})
            assert response.status_code == expected_status
            assert response.json()["detail"]["code"] == expected_code
            assert repository.count() == before

    run_with_app(settings, check)


def test_missing_upload_uses_stable_error_envelope(settings: Settings) -> None:
    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        repository: JobRepository = app.state.jobs

        response = await client.post("/process")

        assert response.status_code == 422
        assert response.json() == {
            "detail": {
                "code": "file_missing",
                "message": "A file upload is required.",
            }
        }
        assert repository.count() == 0

    run_with_app(settings, check)


def test_control_characters_in_filename_do_not_create_jobs(settings: Settings) -> None:
    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        repository: JobRepository = app.state.jobs

        response = await client.post(
            "/process",
            files={"file": ("unsafe\u202ename.txt", b"Safe source text.", "text/plain")},
        )

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "filename_invalid"
        assert repository.count() == 0

    run_with_app(settings, check)


def test_paths_are_removed_from_stored_filename(settings: Settings) -> None:
    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        response = await client.post(
            "/process",
            files={"file": ("../../private/report.txt", b"Safe source text.", "text/plain")},
        )
        job_id = response.json()["job_id"]

        status_response = await client.get(f"/jobs/{job_id}")
        assert status_response.json()["filename"] == "report.txt"

    run_with_app(settings, check)


def test_missing_and_not_ready_jobs_have_stable_errors(settings: Settings) -> None:
    repository = JobRepository(settings.database_url)
    repository.initialize()
    pending = repository.create(
        filename="report.txt",
        input_format="txt",
        byte_size=10,
        mode="demo",
        requested_model="deterministic-extractive-v1",
    )

    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        missing = await client.get("/jobs/missing")
        not_ready = await client.get(f"/jobs/{pending.id}/result")

        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "job_not_found"
        assert not_ready.status_code == 409
        assert not_ready.json()["detail"]["code"] == "job_not_ready"

    run_with_app(settings, check, repository=repository)


def test_corrupt_persisted_result_has_safe_api_error(settings: Settings) -> None:
    repository = JobRepository(settings.database_url)
    repository.initialize()
    job = repository.create(
        filename="report.txt",
        input_format="txt",
        byte_size=10,
        mode="demo",
        requested_model="deterministic-extractive-v1",
    )
    database_path = Path(settings.database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE jobs SET status = ?, result_json = ? WHERE id = ?",
            (Status.COMPLETED.value, "{not-json", job.id),
        )

    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        for endpoint in (f"/jobs/{job.id}", f"/jobs/{job.id}/result"):
            response = await client.get(endpoint)
            assert response.status_code == 500
            assert response.json() == {
                "detail": {
                    "code": "stored_result_invalid",
                    "message": "The stored job result is invalid.",
                }
            }

    run_with_app(settings, check, repository=repository)


def test_logs_exclude_document_text_and_filename(settings: Settings, caplog) -> None:
    secret_text = "UNIQUE_PRIVATE_DOCUMENT_CONTENT"
    secret_filename = "private-customer-name.txt"
    caplog.set_level(logging.INFO)

    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        response = await client.post(
            "/process",
            files={"file": (secret_filename, secret_text.encode(), "text/plain")},
        )
        assert response.status_code == 202

    run_with_app(settings, check)
    assert secret_text not in caplog.text
    assert secret_filename not in caplog.text
