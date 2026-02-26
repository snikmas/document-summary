import uuid
from config import Status
jobs = {}

def create_job():
    jobs_id = str(uuid.uuid4())
    job = {
        'status': Status.PENDING,
        'result': None,
        'error': None
    }
    jobs[jobs_id] = job
    return jobs_id

