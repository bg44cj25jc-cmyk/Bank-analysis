"""OCR engine abstraction.

Tesseract is the default; PaddleOCR is the declared alternative to be measured
against it. Both sit behind this Protocol so the bake-off is a constructor
change rather than a rewrite, and so a future engine can be dropped in without
touching the parsers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

import numpy as np

#: Charset for columns known to hold money or dates. Restricting the alphabet
#: is the single largest accuracy lever on these scans: it makes the 0/O, 1/l,
#: 5/S and 8/B confusions structurally impossible rather than something to
#: repair afterwards, because the letters are not in the alphabet the engine is
#: permitted to emit.
NUMERIC_WHITELIST = "0123456789.,-/"


@dataclass(slots=True)
class OcrLine:
    """One assembled line of text with its geometry and confidence."""

    text: str
    top: int
    bottom: int
    left: int
    right: int
    confidence: float
    word_confidences: tuple[float, ...] = field(default=())

    @property
    def height(self) -> int:
        return self.bottom - self.top


class OcrEngine(Protocol):
    """Minimal contract the parsers depend on."""

    name: str

    def read_lines(self, image: np.ndarray) -> Sequence[OcrLine]:
        """Full-page recognition, returning ordered lines."""
        ...

    def read_region(
        self, image: np.ndarray, *, whitelist: str | None = None
    ) -> str:
        """Recognise a cropped region, optionally with a restricted alphabet.

        Used for targeted re-reads: when the balance chain flags a figure as
        suspect, that one cell is re-recognised with a digits-only alphabet
        instead of re-processing the whole page.
        """
        ...
