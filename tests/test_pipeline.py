import asyncio
import io
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from backend.config import Settings, Status
from backend.jobs import JobRepository
from backend.main import create_app
from backend.pipeline.chunker import chunk_text
from backend.pipeline.cleaner import clean_text
from backend.pipeline.constants import (
    DOCX_MAX_CONTENT_TYPES_BYTES,
    DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES,
    DOCX_MAX_MEMBERS,
    DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES,
)
from backend.pipeline.detector import (
    DocxArchiveSafetyError,
    detect_file_type,
    validate_docx_members,
)
from backend.pipeline.extractor import ExtractionError, extract_text

SAMPLE_ARCHIVE = Path("samples")
EXPECTED_SAMPLES = {
    "northstar-quarterly-brief.pdf": "pdf",
    "northstar-quarterly-brief.docx": "docx",
    "northstar-quarterly-brief.txt": "txt",
    "northstar-quarterly-brief.html": "html",
    "northstar-quarterly-brief.csv": "csv",
}
UPLOAD_MIMES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain",
    "html": "text/html",
    "csv": "text/csv",
}


def sample_documents() -> dict[str, bytes]:
    with zipfile.ZipFile(SAMPLE_ARCHIVE) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def run_with_app(settings: Settings, check) -> None:
    async def run() -> None:
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                await check(client, app)

    asyncio.run(run())


def test_archive_contains_only_five_original_safe_samples() -> None:
    documents = sample_documents()

    assert set(documents) == set(EXPECTED_SAMPLES)
    for name, content in documents.items():
        expected_format = EXPECTED_SAMPLES[name]
        text = extract_text(content, expected_format=expected_format)
        assert detect_file_type(content) in {expected_format, "txt"}
        assert "Northstar" in text
        assert "fictional" in text.lower() or expected_format == "csv"
        assert "/home/" not in text
        assert "@" not in text


def test_extension_and_detected_content_must_agree() -> None:
    documents = sample_documents()

    with pytest.raises(ExtractionError) as raised:
        extract_text(documents["northstar-quarterly-brief.pdf"], expected_format="txt")

    assert raised.value.code == "format_mismatch"
    assert raised.value.status_code == 415

    csv_text = documents["northstar-quarterly-brief.csv"]
    assert extract_text(csv_text, expected_format="csv").startswith("metric, previous")


@pytest.mark.parametrize(
    ("content", "expected_format", "expected_code"),
    [
        (b"", "txt", "empty_file"),
        (b"MZ\x00" + b"\x00" * 100, None, "unsupported_format"),
        (b"%PDF-1.4\nthis is not a valid PDF", "pdf", "invalid_document"),
        (b"PK damaged OOXML package", "docx", "invalid_document"),
        (
            b"<!doctype html><html><script>no visible text</script></html>",
            "html",
            "empty_document",
        ),
    ],
)
def test_extraction_failures_have_stable_codes(
    content: bytes,
    expected_format: str | None,
    expected_code: str,
) -> None:
    with pytest.raises(ExtractionError) as raised:
        extract_text(content, expected_format=expected_format)

    assert raised.value.code == expected_code


def test_highly_compressed_docx_is_rejected_before_document_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/word/document.xml" ContentType="'
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
                '"/></Types>'
            ),
        )
        archive.writestr(
            "word/document.xml",
            b"A" * (DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES + 1),
        )

    def fail_if_parser_runs(_: io.BytesIO) -> None:
        raise AssertionError("python-docx must not parse an unsafe archive")

    monkeypatch.setattr("backend.pipeline.extractor.Document", fail_if_parser_runs)

    with pytest.raises(ExtractionError) as raised:
        extract_text(archive_bytes.getvalue(), expected_format="docx")

    assert raised.value.code == "unsafe_archive"
    assert raised.value.message == "The DOCX archive exceeds safe extraction limits."


def test_docx_metadata_rejects_all_bounded_archive_hazards() -> None:
    def member(
        name: str,
        *,
        size: int = 1,
        compressed: int = 1,
        encrypted: bool = False,
    ) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(name)
        info.file_size = size
        info.compress_size = compressed
        info.flag_bits = 1 if encrypted else 0
        return info

    member_count_hazard = [
        member(f"word/item-{index}.xml") for index in range(DOCX_MAX_MEMBERS + 1)
    ]
    total_size_piece = DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES // 3 + 1
    unsafe_member_sets = {
        "member count": member_count_hazard,
        "total size": [
            member(f"word/item-{index}.xml", size=total_size_piece, compressed=total_size_piece)
            for index in range(3)
        ],
        "member size": [
            member(
                "word/document.xml",
                size=DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES + 1,
                compressed=DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES + 1,
            )
        ],
        "compression ratio": [member("word/document.xml", size=101, compressed=1)],
        "unsafe path": [member("../word/document.xml")],
        "duplicate critical name": [
            member("[Content_Types].xml"),
            member("[Content_Types].xml"),
        ],
        "encrypted member": [member("word/document.xml", encrypted=True)],
        "content types size": [
            member(
                "[Content_Types].xml",
                size=DOCX_MAX_CONTENT_TYPES_BYTES + 1,
                compressed=DOCX_MAX_CONTENT_TYPES_BYTES + 1,
            )
        ],
    }

    for members in unsafe_member_sets.values():
        with pytest.raises(DocxArchiveSafetyError):
            validate_docx_members(members)


def test_cleaning_removes_controls_and_preserves_bounded_paragraphs() -> None:
    source = "  First\t line.\r\n\r\n\x00\u200bSecond   line.\n\n\n\nThird.  "

    cleaned = clean_text(source)
    chunks = chunk_text(cleaned, max_chars=20)

    assert cleaned == "First line.\n\nSecond line.\n\nThird."
    assert "".join(chunks).replace("\n\n", "") == cleaned.replace("\n\n", "")
    assert all(chunk and len(chunk) <= 20 for chunk in chunks)


def test_chunker_hard_splits_oversized_paragraphs() -> None:
    chunks = chunk_text("A" * 25 + "\n\nshort", max_chars=10)

    assert chunks == ["A" * 10, "A" * 10, "A" * 5, "short"]
    with pytest.raises(ValueError, match="positive"):
        chunk_text("text", max_chars=0)


def test_all_five_formats_complete_offline_api_flow(settings: Settings) -> None:
    documents = sample_documents()

    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        repository: JobRepository = app.state.jobs

        for name, content in documents.items():
            input_format = EXPECTED_SAMPLES[name]
            response = await client.post(
                "/process",
                files={"file": (name, content, UPLOAD_MIMES[input_format])},
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]

            job_response = await client.get(f"/jobs/{job_id}")
            assert job_response.status_code == 200
            assert job_response.json()["status"] == Status.COMPLETED.value
            assert job_response.json()["input_format"] == input_format

            result_response = await client.get(f"/jobs/{job_id}/result")
            assert result_response.status_code == 200
            result = result_response.json()
            assert result["summary"]
            assert result["key_points"]
            assert result["word_count"] > 0
            assert result["metadata"]["mode"] == "demo"
            assert result["metadata"]["input_format"] == input_format

        assert repository.count() == 5

    run_with_app(settings, check)


def test_rejected_documents_leave_no_orphan_jobs(settings: Settings) -> None:
    cases = (
        ("empty.txt", b"", "text/plain", "empty_file"),
        (
            "scan.html",
            b"<!doctype html><html><style>nothing</style></html>",
            "text/html",
            "empty_document",
        ),
        ("broken.pdf", b"%PDF-1.4\nbroken", "application/pdf", "invalid_document"),
    )

    async def check(client: httpx.AsyncClient, app: FastAPI) -> None:
        repository: JobRepository = app.state.jobs
        for name, content, mime, code in cases:
            response = await client.post("/process", files={"file": (name, content, mime)})
            assert response.status_code == 422
            assert response.json()["detail"]["code"] == code
            assert repository.count() == 0

    run_with_app(settings, check)
