import io

import pytest
from docx import Document

from frontend.exports import (
    PdfCharacterError,
    build_docx,
    build_markdown,
    build_pdf,
)


@pytest.fixture
def result() -> dict:
    return {
        "summary": "Revenue grew while response times improved.",
        "key_points": ["Revenue increased", "Support became faster"],
        "language": "English",
        "word_count": 137,
        "metadata": {
            "mode": "demo",
            "provider": "deterministic",
            "requested_model": "deterministic-extractive-v1",
            "routed_model": None,
            "input_format": "docx",
            "chunk_count": 2,
            "processing_time_ms": 41,
        },
    }


def test_markdown_contains_result_and_all_metadata(result: dict) -> None:
    text = build_markdown(result).decode("utf-8")

    for expected in (
        result["summary"],
        *result["key_points"],
        "English",
        "137",
        "demo",
        "deterministic",
        "deterministic-extractive-v1",
        "Not applicable",
        "DOCX",
        "2",
        "41 ms",
    ):
        assert str(expected) in text


def test_docx_is_openable_and_unicode_safe(result: dict) -> None:
    result["summary"] = "中文摘要 — résumé"
    result["key_points"] = ["增长", "Qualité améliorée"]

    payload = build_docx(result)
    document = Document(io.BytesIO(payload))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert payload.startswith(b"PK")
    assert "中文摘要" in text
    assert "增长" in text
    assert "Processing time: 41 ms" in text


def test_pdf_is_openable_for_latin1_result(result: dict) -> None:
    payload = build_pdf(result)

    assert payload.startswith(b"%PDF-")
    assert payload.rstrip().endswith(b"%%EOF")


def test_pdf_rejects_unsupported_unicode_instead_of_corrupting(result: dict) -> None:
    result["summary"] = "中文摘要"

    with pytest.raises(PdfCharacterError, match="Latin-1"):
        build_pdf(result)
