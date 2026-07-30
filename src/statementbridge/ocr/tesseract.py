"""Tesseract implementation of the OCR contract."""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
import pytesseract

from .engine import NUMERIC_WHITELIST, OcrLine
from .lines import Word, group_into_rows

#: Page segmentation 6 -- "a single uniform block of text". A bank ledger is a
#: dense table with no headings to speak of, and the layout-analysis modes
#: fragment it into spurious columns.
DEFAULT_PSM = 6


class TesseractEngine:
    name = "tesseract"

    def __init__(self, *, psm: int = DEFAULT_PSM, lang: str = "eng") -> None:
        self.psm = psm
        self.lang = lang

    def _config(self, whitelist: str | None) -> str:
        parts = [f"--psm {self.psm}"]
        if whitelist:
            parts.append(f"-c tessedit_char_whitelist={whitelist}")
        return " ".join(parts)

    def read_lines(self, image: np.ndarray) -> Sequence[OcrLine]:
        data = pytesseract.image_to_data(
            image,
            lang=self.lang,
            config=self._config(None),
            output_type=pytesseract.Output.DATAFRAME,
        )
        if not isinstance(data, pd.DataFrame) or data.empty:
            return []

        data = data[data.conf != -1].copy()
        data["text"] = data["text"].astype(str)
        data = data[data["text"].str.strip() != ""]
        if data.empty:
            return []

        # Deliberately ignore Tesseract's own line_num grouping and rebuild the
        # rows from word geometry -- see ocr/lines.py for why.
        words = [
            Word(
                text=str(record.text),
                left=int(record.left),
                top=int(record.top),
                width=int(record.width),
                height=int(record.height),
                confidence=float(record.conf),
            )
            for record in data.itertuples()
        ]
        return group_into_rows(words)

    def read_region(self, image: np.ndarray, *, whitelist: str | None = None) -> str:
        return pytesseract.image_to_string(
            image, lang=self.lang, config=self._config(whitelist)
        ).strip()

    def read_number(self, image: np.ndarray) -> str:
        """Re-read a cell that should contain only a figure."""
        return self.read_region(image, whitelist=NUMERIC_WHITELIST)
