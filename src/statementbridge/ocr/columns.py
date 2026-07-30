"""Re-read the money columns with a digits-only alphabet.

The full-page pass has to recognise narration, so Tesseract runs with the whole
Latin alphabet available and the figures compete against it: ``5`` against
``S``, ``0`` against ``O``, ``8`` against ``B``, ``1`` against ``l``. Measured
on the Gramin fixture, only 44% of rows had a printed amount agreeing with the
balance delta after that single pass -- and row assembly was not the cause, as
every clustering strategy scored identically.

Restricting the alphabet removes the competition rather than trying to repair
it afterwards: with ``tessedit_char_whitelist`` set to digits and separators
the confusions become unrepresentable, because the letters are not in the set
the engine may emit. That only works where a region is known to be numeric, so
the money columns are located first, from where the figures fell on the
full-page pass, and re-read on their own.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytesseract

from ..money import MONEY_TOKEN
from .engine import NUMERIC_WHITELIST, OcrLine
from .lines import Word, group_into_rows


@dataclass(slots=True)
class NumericBand:
    left: int
    right: int

    @property
    def width(self) -> int:
        return self.right - self.left


def locate_band(lines: list[OcrLine], page_width: int, *, pad: int = 24) -> NumericBand | None:
    """Find the horizontal span occupied by money figures.

    Uses the figures the full-page pass already found: whatever their character
    errors, their *position* is reliable, and that is all this needs.
    """
    lefts: list[int] = []
    rights: list[int] = []
    for line in lines:
        if not MONEY_TOKEN.search(line.text):
            continue
        # Approximate the token's x-range by the line's right-hand portion:
        # money always sits to the right of the narration in these layouts.
        span = line.right - line.left
        lefts.append(line.left + int(span * 0.45))
        rights.append(line.right)
    if len(lefts) < 5:
        return None
    left = max(0, int(np.percentile(lefts, 20)) - pad)
    right = min(page_width, int(np.percentile(rights, 90)) + pad)
    if right - left < 50:
        return None
    return NumericBand(left=left, right=right)


def read_numeric_band(
    image: np.ndarray, band: NumericBand, *, psm: int = 6
) -> list[OcrLine]:
    """Recognise the money columns alone, digits only."""
    crop = image[:, band.left : band.right]
    config = f"--psm {psm} -c tessedit_char_whitelist={NUMERIC_WHITELIST}"
    data = pytesseract.image_to_data(
        crop, config=config, output_type=pytesseract.Output.DATAFRAME
    )
    if not isinstance(data, pd.DataFrame) or data.empty:
        return []
    data = data[data.conf != -1].copy()
    data["text"] = data["text"].astype(str)
    data = data[data["text"].str.strip() != ""]
    if data.empty:
        return []
    words = [
        Word(
            text=str(record.text),
            left=int(record.left) + band.left,
            top=int(record.top),
            width=int(record.width),
            height=int(record.height),
            confidence=float(record.conf),
        )
        for record in data.itertuples()
    ]
    return group_into_rows(words)


def overlay(rows: list[OcrLine], numeric: list[OcrLine]) -> list[OcrLine]:
    """Replace each row's money text with the digits-only reading of that row.

    Rows are matched by vertical overlap. A row with no numeric counterpart, or
    whose counterpart yields no usable figure, is left exactly as it was: this
    pass may improve a reading but must never remove one.
    """
    if not numeric:
        return rows
    merged: list[OcrLine] = []
    for row in rows:
        candidate = _best_overlap(row, numeric)
        if candidate is None:
            merged.append(row)
            continue
        digits = MONEY_TOKEN.findall(candidate.text)
        original = MONEY_TOKEN.findall(row.text)
        if len(digits) != len(original) or not digits:
            merged.append(row)
            continue
        text = row.text
        for old, new in zip(original, digits):
            text = text.replace(old, new, 1)
        merged.append(
            OcrLine(
                text=text,
                top=row.top,
                bottom=row.bottom,
                left=row.left,
                right=row.right,
                confidence=max(row.confidence, candidate.confidence),
                word_confidences=row.word_confidences,
            )
        )
    return merged


def _best_overlap(row: OcrLine, candidates: list[OcrLine]) -> OcrLine | None:
    best: tuple[int, OcrLine] | None = None
    for candidate in candidates:
        overlap = min(row.bottom, candidate.bottom) - max(row.top, candidate.top)
        if overlap <= 0:
            continue
        if best is None or overlap > best[0]:
            best = (overlap, candidate)
    if best is None:
        return None
    # Require the match to cover most of the row, so a tall row does not steal
    # the figures belonging to its neighbour.
    if best[0] < row.height * 0.5:
        return None
    return best[1]
