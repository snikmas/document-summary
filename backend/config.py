import os
from dotenv import load_dotenv

load_dotenv()

GROQ_KEY = os.getenv('GROQ_API')
MAX_CHUNK_SIZE = os.getenv('MAX_CHUNK_SIZE')