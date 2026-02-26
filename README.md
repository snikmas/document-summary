# Document Intelligence Pipeline

Multi-format document processing pipeline that extracts text from uploaded files, processes it through an AI model, and returns structured summaries.

## Supported Formats

- PDF
- DOCX
- TXT
- HTML
- CSV

## How It Works

1. Upload a file through the web UI
2. Backend detects the file type and extracts text
3. Text is cleaned (unicode normalization, whitespace cleanup)
4. Text is split into chunks that fit the LLM context
5. Each chunk is summarized via Google Gemini API
6. A final structured summary is returned with key points, language, and word count

## Tech Stack

- **Backend:** FastAPI (async, background tasks)
- **Frontend:** Streamlit
- **LLM:** Google Gemini 2.0 Flash
- **Text Extraction:** pypdf, python-docx, BeautifulSoup4, python-magic

## Setup

### 1. Install dependencies

```bash
pip install fastapi uvicorn google-generativeai pypdf python-docx beautifulsoup4 python-magic python-dotenv pydantic streamlit requests
```

### 2. Configure environment

Create a `.env` file in the project root:

```env
GEMINI_KEY=your_gemini_api_key
MAX_CHUNK_SIZE=8000
```

Get your Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 3. Run

```bash
# Terminal 1 — Backend (port 8000)
uvicorn backend.main:app --reload

# Terminal 2 — Frontend (port 8501)
streamlit run frontend/app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/process` | Upload a file, returns `job_id` |
| GET | `/jobs/{job_id}` | Check job status (`pending`, `processing`, `done`, `failed`) |
| GET | `/jobs/{job_id}/result` | Get the summary result (when status is `done`) |

## Project Structure

```
backend/
    main.py          — FastAPI app, endpoints, background pipeline
    config.py        — env vars, Status enum
    models.py        — DocumentSummary pydantic model
    jobs.py          — in-memory job store
    pipeline/
        detector.py  — MIME type detection
        extractor.py — text extraction per format
        cleaner.py   — text normalization
        chunker.py   — paragraph-based text splitting
        llm.py       — Gemini API integration
        constants.py — MIME type mapping
frontend/
    app.py           — Streamlit UI
```
