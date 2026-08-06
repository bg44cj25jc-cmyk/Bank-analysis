"""The OCR parser family: scanned PDF in, transaction frame out."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

import cv2

from ..ingest import preprocess, render
from ..ocr import columns, table
from ..ocr.engine import OcrEngine, OcrLine
from ..ocr.tesseract import TesseractEngine
from .frame import ParseResult
from .pages import read_page
from .profiles.base import BankProfile

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
        lines = read_scanned_page(image, profile, engine)
        rows, anchors, diagnostics = read_page(
            lines,
            profile,
            page_no=page.page_no,
            start_row=source_row,
            printed_page_pattern=PRINTED_PAGE,
        )
        result.rows.extend(rows)
        result.anchors.extend(anchors)
        result.diagnostics.append(diagnostics)
        source_row += len(lines)

    return result


def read_scanned_page(
    raster, profile: BankProfile, engine: OcrEngine
) -> list[OcrLine]:
    """Condition, recognise and sharpen one already-rasterised page.

    Shared with the per-page router, which rasterises in runs of its own and so
    cannot go through :func:`parse_pdf`.
    """
    prepared, lines = _read_image(raster, profile, engine)
    # Second pass over the money columns alone, digits only. Never removes a
    # reading, only sharpens one.
    band = columns.locate_band(lines, prepared.shape[1])
    if band is not None:
        lines = columns.overlay(lines, columns.read_numeric_band(prepared, band))
    return list(lines)


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
