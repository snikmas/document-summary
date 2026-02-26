import os
from dotenv import load_dotenv
from enum import Enum

load_dotenv()

GROQ_KEY = os.getenv('GROQ_KEY')
MAX_CHUNK_SIZE = int(os.getenv('MAX_CHUNK_SIZE'))


class Status(Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    FAILED = 'failed'
    DONE = 'done'
