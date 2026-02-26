from fastapi import FastAPI, BackgroundTasks, UploadFile, HTTPException
from jobs import create_job, jobs
from backend.pipeline.extractor import extract_text
from backend.pipeline.cleaner import clean_text
from backend.pipeline.llm import get_summary_from_llm
from backend.pipeline.chunker import chunk_text
from config import Status

app = FastAPI()


def run_pipeline(job_id: str, filename: str, file_bytes: bytes):
    jobs[job_id]['status'] = Status.PROCESSING

    try: 
        extracted_text = extract_text(filename, file_bytes)    
        cleaned_text = clean_text(extracted_text)
        chunked_text = chunk_text(cleaned_text) #doesnt it used in the summaries or ?
        res = get_summary_from_llm(chunked_text)

        jobs[job_id]['status'] = Status.DONE
        jobs[job_id]['result'] = res
    except Exception as e:
        jobs[job_id]['status'] = Status.FAILED
        jobs[job_id]['error'] = str(e)


# here we upload our file
# create a job
@app.post('/process')
async def upload_file(file: UploadFile, background_tasks: BackgroundTasks):
    job_id = create_job()
    file_bytes = await file.read()
    background_tasks.add_task(run_pipeline, job_id, file.filename, file_bytes)

    return {'job_id': job_id}


# get a job: this func is trying to find this job in a dict
# from a user perspective: do we really need this /jobs links? for users it doesnt amke any sense
@app.get('/jobs/{job_id}')
async def get_job(job_id: str):
    #getresut or what?
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {'status': job['status']}


@app.get('/jobs/{job_id}/result')
async def get_result_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job['status'] is not Status.DONE:
        raise HTTPException(status_code=400, detail='Job not ready')
    return job['result']
