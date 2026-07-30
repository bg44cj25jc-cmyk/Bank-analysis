"""The OCR parser family: scanned PDF in, transaction frame out."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Sequence

import cv2

from ..ingest import preprocess, render
from ..ocr import columns, table
from ..ocr.engine import OcrEngine, OcrLine
from ..ocr.tesseract import TesseractEngine
from .frame import Anchor, ParseResult, Txn
from .lineparse import build_txn
from .profiles.base import BankProfile
from .rowkind import RowKind, classify_line

#: A logical statement page number printed in the running header. The scans put
#: more than one logical page on some sheets, so this is tracked separately
#: from the PDF page index.
PRINTED_PAGE = re.compile(r"\bPage\s*(?:no\.?)?\s*(\d{1,3})\b", re.IGNORECASE)


def parse_pdf(
    pdf: Path,
    profile: BankProfile,
    *,
    engine: OcrEngine | None = None,
    dpi: int = render.DEFAULT_DPI,
    first: int | None = None,
    last: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ParseResult:
    """Read a scanned statement into rows and verification anchors."""
    engine = engine or TesseractEngine()
    images = render.render(pdf, dpi=dpi, first=first, last=last)
    result = ParseResult(page_count=len(images))

    source_row = 0

    for position, page in enumerate(images, start=1):
        if progress:
            progress(position, len(images))
        image = cv2.imread(str(page.path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        prepared, lines = _read_image(image, profile, engine)
        # Second pass over the money columns alone, digits only. Never removes
        # a reading, only sharpens one.
        band = columns.locate_band(lines, prepared.shape[1])
        if band is not None:
            lines = columns.overlay(lines, columns.read_numeric_band(prepared, band))
        rows, anchors, diagnostics = _read_page(
            lines, profile, page_no=page.page_no, start_row=source_row
        )
        result.rows.extend(rows)
        result.anchors.extend(anchors)
        result.diagnostics.append(diagnostics)
        source_row += len(lines)

    return result


def _read_image(image, profile: BankProfile, engine: OcrEngine):
    """Condition one page and assemble its rows, per the profile's scan class."""
    if not profile.ruled_table:
        prepared = preprocess.prepare(image, dot_matrix=True)
        return prepared, list(engine.read_lines(prepared))

    # The grid has to be found before the rules are stripped, since the rules
    # are what defines it. Words are then read from the de-ruled image, because
    # Tesseract renders a printed rule as a run of pipe characters.
    binary = preprocess.sauvola(preprocess.deskew(preprocess.to_grey(image)))
    grid = table.detect_grid(binary)
    deruled = preprocess.remove_rules(binary)
    words = engine.read_words(deruled)
    if grid.usable and words:
        return deruled, table.rows_to_lines(words, grid)
    return deruled, list(engine.read_lines(deruled))


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
    confidences: list[float] = []
    dropped = 0

    for offset, line in enumerate(lines):
        source_row = start_row + offset
        text = line.text
        confidences.append(line.confidence)

        page_match = PRINTED_PAGE.search(text)
        if page_match:
            printed_pages.add(int(page_match.group(1)))

        classification = classify_line(
            text,
            page_no=page_no,
            source_row=source_row,
            extra_patterns=profile.patterns(),
        )

        if classification.anchor is not None:
            anchors.append(classification.anchor)

        # The Gramin ledger closes with a Limits / Draw Power / Int Rate block.
        # Once it starts, nothing further on the page is transactional -- but
        # only trust that when it appears in the lower part of the page, so a
        # narration mentioning an interest rate cannot truncate a whole sheet.
        if classification.kind is RowKind.LIMITS_TABLE:
            if offset > len(lines) * 0.6:
                limits_reached = True
            continue

        if limits_reached or not classification.kind.is_transaction:
            continue

        row = build_txn(
            text,
            page_no=page_no,
            source_row=source_row,
            is_overdraft=profile.is_overdraft,
        )
        if row is None:
            dropped += 1
            continue
        row.ocr_confidence = line.confidence
        row.bbox = (line.left, line.top, line.right, line.bottom)
        rows.append(row)

    diagnostics = {
        "page_no": page_no,
        "printed_pages": sorted(printed_pages),
        "lines": len(lines),
        "rows": len(rows),
        "unparsed_lines": dropped,
        "mean_confidence": (
            round(sum(confidences) / len(confidences), 1) if confidences else 0.0
        ),
    }
    return rows, anchors, diagnostics
