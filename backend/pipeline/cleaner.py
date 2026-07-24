import re
import unicodedata

_ALLOWED_CONTROLS = {"\n", "\t"}


def clean_text(text: str) -> str:
    """Normalize extracted text while preserving useful paragraph boundaries."""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character
        for character in text
        if character in _ALLOWED_CONTROLS or not unicodedata.category(character).startswith("C")
    )
    text = unicodedata.normalize("NFKC", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
