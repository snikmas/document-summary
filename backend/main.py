import logging

from fastapi import FastAPI, BackgroundTasks, UploadFile, HTTPException
from backend.jobs import create_job, jobs
from backend.pipeline.extractor import extract_text
from backend.pipeline.cleaner import clean_text
from backend.pipeline.llm import get_summary_from_llm
from backend.pipeline.chunker import chunk_text
from backend.config import Status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB


def run_pipeline(job_id: str, file_bytes: bytes):
    logger.info("Job %s — starting pipeline (%d bytes)", job_id, len(file_bytes))
    jobs[job_id]['status'] = Status.PROCESSING

    try:
        logger.info("Job %s — detecting file type & extracting text", job_id)
        extracted_text = extract_text(file_bytes)
        logger.info("Job %s — extracted %d chars", job_id, len(extracted_text))

        logger.info("Job %s — cleaning text", job_id)
        cleaned_text = clean_text(extracted_text)

        logger.info("Job %s — chunking text", job_id)
        chunked_text = chunk_text(cleaned_text)
        logger.info("Job %s — produced %d chunk(s)", job_id, len(chunked_text))

        logger.info("Job %s — sending to LLM for summarization", job_id)
        res = get_summary_from_llm(chunked_text)
        logger.info("Job %s — summarization complete", job_id)

        jobs[job_id]['status'] = Status.DONE
        jobs[job_id]['result'] = res
        logger.info("Job %s — done", job_id)
    except Exception as e:
        jobs[job_id]['status'] = Status.FAILED
        jobs[job_id]['error'] = str(e)
        logger.error("Job %s — failed: %s", job_id, e)


@app.post('/process')
async def upload_file(file: UploadFile, background_tasks: BackgroundTasks):
    logger.info("Received file upload: %s (%s)", file.filename, file.content_type)
    job_id = create_job()
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        logger.warning("Upload rejected — file too large (%d bytes)", len(file_bytes))
        raise HTTPException(status_code=413, detail="File too large. Maximum upload size is 50 MB.")
    logger.info("Created job %s for %s (%d bytes)", job_id, file.filename, len(file_bytes))
    background_tasks.add_task(run_pipeline, job_id, file_bytes)

    return {'job_id': job_id}


@app.get('/jobs/{job_id}')
async def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    data = {'status': job['status'].value}
    if job['error']:
        data['error'] = job['error']
    return data


@app.get('/jobs/{job_id}/result')
async def get_result_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job['status'] is not Status.DONE:
        raise HTTPException(status_code=400, detail='Job not ready')
    return job['result']
