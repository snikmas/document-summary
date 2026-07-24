"""Generate the project's original, legal-to-share five-format sample archive."""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_PATH = PROJECT_ROOT / "samples"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)

TITLE = "Northstar Studio Quarterly Brief"
PARAGRAPHS = (
    "Northstar Studio is a fictional company created for this portfolio demonstration.",
    "In the second quarter, revenue increased by twelve percent while support response "
    "time fell from nine hours to five hours.",
    "The team recommends expanding the customer onboarding guide, reviewing campaign "
    "costs, and tracking support satisfaction each month.",
)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _pdf_bytes() -> bytes:
    lines = (TITLE, *PARAGRAPHS)
    commands = ["BT", "/F1 11 Tf", "72 740 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -24 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")

    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    )
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def _docx_bytes() -> bytes:
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in (TITLE, *PARAGRAPHS)
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{paragraphs}<w:sectPr/></w:body></w:document>"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(_zip_info(name), content.encode("utf-8"))
    return buffer.getvalue()


def _sample_files() -> dict[str, bytes]:
    plain_text = f"{TITLE}\n\n" + "\n\n".join(PARAGRAPHS) + "\n"
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        "<title>Northstar sample</title><style>.hidden{display:none}</style></head>"
        f"<body><h1>{TITLE}</h1>"
        + "".join(f"<p>{escape(paragraph)}</p>" for paragraph in PARAGRAPHS)
        + "<script>privateNoise = 'not extracted';</script></body></html>"
    )
    csv_text = (
        "metric,previous,current\n"
        "Revenue growth,0 percent,12 percent\n"
        "Support response time,9 hours,5 hours\n"
        "Company,Fictional,Northstar Studio\n"
    )
    return {
        "northstar-quarterly-brief.pdf": _pdf_bytes(),
        "northstar-quarterly-brief.docx": _docx_bytes(),
        "northstar-quarterly-brief.txt": plain_text.encode("utf-8"),
        "northstar-quarterly-brief.html": html.encode("utf-8"),
        "northstar-quarterly-brief.csv": csv_text.encode("utf-8"),
    }


def build_archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in _sample_files().items():
            archive.writestr(_zip_info(name), content)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that the committed archive matches deterministic output.",
    )
    args = parser.parse_args()
    expected = build_archive()

    if args.check:
        if not ARCHIVE_PATH.is_file() or ARCHIVE_PATH.read_bytes() != expected:
            print(f"{ARCHIVE_PATH} is missing or out of date", file=sys.stderr)
            return 1
        print(f"{ARCHIVE_PATH} is deterministic and up to date")
        return 0

    ARCHIVE_PATH.write_bytes(expected)
    print(f"Wrote {ARCHIVE_PATH} with five original sample documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
