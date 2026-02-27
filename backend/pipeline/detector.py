import logging

import magic
from backend.pipeline.constants import EXTENSION_MAP

logger = logging.getLogger(__name__)

def detect_file_type(file_bytes: bytes) -> str:
    mime_type = magic.from_buffer(file_bytes[:2048], mime=True)
    logger.info("Detected MIME type: %s", mime_type)

    if '/' not in mime_type:
        raise ValueError(f"Invalid MIME type: {mime_type}")

    subtype = mime_type.split('/')[1].lower()

    if subtype in EXTENSION_MAP:
        file_type = EXTENSION_MAP[subtype]
        logger.info("Mapped to file type: %s", file_type)
        return file_type
    else:
        raise ValueError(f"Unsupported file type: {mime_type}")
