"""Decide whether each page carries real text or is a picture of text.

Classified per page rather than per document. A branch that staples a rescanned
sheet into an otherwise digital export is common, and routing the whole file by
its first page would send that sheet to a parser guaranteed to find nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from statistics import median


class PageClass(str, Enum):
    DIGITAL = "DIGITAL"
    SCANNED = "SCANNED"


#: Below this many characters a page is a scan. A digital statement page runs to
#: thousands; a scanned one yields at most a stray watermark or a stamped
#: annotation, so the gap between the two is wide and the threshold uncritical.
TEXT_FLOOR = 50


@dataclass(slots=True)
class DocumentClass:
    pages: list[PageClass]
    char_counts: list[int]

    @property
    def dominant(self) -> PageClass:
        scanned = sum(1 for page in self.pages if page is PageClass.SCANNED)
        return PageClass.SCANNED if scanned * 2 >= len(self.pages) else PageClass.DIGITAL

    @property
    def mixed(self) -> bool:
        return len(set(self.pages)) > 1

    @property
    def median_chars(self) -> float:
        return median(self.char_counts) if self.char_counts else 0.0


def classify(pdf: Path) -> DocumentClass:
    import pdfplumber

    pages: list[PageClass] = []
    counts: list[int] = []
    with pdfplumber.open(str(pdf)) as document:
        for page in document.pages:
            text = page.extract_text() or ""
            count = len(text.strip())
            counts.append(count)
            pages.append(
                PageClass.DIGITAL if count >= TEXT_FLOOR else PageClass.SCANNED
            )
    return DocumentClass(pages=pages, char_counts=counts)
