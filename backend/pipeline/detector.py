# detect the file type
import magic
from backend.pipeline.constants import EXTENSION_MAP

def detect_file_type(file_bytes: bytes) -> str:
    mime_type = magic.from_buffer(file_bytes[:2048], mime=True)

    if '/' not in mime_type:
        raise ValueError(f"Invalid MIME type: {mime_type}")

    subtype = mime_type.split('/')[1].lower()

    if subtype in EXTENSION_MAP:
        return EXTENSION_MAP[subtype]
    else:
        raise ValueError(f"Unsupported file type: {mime_type}")
