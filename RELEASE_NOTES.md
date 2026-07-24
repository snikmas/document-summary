# Release notes

## 0.1.0 — portfolio release

This release turns the original document-summary prototype into a reproducible
product demonstration.

### Added

- Deterministic offline demo mode and provider-neutral OpenRouter integration.
- Typed configuration with clear live-mode credential validation.
- Durable SQLite jobs, explicit lifecycle transitions, restart recovery, and
  stable API error envelopes.
- Safe intake and extraction for PDF, DOCX, TXT, HTML, and CSV.
- Deterministic fictional sample documents and full five-format integration
  coverage.
- DOCX archive-expansion safeguards.
- Complete Streamlit buyer journey with bundled samples and recovery states.
- Markdown, DOCX, and constrained PDF exports.
- Offline tests, Ruff quality gates, GitHub Actions, Dockerfile, and Compose.

### Deliberate limitations

- No OCR, authentication, distributed queue, multi-tenant isolation, or public
  deployment.
- In-process jobs interrupted by a restart are marked failed and require a new
  upload.
- PDF output supports Latin-1; use Markdown or DOCX for other scripts.
