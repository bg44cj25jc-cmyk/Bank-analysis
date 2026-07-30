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
from typing import Sequence

from ..ocr.engine import OcrLine
from ..ocr.lines import Word, group_into_rows
from .frame import Anchor, ParseResult, Txn
from .lineparse import build_txn
from .profiles.base import BankProfile
from .rowkind import RowKind, classify_line
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
            rows, anchors, diagnostics = _read_page(
                lines, profile, page_no=index, start_row=source_row
            )
            result.rows.extend(rows)
            result.anchors.extend(anchors)
            result.diagnostics.append(diagnostics)
            source_row += len(lines)
    return result


def _read_page(
    lines: Sequence[OcrLine],
    profile: BankProfile,
    *,
    page_no: int,
    start_row: int,
) -> tuple[list[Txn], list[Anchor], dict]:
    rows: list[Txn] = []
    anchors: list[Anchor] = []
    printed_pages: set[int] = set()
    limits_reached = False
    dropped = 0

    for offset, line in enumerate(lines):
        source_row = start_row + offset
        match = PRINTED_PAGE.search(line.text)
        if match:
            printed_pages.add(int(match.group(1)))

        classification = classify_line(
            line.text,
            page_no=page_no,
            source_row=source_row,
            extra_patterns=profile.patterns(),
        )
        if classification.anchor is not None:
            anchors.append(classification.anchor)

        if classification.kind is RowKind.LIMITS_TABLE:
            if offset > len(lines) * 0.6:
                limits_reached = True
            continue
        if limits_reached or not classification.kind.is_transaction:
            continue

        row = build_txn(
            line.text,
            page_no=page_no,
            source_row=source_row,
            is_overdraft=profile.is_overdraft,
        )
        if row is None:
            dropped += 1
            continue
        row.ocr_confidence = 100.0
        rows.append(row)

    return rows, anchors, {
        "page_no": page_no,
        "printed_pages": sorted(printed_pages),
        "lines": len(lines),
        "rows": len(rows),
        "unparsed_lines": dropped,
        "mean_confidence": 100.0,
    }
