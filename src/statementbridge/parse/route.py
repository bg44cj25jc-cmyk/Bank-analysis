"""Route each page to the parser family that can actually read it.

``ingest.classify`` has always decided, per page, whether a sheet carries real
text or a picture of text -- and until now nothing on the parse path asked it.
Both CLI commands called the OCR family unconditionally, which is harmless while
every statement in hand is a scan and quietly destructive the moment one is not:
a downloaded statement carries exact characters and exact geometry, and
rasterising it to guess at them again throws all of that away.

That is not hypothetical. The statement behind the client's target workbook is a
text-layer PDF.

So the classification is consulted here, per page, and each page is handed to
the family that suits it. Pages are grouped into runs of the same class before
rendering, because Poppler takes a page range and starting it once per page
would cost more than the recognition does on a short document.

The two families keep their own entry points. This does not replace them: it is
the door the job pipeline comes through, and what the CLI now uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterator

from ..ingest import render
from ..ingest.classify import PageClass, classify_pages
from ..ocr.engine import OcrEngine
from ..ocr.tesseract import TesseractEngine
from . import digital, scanned
from .frame import ParseResult
from .pages import read_page
from .profiles.base import BankProfile

Progress = Callable[[int, int], None]


def _runs(classes: list[PageClass], first: int, last: int) -> Iterator[tuple[PageClass, int, int]]:
    """Group the requested page range into consecutive same-class runs.

    Yields ``(class, first_page, last_page)`` with 1-based inclusive bounds, so
    a run of scanned pages becomes exactly one Poppler invocation.
    """
    start = first
    for page_no in range(first, last + 1):
        current = classes[page_no - 1]
        if page_no == last or classes[page_no] is not current:
            yield current, start, page_no
            start = page_no + 1


def parse_statement(
    pdf: Path,
    profile: BankProfile,
    *,
    engine: OcrEngine | None = None,
    dpi: int = render.DEFAULT_DPI,
    first: int | None = None,
    last: int | None = None,
    progress: Progress | None = None,
) -> ParseResult:
    """Read a statement of either kind -- or of both kinds -- into one frame."""
    import pdfplumber

    pdf = Path(pdf)
    result = ParseResult()
    source_row = 0

    with pdfplumber.open(str(pdf)) as document:
        classes = classify_pages(document).pages
        total = len(document.pages)
        begin = max(first or 1, 1)
        end = min(last or total, total)
        if begin > end:
            return result

        result.page_count = end - begin + 1
        done = 0

        for page_class, run_first, run_last in _runs(classes, begin, end):
            if page_class is PageClass.DIGITAL:
                pages = (
                    (page_no, digital.read_lines(document.pages[page_no - 1]))
                    for page_no in range(run_first, run_last + 1)
                )
            else:
                pages = _scanned_lines(
                    pdf, profile, engine, dpi=dpi, first=run_first, last=run_last
                )

            for page_no, lines in pages:
                done += 1
                if progress:
                    progress(done, result.page_count)
                rows, anchors, diagnostics = read_page(
                    lines,
                    profile,
                    page_no=page_no,
                    start_row=source_row,
                    printed_page_pattern=scanned.PRINTED_PAGE,
                )
                diagnostics["page_class"] = page_class.value
                result.rows.extend(rows)
                result.anchors.extend(anchors)
                result.diagnostics.append(diagnostics)
                source_row += len(lines)

    return result


def _scanned_lines(
    pdf: Path,
    profile: BankProfile,
    engine: OcrEngine | None,
    *,
    dpi: int,
    first: int,
    last: int,
):
    """Rasterise one run of scanned pages and recognise each of them."""
    import cv2

    engine = engine or TesseractEngine()
    for image in render.render(pdf, dpi=dpi, first=first, last=last):
        raster = cv2.imread(str(image.path), cv2.IMREAD_GRAYSCALE)
        if raster is None:
            continue
        yield image.page_no, scanned.read_scanned_page(raster, profile, engine)
