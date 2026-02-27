import logging

import magic
from backend.pipeline.constants import EXTENSION_MAP

log = logging.getLogger("pipeline.detector")


def detect_file_type(file_bytes: bytes) -> str:
    mime_type = magic.from_buffer(file_bytes[:2048], mime=True)
    log.info("Detected MIME type: %s", mime_type)

    if '/' not in mime_type:
        raise ValueError(f"Invalid MIME type: {mime_type}")

    subtype = mime_type.split('/')[1].lower()

    if subtype in EXTENSION_MAP:
        file_type = EXTENSION_MAP[subtype]
        log.info("Mapped to file type: %s", file_type)
        return file_type
    else:
        raise ValueError(f"Unsupported file type: {mime_type}")
