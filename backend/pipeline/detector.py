# detect the file type
import magic
from backend.pipeline.constants import EXTENSION_MAP

def detect_file_type(file) -> str:
    #it wont crash if 2048>, just opens all that it has
    with open (file, 'rb') as f:
        data = f.read(2048)
    mime_type = magic.from_buffer(data, mime=True)

    parts = mime_type.split('/')
    if len(parts) > 1:
        subtype = parts[1].lower()

    if subtype in EXTENSION_MAP:
        return subtype
    else:
        raise ValueError(f"Unsupported file type: {subtype}")
