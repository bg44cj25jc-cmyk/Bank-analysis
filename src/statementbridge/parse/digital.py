"""The digital-text parser family.

A text-layer PDF hands over exact characters and exact word geometry, so this
family skips rasterising, conditioning and recognition entirely. What it does
*not* skip is anything after row assembly: the same row grouping, the same trap
classifier, the same field extraction and the same balance chain run over both
families. That is what makes the frame contract real rather than nominal -- a
change to the repair engine benefits both paths, and a bank profile written for
a scanned statement keeps working when the client starts downloading the
digital version.

Untested against a real bank statement: both supplied fixtures are pure images.
It is exercised by synthetic PDFs in the test suite, and should be re-verified
against a genuine text-layer statement before being relied on.
"""

from __future__ import annotations

from pathlib import Path

from ..ocr.engine import OcrLine
from ..ocr.lines import Word, group_into_rows
from .frame import ParseResult
from .pages import read_page
from .profiles.base import BankProfile
from .scanned import PRINTED_PAGE

#: pdfplumber reports coordinates in points; scale to the integer pixel space
#: the shared row assembly expects, so one tolerance works for both families.
SCALE = 4


def words_from_page(page) -> list[Word]:
    """Convert pdfplumber words into the shared geometry type."""
    words: list[Word] = []
    for item in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        left = int(item["x0"] * SCALE)
        top = int(item["top"] * SCALE)
        words.append(
            Word(
                text=item["text"],
                left=left,
                top=top,
                width=max(int((item["x1"] - item["x0"]) * SCALE), 1),
                height=max(int((item["bottom"] - item["top"]) * SCALE), 1),
                # A text layer is exact: there is no recognition to doubt.
                confidence=100.0,
            )
        )
    return words


def read_lines(page) -> list[OcrLine]:
    return group_into_rows(words_from_page(page))


def parse_pdf(pdf: Path, profile: BankProfile) -> ParseResult:
    import pdfplumber

    result = ParseResult()
    source_row = 0
    with pdfplumber.open(str(pdf)) as document:
        result.page_count = len(document.pages)
        for index, page in enumerate(document.pages, start=1):
            lines = read_lines(page)
            rows, anchors, diagnostics = read_page(
                lines,
                profile,
                page_no=index,
                start_row=source_row,
                printed_page_pattern=PRINTED_PAGE,
            )
            result.rows.extend(rows)
            result.anchors.extend(anchors)
            result.diagnostics.append(diagnostics)
            source_row += len(lines)
    return result
