"""Build a tiny text-layer PDF, so the digital parser can be tested for real.

Both supplied fixtures are pure images, which leaves the pdfplumber family with
no real statement to run against. Rather than leave it untested until a digital
statement arrives, the tests synthesise one. This writes a genuine PDF with a
real text layer -- pdfplumber extracts characters and coordinates from it
exactly as it would from a bank's own export -- in about fifty lines, which is
cheaper than taking a dependency on a PDF toolkit for test fixtures alone.
"""

from __future__ import annotations

import zlib
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


# --- scanned pages, for the capture quality gate -------------------------
#
# The gate judges what a scanner produced: dots per inch, bit depth, colour
# space. None of that can be exercised with a text-layer PDF, and the only two
# real scans available are both the *failing* case -- so the passing case has to
# be synthesised. These build a genuine image-only page whose effective
# resolution is whatever the test asks for, using zlib from the standard library
# rather than taking an imaging dependency for fixtures alone.


def _ink_rows(width: int, height: int) -> list[int]:
    """Row indices carrying 'text', so the page is not a blank sheet.

    The gate measures ink-to-paper separation and dominant ink angle, and both
    need something on the page to measure.
    """
    band = max(height // 24, 1)
    return [row for row in range(height) if (row // band) % 3 == 1]


def _grey_bitmap(width: int, height: int, ink: int = 30, paper: int = 240) -> bytes:
    dark = set(_ink_rows(width, height))
    row_ink = bytes([ink]) * width
    row_paper = bytes([paper]) * width
    return b"".join(row_ink if row in dark else row_paper for row in range(height))


def _bilevel_bitmap(width: int, height: int) -> bytes:
    """1 bit per pixel, rows padded to a byte boundary as the PDF spec requires."""
    dark = set(_ink_rows(width, height))
    stride = (width + 7) // 8
    row_ink = b"\x00" * stride      # 0 = black in DeviceGray
    row_paper = b"\xff" * stride
    return b"".join(row_ink if row in dark else row_paper for row in range(height))


def write_image_pdf(
    path: Path,
    *,
    dpi: int = 300,
    bits: int = 8,
    width_px: int = 320,
    height_px: int = 440,
    pages: int = 1,
) -> Path:
    """Write an image-only PDF whose pages measure ``dpi`` when inspected.

    The page box is derived from the pixel count and the requested resolution,
    which is exactly the relationship the gate inverts to recover DPI.
    """
    width_pt = width_px / dpi * 72.0
    height_pt = height_px / dpi * 72.0

    if bits == 1:
        raw = _bilevel_bitmap(width_px, height_px)
    elif bits == 8:
        raw = _grey_bitmap(width_px, height_px)
    else:
        raise ValueError(f"unsupported bit depth {bits}")
    data = zlib.compress(raw)

    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    image_id = add(
        b"<< /Type /XObject /Subtype /Image /Width " + str(width_px).encode()
        + b" /Height " + str(height_px).encode()
        + b" /ColorSpace /DeviceGray /BitsPerComponent " + str(bits).encode()
        + b" /Filter /FlateDecode /Length " + str(len(data)).encode()
        + b" >>\nstream\n" + data + b"\nendstream"
    )

    stream = (f"q {width_pt:.4f} 0 0 {height_pt:.4f} 0 0 cm /Im0 Do Q").encode("ascii")
    content_ids = [
        add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream")
        for _ in range(pages)
    ]

    pages_id = len(objects) + pages + 1
    box = f"[0 0 {width_pt:.4f} {height_pt:.4f}]".encode("ascii")
    page_ids = [
        add(
            b"<< /Type /Page /Parent " + str(pages_id).encode()
            + b" 0 R /MediaBox " + box
            + b" /Resources << /XObject << /Im0 " + str(image_id).encode()
            + b" 0 R >> >> /Contents " + str(content_id).encode() + b" 0 R >>"
        )
        for content_id in content_ids
    ]

    kids = b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
    actual_pages_id = add(
        b"<< /Type /Pages /Kids [" + kids + b"] /Count "
        + str(len(page_ids)).encode() + b" >>"
    )
    catalog_id = add(
        b"<< /Type /Catalog /Pages " + str(actual_pages_id).encode() + b" 0 R >>"
    )

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
