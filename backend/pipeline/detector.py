import logging
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

import magic

from backend.pipeline.constants import (
    DOCX_MAX_COMPRESSION_RATIO,
    DOCX_MAX_CONTENT_TYPES_BYTES,
    DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES,
    DOCX_MAX_MEMBERS,
    DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES,
    DOCX_MIME,
    MIME_FORMATS,
)

log = logging.getLogger("pipeline.detector")
_DOCX_CRITICAL_MEMBERS = frozenset({"[Content_Types].xml", "word/document.xml"})


class DocxArchiveSafetyError(ValueError):
    """Raised when DOCX ZIP metadata exceeds safe extraction boundaries."""


def detect_file_type(file_bytes: bytes) -> str:
    """Return a supported format based on the bytes, never a client MIME header."""

    if not file_bytes:
        raise ValueError("empty file")

    mime_type = magic.from_buffer(file_bytes[:2048], mime=True)
    mime_type = mime_type.split(";", 1)[0].strip().lower()
    log.debug("detected_mime=%s", mime_type)

    mapped = MIME_FORMATS.get(mime_type)
    if mapped:
        return mapped

    # Some minimal magic databases identify OOXML only as a generic ZIP.
    if mime_type in {"application/zip", "application/x-zip"} and _is_docx(file_bytes):
        return "docx"

    raise ValueError(f"unsupported MIME type: {mime_type or 'unknown'}")


def _is_docx(file_bytes: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
            members = archive.infolist()
            validate_docx_members(members)
            names = {member.filename for member in members}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                return False
            content_types = _read_bounded(
                archive,
                "[Content_Types].xml",
                DOCX_MAX_CONTENT_TYPES_BYTES,
            )
    except (KeyError, OSError, zipfile.BadZipFile):
        return False
    return DOCX_MIME.encode() in content_types


def validate_docx_archive(file_bytes: bytes) -> None:
    """Validate all DOCX ZIP metadata without decompressing archive members."""

    with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
        validate_docx_members(archive.infolist())


def validate_docx_members(members: list[zipfile.ZipInfo]) -> None:
    """Reject ZIP metadata that could make DOCX parsing consume unsafe resources."""

    if len(members) > DOCX_MAX_MEMBERS:
        raise DocxArchiveSafetyError("DOCX archive contains too many members")

    total_uncompressed = 0
    critical_counts = {name: 0 for name in _DOCX_CRITICAL_MEMBERS}
    for member in members:
        _validate_member_path(member.filename)
        if member.flag_bits & 0x1:
            raise DocxArchiveSafetyError("encrypted DOCX members are not supported")

        if member.filename in critical_counts:
            critical_counts[member.filename] += 1
            if critical_counts[member.filename] > 1:
                raise DocxArchiveSafetyError("DOCX archive has duplicate critical members")
        if (
            member.filename == "[Content_Types].xml"
            and member.file_size > DOCX_MAX_CONTENT_TYPES_BYTES
        ):
            raise DocxArchiveSafetyError("DOCX content-types metadata exceeds the limit")

        if member.is_dir():
            continue
        if member.file_size > DOCX_MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise DocxArchiveSafetyError("DOCX member exceeds the extraction limit")

        total_uncompressed += member.file_size
        if total_uncompressed > DOCX_MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise DocxArchiveSafetyError("DOCX archive exceeds the extraction limit")

        if member.file_size:
            if member.compress_size <= 0:
                raise DocxArchiveSafetyError("DOCX member has an unsafe compression ratio")
            ratio = member.file_size / member.compress_size
            if ratio > DOCX_MAX_COMPRESSION_RATIO:
                raise DocxArchiveSafetyError("DOCX member has an unsafe compression ratio")


def _validate_member_path(filename: str) -> None:
    if not filename or "\x00" in filename or "\\" in filename:
        raise DocxArchiveSafetyError("DOCX archive contains an unsafe member path")

    path = PurePosixPath(filename)
    if path.is_absolute() or ".." in path.parts:
        raise DocxArchiveSafetyError("DOCX archive contains an unsafe member path")
    if path.parts and path.parts[0].endswith(":"):
        raise DocxArchiveSafetyError("DOCX archive contains an unsafe member path")


def _read_bounded(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    member = archive.getinfo(name)
    if member.file_size > limit:
        raise DocxArchiveSafetyError("DOCX content-types metadata exceeds the limit")
    with archive.open(member) as source:
        content = source.read(limit + 1)
    if len(content) > limit:
        raise DocxArchiveSafetyError("DOCX content-types metadata exceeds the limit")
    return content
