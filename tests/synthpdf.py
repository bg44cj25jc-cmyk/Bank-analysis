"""Build a tiny text-layer PDF, so the digital parser can be tested for real.

Both supplied fixtures are pure images, which leaves the pdfplumber family with
no real statement to run against. Rather than leave it untested until a digital
statement arrives, the tests synthesise one. This writes a genuine PDF with a
real text layer -- pdfplumber extracts characters and coordinates from it
exactly as it would from a bank's own export -- in about fifty lines, which is
cheaper than taking a dependency on a PDF toolkit for test fixtures alone.
"""

from __future__ import annotations

from pathlib import Path

FONT_SIZE = 9
LEADING = 14
LEFT_MARGIN = 40
TOP_START = 800


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    parts = ["BT", f"/F1 {FONT_SIZE} Tf", f"1 0 0 1 {LEFT_MARGIN} {TOP_START} Tm",
             f"{LEADING} TL"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", "replace")


def write_pdf(path: Path, pages: list[list[str]]) -> Path:
    """Write one page per list of lines. Uses Courier so columns line up."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_ids: list[int] = []
    content_ids: list[int] = []
    for lines in pages:
        stream = _content_stream(lines)
        content_ids.append(
            add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                + stream + b"\nendstream")
        )
    pages_id = len(objects) + len(pages) + 1

    for content_id in content_ids:
        page_ids.append(
            add(
                b"<< /Type /Page /Parent " + str(pages_id).encode()
                + b" 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 "
                + str(font_id).encode() + b" 0 R >> >> /Contents "
                + str(content_id).encode() + b" 0 R >>"
            )
        )

    kids = b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
    actual_pages_id = add(
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode() + b" >>"
    )
    catalog_id = add(b"<< /Type /Catalog /Pages " + str(actual_pages_id).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root "
            + str(catalog_id).encode() + b" 0 R >>\nstartxref\n"
            + str(xref_at).encode() + b"\n%%EOF\n")

    path.write_bytes(bytes(out))
    return path
