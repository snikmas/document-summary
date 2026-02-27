# Document Intelligence Pipeline

Upload a document — PDF, DOCX, TXT, HTML, or CSV — and get back a structured AI-powered summary with key points, detected language, and word count. Built as two separate services (FastAPI backend + Streamlit frontend) communicating over HTTP, mirroring real production architecture.

## Architecture

```
┌──────────────────┐        HTTP        ┌──────────────────────────────┐
│  Streamlit UI    │ ◄────────────────► │  FastAPI Backend             │
│  (port 8501)     │                    │  (port 8000)                 │
│                  │  POST /process     │                              │
│  Upload file ────┼──────────────────► │  ┌────────────────────────┐  │
│                  │  { job_id }        │  │ Pipeline               │  │
│  Poll status ────┼──────────────────► │  │  detector  → extractor │  │
│                  │  { status }        │  │  → cleaner → chunker   │  │
│  Fetch result ───┼──────────────────► │  │  → LLM summarizer      │  │
│                  │  { summary }       │  └────────────────────────┘  │
└──────────────────┘                    └──────────────────────────────┘
```

## How It Works

1. **Upload** — User selects a file in the Streamlit UI and clicks "Summarize it"
2. **Detect** — `python-magic` reads file bytes to determine MIME type
3. **Extract** — Format-specific extractor pulls plain text (pypdf, python-docx, BeautifulSoup, csv)
4. **Clean** — Unicode normalization (NFKC), null byte removal, whitespace collapsing
5. **Chunk** — Text is split by paragraph boundaries into chunks of ~8000 characters
6. **Summarize** — Each chunk is sent to Google Gemini, responses are validated against a Pydantic schema
7. **Merge** — Multi-chunk documents get a final merge pass through the LLM
8. **Return** — Structured JSON result: summary, key points, language, word count

Jobs are processed asynchronously — the upload returns instantly with a `job_id`, and the frontend polls for status every 2 seconds.

## Supported Formats

| Format | Library | Notes |
|--------|---------|-------|
| PDF | `pypdf` | Extracts text from all pages |
| DOCX | `python-docx` | Paragraph-level text extraction |
| HTML | `beautifulsoup4` | Strips scripts, styles, and tags |
| CSV | `csv` (stdlib) | Converts rows to readable text |
| TXT | — | UTF-8 decode with error replacement |

## Setup

### 1. Install dependencies

```bash
pip install fastapi uvicorn google-generativeai pypdf python-docx beautifulsoup4 python-magic python-dotenv pydantic streamlit requests python-multipart
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
GEMINI_KEY=your_gemini_api_key
MAX_CHUNK_SIZE=8000
```

Get a Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 3. Run

Start both services in separate terminals:

```bash
# Terminal 1 — Backend
uvicorn backend.main:app --reload

# Terminal 2 — Frontend
streamlit run frontend/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/process` | Upload a file (multipart), returns `{ "job_id": "..." }` |
| `GET` | `/jobs/{job_id}` | Poll job status: `pending` → `processing` → `done` / `failed` |
| `GET` | `/jobs/{job_id}/result` | Fetch result (only when status is `done`) |

You can test the API directly at [http://localhost:8000/docs](http://localhost:8000/docs) (auto-generated Swagger UI).

## Project Structure

```
backend/
├── main.py              FastAPI app, endpoints, background pipeline runner
├── config.py            Environment variables (GEMINI_KEY, MAX_CHUNK_SIZE), Status enum
├── models.py            DocumentSummary Pydantic model
├── jobs.py              In-memory job store (dict keyed by UUID)
└── pipeline/
    ├── detector.py      MIME type detection via python-magic
    ├── extractor.py     Per-format text extraction (match/case routing)
    ├── cleaner.py       Text normalization (unicode, whitespace, null bytes)
    ├── chunker.py       Paragraph-aware text splitting
    ├── llm.py           Gemini API calls, JSON parsing, retry logic
    └── constants.py     MIME subtype → canonical type mapping
frontend/
└── app.py               Streamlit UI (upload, polling, result display, download)
```

## Error Handling

- **Unsupported file type** — Backend raises `ValueError`, frontend shows error message
- **LLM quota exceeded (429)** — Caught and reported as "AI service quota exceeded"
- **LLM server errors (5xx)** — Reported as "AI service temporarily unavailable"
- **Invalid LLM response** — Pydantic validation catches malformed JSON, retries once
- **File too large** — Backend rejects uploads over 50 MB with HTTP 413
- **Polling timeout** — Frontend stops polling after 5 minutes and shows timeout error

## What I'd Add With More Time

- **Tests** — Unit tests per pipeline stage with sample documents (corrupted, empty, wrong extension, non-English)
- **Chunk overlap** — ~200 character overlap between adjacent chunks to preserve context at boundaries
- **Extension fallback** — Fall back to filename extension when MIME detection is ambiguous (e.g., DOCX detected as ZIP)
- **Persistent job store** — Replace in-memory dict with Redis or SQLite for crash resilience
- **Swappable LLM provider** — Config-driven provider selection (Gemini, Claude, Groq) without code changes
- **Rate limiting** — Prevent abuse on the upload endpoint
- **Streaming progress** — WebSocket or SSE for real-time pipeline stage updates instead of simple polling
