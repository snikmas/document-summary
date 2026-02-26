import os
from dotenv import load_dotenv
from enum import Enum

load_dotenv()

GROQ_KEY = os.getenv('GROQ_KEY')
GEMINI_KEY = os.getenv('GEMINI_KEY')
MAX_CHUNK_SIZE = int(os.getenv('MAX_CHUNK_SIZE', 8000))


class Status(Enum):
    PENDING = 'pending'
    PROCESSING = 'processing'
    FAILED = 'failed'
    DONE = 'done'
