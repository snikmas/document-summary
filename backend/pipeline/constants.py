SUPPORTED_FORMATS = frozenset({"pdf", "docx", "txt", "html", "csv"})

# libmagic reports CSV as either text/csv or text/plain depending on the host's
# magic database. The extractor resolves that one ambiguity against the
# filename extension.
MIME_FORMATS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/csv": "csv",
    "application/csv": "csv",
}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# DOCX is a ZIP container. These limits are checked from the central directory
# before python-docx is allowed to decompress any member.
DOCX_MAX_MEMBERS = 512
DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
DOCX_MAX_COMPRESSION_RATIO = 100
DOCX_MAX_CONTENT_TYPES_BYTES = 256 * 1024
