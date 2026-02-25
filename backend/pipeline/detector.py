# detect the file type
import magic
from backend.pipeline.constants import EXTENSION_MAP

def detect_file_type(filename: str, file_bytes: bytes) -> str:
    #it wont crash if 2048>, just opens all that it has
    # with open (file_bytes, 'rb') as f:
    # data = file_bytes.read(2048)
    mime_type = magic.from_buffer(file_bytes[:2048], mime=True)

    parts = mime_type.split('/')
    if len(parts) > 1:
        subtype = parts[1].lower()

    if subtype in EXTENSION_MAP:
        return subtype
    else:
        raise ValueError(f"Unsupported file type: {subtype}")
