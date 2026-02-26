import os
from dotenv import load_dotenv
from enum import Enum

load_dotenv()

GROQ_KEY = os.getenv('GROQ_API')
MAX_CHUNK_SIZE = os.getenv('MAX_CHUNK_SIZE')


class Status(Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    FAILED = 'failed'
    DONE = 'done'
