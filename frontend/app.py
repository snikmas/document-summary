"""Streamlit buyer journey for the Document Intelligence Pipeline."""

from __future__ import annotations

import mimetypes
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import requests
import streamlit as st

from frontend.exports import (
    PdfCharacterError,
    build_docx,
    build_markdown,
    build_pdf,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_ARCHIVE = PROJECT_ROOT / "samples"
SUPPORTED_TYPES = ("pdf", "docx", "txt", "html", "csv")
POLL_TIMEOUT_SECONDS = 300.0
POLL_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class SelectedDocument:
    name: str
    content: bytes
    content_type: str
    source: str


class ApiProblem(RuntimeError):
    """A client-safe API or connection error."""

    def __init__(self, message: str, *, code: str = "request_failed", status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


def get_api_url(environ: dict[str, str] | None = None) -> str:
    """Return a separately configurable UI-to-API URL."""

    values = os.environ if environ is None else environ
    value = values.get("BACKEND_API_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "http://127.0.0.1:8000"
    return value


def format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024**2:
        return f"{value / 1024:.1f} KB"
    return f"{value / 1024**2:.1f} MB"


def load_bundled_samples(archive: Path = SAMPLE_ARCHIVE) -> dict[str, SelectedDocument]:
    """Read only safe, supported regular files from the generated sample ZIP."""

    samples: dict[str, SelectedDocument] = {}
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            path = PurePosixPath(info.filename)
            extension = path.suffix.lower().lstrip(".")
            if (
                info.is_dir()
                or path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 1
                or extension not in SUPPORTED_TYPES
            ):
                continue
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            samples[extension] = SelectedDocument(
                name=path.name,
                content=bundle.read(info),
                content_type=content_type,
                source="Bundled sample",
            )
    return samples


def api_error(response: requests.Response, fallback: str) -> ApiProblem:
    code = "request_failed"
    message = fallback
    try:
        body = response.json()
        detail = body.get("detail", body) if isinstance(body, dict) else {}
        if isinstance(detail, dict):
            code = str(detail.get("code") or code)
            message = str(detail.get("message") or message)
    except (ValueError, TypeError):
        pass
    return ApiProblem(message, code=code, status=response.status_code)


def api_get(api_url: str, path: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{api_url}{path}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise ApiProblem(
            "The API is unavailable. Start the backend, then try again.",
            code="backend_unavailable",
        ) from exc
    if not response.ok:
        raise api_error(response, "The API could not complete the request.")
    return response.json()


def api_upload(api_url: str, document: SelectedDocument) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{api_url}/process",
            files={"file": (document.name, document.content, document.content_type)},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise ApiProblem(
            "The API is unavailable. Your document was not submitted.",
            code="backend_unavailable",
        ) from exc
    if not response.ok:
        raise api_error(response, "The document could not be submitted.")
    return response.json()


def reset_job() -> None:
    st.session_state.job_id = None
    st.session_state.poll_started_at = None
    st.session_state.last_result = None
    st.session_state.job_filename = None


def initialize_state() -> None:
    defaults = {
        "job_id": None,
        "poll_started_at": None,
        "last_result": None,
        "job_filename": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_guidance(mode: str | None) -> None:
    mode_label = (
        "DEMO — deterministic, offline summarizer"
        if mode == "demo"
        else ("LIVE — OpenRouter inference" if mode == "openrouter" else "UNKNOWN — API offline")
    )
    st.info(f"Current mode: **{mode_label}**")
    st.markdown(
        """
        **Before you upload**

        - Supported: text-based **PDF, DOCX, TXT, HTML, and CSV**, up to the
          server's configured limit.
        - Uploaded bytes are held only while processing. Results and safe file
          metadata are stored in SQLite.
        - **OCR is not included.** Scanned or image-only PDFs need an OCR
          service before they can be summarized.
        """
    )


def select_document() -> SelectedDocument | None:
    method = st.radio(
        "Choose a document source",
        ("Try a bundled sample", "Upload my document"),
        horizontal=True,
    )
    if method == "Try a bundled sample":
        try:
            samples = load_bundled_samples()
        except (OSError, zipfile.BadZipFile):
            st.error("Bundled samples are unavailable. Upload a document instead.")
            return None
        if not samples:
            st.error("No safe supported files were found in the sample bundle.")
            return None
        extension = st.selectbox(
            "Sample format",
            tuple(sorted(samples)),
            format_func=lambda value: value.upper(),
        )
        return samples[extension]

    uploaded = st.file_uploader("Upload a document", type=SUPPORTED_TYPES)
    if uploaded is None:
        return None
    return SelectedDocument(
        name=uploaded.name,
        content=uploaded.getvalue(),
        content_type=uploaded.type or "application/octet-stream",
        source="Your upload",
    )


def render_document_metadata(document: SelectedDocument) -> None:
    extension = Path(document.name).suffix.lstrip(".").upper() or "Unknown"
    first, second, third = st.columns(3)
    first.metric("Format", extension)
    second.metric("Size", format_bytes(len(document.content)))
    third.metric("Source", document.source)
    st.caption(f"Selected file: `{document.name}`")


def render_metadata(metadata: dict[str, Any]) -> None:
    st.subheader("Processing details")
    fields = (
        ("Mode", metadata.get("mode")),
        ("Provider", metadata.get("provider")),
        ("Requested model", metadata.get("requested_model")),
        ("Routed model", metadata.get("routed_model") or "Not applicable"),
        ("Input format", str(metadata.get("input_format", "")).upper()),
        ("Chunks", metadata.get("chunk_count")),
        ("Processing time", f"{metadata.get('processing_time_ms', 0)} ms"),
    )
    for row in range(0, len(fields), 3):
        columns = st.columns(3)
        for column, (label, value) in zip(columns, fields[row : row + 3], strict=False):
            column.metric(label, value if value is not None else "N/A")


def render_downloads(result: dict[str, Any], stem: str) -> None:
    safe_name = PurePosixPath(stem.replace("\\", "/")).name
    safe_stem = Path(safe_name).stem or "document"
    st.subheader("Download the result")
    markdown = build_markdown(result)
    docx = build_docx(result)
    columns = st.columns(3)
    columns[0].download_button(
        "Markdown",
        markdown,
        file_name=f"{safe_stem}-summary.md",
        mime="text/markdown; charset=utf-8",
        use_container_width=True,
    )
    columns[1].download_button(
        "Word (.docx)",
        docx,
        file_name=f"{safe_stem}-summary.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        use_container_width=True,
    )
    try:
        pdf = build_pdf(result)
    except PdfCharacterError:
        columns[2].button("PDF unavailable", disabled=True, use_container_width=True)
        st.caption(
            "PDF export supports Latin-1 text only in this lightweight build. "
            "Use Markdown or Word for Unicode results."
        )
    else:
        columns[2].download_button(
            "PDF",
            pdf,
            file_name=f"{safe_stem}-summary.pdf",
            mime="application/pdf",
            use_container_width=True,
        )


def render_result(result: dict[str, Any], filename: str) -> None:
    st.success("Document analysis complete.")
    first, second = st.columns(2)
    first.metric("Language", result.get("language", "N/A"))
    second.metric("Source word count", result.get("word_count", "N/A"))
    st.subheader("Summary")
    st.write(result.get("summary", ""))
    st.subheader("Key points")
    for point in result.get("key_points", []):
        st.markdown(f"- {point}")
    render_metadata(result.get("metadata", {}))
    render_downloads(result, filename)
    if st.button("Process another document", type="primary"):
        reset_job()
        st.rerun()


def render_recovery(message: str, *, stale: bool = False) -> None:
    st.error(message)
    if stale:
        st.caption("This job no longer exists on the backend. Start a new analysis.")
    if st.button("Start over"):
        reset_job()
        st.rerun()


def render_active_job(api_url: str) -> None:
    job_id = st.session_state.job_id
    if not job_id:
        return
    if st.session_state.last_result is not None:
        render_result(
            st.session_state.last_result,
            st.session_state.job_filename or "document",
        )
        return

    try:
        status_data = api_get(api_url, f"/jobs/{job_id}")
    except ApiProblem as exc:
        render_recovery(str(exc), stale=exc.code == "job_not_found" or exc.status == 404)
        return

    status = status_data.get("status")
    st.caption(f"Job ID: `{job_id}`")
    if status in {"pending", "processing"}:
        started = st.session_state.poll_started_at or time.monotonic()
        st.session_state.poll_started_at = started
        if time.monotonic() - started > POLL_TIMEOUT_SECONDS:
            render_recovery("Processing timed out in this browser. The job may still be running.")
            return
        label = (
            "Queued — waiting for the worker to start."
            if status == "pending"
            else "Processing — extracting and summarizing the document."
        )
        st.status(label, state="running")
        time.sleep(POLL_INTERVAL_SECONDS)
        st.rerun()
        return

    if status == "failed":
        detail = status_data.get("error") or {}
        render_recovery(
            str(detail.get("message") or "Processing failed. Please try another document.")
        )
        return

    if status != "done":
        render_recovery("The API returned an unknown job state. Start a new analysis.")
        return

    try:
        result = api_get(api_url, f"/jobs/{job_id}/result")
    except ApiProblem as exc:
        render_recovery(str(exc), stale=exc.code == "job_not_found" or exc.status == 404)
        return
    st.session_state.last_result = result
    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Document Intelligence Pipeline",
        page_icon="📄",
        layout="centered",
    )
    initialize_state()
    api_url = get_api_url()

    st.title("Document Intelligence Pipeline")
    st.caption(
        "Turn everyday business documents into a structured summary and downloadable deliverable."
    )
    try:
        health = api_get(api_url, "/health")
        mode = str(health.get("mode"))
        backend_ready = True
    except ApiProblem:
        mode = None
        backend_ready = False
    render_guidance(mode)

    if st.session_state.job_id:
        render_active_job(api_url)
        return

    document = select_document()
    if document is None:
        return
    render_document_metadata(document)

    if not backend_ready:
        st.warning(f"The backend at `{api_url}` is unavailable. Start it, then refresh this page.")
    if st.button(
        "Analyze document",
        type="primary",
        disabled=not backend_ready,
        use_container_width=True,
    ):
        try:
            accepted = api_upload(api_url, document)
        except ApiProblem as exc:
            st.error(str(exc))
            return
        st.session_state.job_id = accepted["job_id"]
        st.session_state.job_filename = document.name
        st.session_state.poll_started_at = time.monotonic()
        st.session_state.last_result = None
        st.rerun()


if __name__ == "__main__":
    main()
