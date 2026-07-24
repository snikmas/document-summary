from streamlit.testing.v1 import AppTest

from frontend.app import SAMPLE_ARCHIVE, format_bytes, get_api_url, load_bundled_samples


def test_api_url_is_configurable_and_invalid_values_are_safe() -> None:
    assert get_api_url({"BACKEND_API_URL": "http://api:9000/"}) == "http://api:9000"
    assert get_api_url({"BACKEND_API_URL": "file:///private/socket"}) == ("http://127.0.0.1:8000")


def test_format_bytes() -> None:
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(2 * 1024**2) == "2.0 MB"


def test_bundled_zip_exposes_exactly_the_five_safe_formats() -> None:
    samples = load_bundled_samples(SAMPLE_ARCHIVE)

    assert set(samples) == {"pdf", "docx", "txt", "html", "csv"}
    assert all(sample.content for sample in samples.values())
    assert all("/" not in sample.name and "\\" not in sample.name for sample in samples.values())


def test_frontend_initial_view_explains_product_and_offline_state() -> None:
    app = AppTest.from_string(
        """
from frontend import app

def unavailable(*args, **kwargs):
    raise app.ApiProblem("offline", code="backend_unavailable")

app.api_get = unavailable
app.main()
"""
    )

    app.run(timeout=5)

    assert not app.exception
    visible = "\n".join(
        element.value
        for collection in (
            app.title,
            app.caption,
            app.info,
            app.markdown,
            app.warning,
        )
        for element in collection
    )
    assert "Document Intelligence Pipeline" in visible
    assert "PDF, DOCX, TXT, HTML, and CSV" in visible
    assert "OCR is not included" in visible
    assert "UNKNOWN" in visible
    assert "unavailable" in visible
    assert app.button[0].disabled


def test_frontend_bundled_sample_completes_buyer_journey() -> None:
    app = AppTest.from_string(
        """
from frontend import app

RESULT = {
    "summary": "The quarter finished ahead of plan.",
    "key_points": ["Revenue grew", "Response time improved"],
    "language": "English",
    "word_count": 137,
    "metadata": {
        "mode": "demo",
        "provider": "deterministic",
        "requested_model": "deterministic-extractive-v1",
        "routed_model": None,
        "input_format": "csv",
        "chunk_count": 2,
        "processing_time_ms": 41,
    },
}

def fake_get(api_url, path):
    if path == "/health":
        return {"status": "ok", "mode": "demo"}
    if path.endswith("/result"):
        return RESULT
    return {
        "job_id": "safe-job",
        "status": "done",
        "filename": "northstar-quarterly-brief.csv",
        "input_format": "csv",
        "byte_size": 133,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
        "error": None,
    }

def fake_upload(api_url, document):
    return {"job_id": "safe-job", "status": "pending"}

app.api_get = fake_get
app.api_upload = fake_upload
app.main()
"""
    )
    app.run(timeout=5)
    app.selectbox[0].select("csv").run(timeout=5)
    app.button[0].click().run(timeout=5)
    app.run(timeout=5)

    assert not app.exception
    visible = "\n".join(
        element.value
        for collection in (app.success, app.subheader, app.markdown, app.metric)
        for element in collection
    )
    for expected in (
        "Document analysis complete",
        "The quarter finished ahead of plan.",
        "Revenue grew",
        "Response time improved",
        "English",
        "137",
        "demo",
        "deterministic",
        "deterministic-extractive-v1",
        "CSV",
        "2",
        "41 ms",
    ):
        assert expected in visible
    assert {button.label for button in app.download_button} == {
        "Markdown",
        "Word (.docx)",
        "PDF",
    }
    assert any(button.label == "Process another document" for button in app.button)
