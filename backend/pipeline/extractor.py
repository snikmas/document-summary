import csv
import io

from bs4 import BeautifulSoup
from docx import Document
from pypdf import PdfReader

from backend.pipeline.constants import SUPPORTED_FORMATS
from backend.pipeline.detector import (
    DocxArchiveSafetyError,
    detect_file_type,
    validate_docx_archive,
)


class ExtractionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def extract_text(file_bytes: bytes, *, expected_format: str | None = None) -> str:
    """Extract text in memory after reconciling the expected and detected formats."""

    if not file_bytes:
        raise ExtractionError("empty_file", "The uploaded file is empty.")
    if expected_format is not None and expected_format not in SUPPORTED_FORMATS:
        raise ExtractionError(
            "unsupported_format",
            "The document format is not supported.",
            status_code=415,
        )

    try:
        detected_format = detect_file_type(file_bytes)
    except DocxArchiveSafetyError as exc:
        raise ExtractionError(
            "unsafe_archive",
            "The DOCX archive exceeds safe extraction limits.",
        ) from exc
    except (TypeError, ValueError) as exc:
        # A damaged OOXML package can still be classified safely as a DOCX
        # candidate from its ZIP signature; the parser below then produces the
        # stable corrupt-document error.
        if expected_format == "docx" and file_bytes.startswith(b"PK"):
            detected_format = "docx"
        else:
            raise ExtractionError(
                "unsupported_format",
                "The file content is not a supported PDF, DOCX, TXT, HTML, or CSV document.",
                status_code=415,
            ) from exc

    # Even damaged OOXML starts with the ZIP signature. Let the DOCX parser
    # distinguish corruption from an extension mismatch in that bounded case.
    if expected_format == "docx" and file_bytes.startswith(b"PK"):
        detected_format = "docx"

    if not _formats_agree(expected_format, detected_format):
        raise ExtractionError(
            "format_mismatch",
            "The filename extension does not match the detected document format.",
            status_code=415,
        )
    file_format = expected_format or detected_format

    try:
        match file_format:
            case "pdf":
                text = extract_pdf(file_bytes)
            case "docx":
                text = extract_docx(file_bytes)
            case "txt":
                text = extract_txt(file_bytes)
            case "html":
                text = extract_html(file_bytes)
            case "csv":
                text = extract_csv(file_bytes)
            case _:
                raise ExtractionError(
                    "unsupported_format",
                    "The document format is not supported.",
                    status_code=415,
                )
        if not text.strip():
            raise ExtractionError(
                "empty_document",
                "No readable text was found. OCR for scanned documents is not supported.",
            )
        return text
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(
            "invalid_document",
            "The document is corrupt or cannot be read.",
        ) from exc


def extract_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_docx(file_bytes: bytes) -> str:
    try:
        validate_docx_archive(file_bytes)
    except DocxArchiveSafetyError as exc:
        raise ExtractionError(
            "unsafe_archive",
            "The DOCX archive exceeds safe extraction limits.",
        ) from exc
    document = Document(io.BytesIO(file_bytes))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def extract_txt(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8-sig")


def extract_html(file_bytes: bytes) -> str:
    decoded = file_bytes.decode("utf-8-sig")
    soup = BeautifulSoup(decoded, "html.parser")
    for hidden in soup(["script", "style"]):
        hidden.decompose()
    return soup.get_text(separator=" ", strip=True)


def extract_csv(file_bytes: bytes) -> str:
    decoded = file_bytes.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(decoded), strict=True)
    return "\n".join(", ".join(row) for row in reader)


def _formats_agree(expected: str | None, detected: str) -> bool:
    if expected is None or expected == detected:
        return True
    return expected == "csv" and detected == "txt"
