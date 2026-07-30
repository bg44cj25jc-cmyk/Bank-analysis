"""Cell extraction for ruled statements.

The SBI fixture defeats line-based reading. A single ledger row occupies three
printed lines -- the two dates on one, the amounts on another, the UPI or
cheque reference on a third -- so any reader that treats an OCR line as a
transaction produces a stream of fragments, each carrying part of a row.

The page is a ruled table, though, and the rules say exactly where every row
and column begins. Detecting them turns a guessing problem into a lookup: words
are assigned to the cell whose bounds contain them, and a row is whatever falls
between two horizontal rules regardless of how many printed lines that spans.

Columns are then identified by what they contain rather than by their heading,
because the heading is as likely to be misread as anything else. A column whose
cells parse predominantly as dates is a date column; the rightmost money column
is the running balance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..money import MONEY_TOKEN
from ..parse.lineparse import DATE_TOKEN
from .engine import OcrLine
from .lines import Word, median

#: A rule must span this fraction of the page width to count as a row divider
#: rather than an underline or a long dash inside a narration. Measured on the
#: SBI fixture: a quarter-width kernel finds 16 dividers per page at this
#: threshold, which matches the printed row count.
HORIZONTAL_SPAN = 0.25

#: The SBI table is ruled horizontally but *not* vertically -- the longest
#: continuous vertical stroke on a page covers 10% of its height, and the pipe
#: characters Tesseract reports are short per-cell separators, not columns. So
#: column boundaries are never taken from rules; they are inferred from where
#: the figures and dates actually fall. This constant only guards the optional
#: vertical pass for banks that do rule their columns.
VERTICAL_SPAN = 0.20

#: Kernel width as a fraction of the page, for isolating horizontal rules.
HORIZONTAL_KERNEL = 0.05


@dataclass(slots=True)
class Grid:
    rows: list[tuple[int, int]] = field(default_factory=list)
    cols: list[tuple[int, int]] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        # Row bands alone are enough: they are what reunites a transaction that
        # the printer spread over three lines. Columns are a refinement.
        return len(self.rows) >= 3


def _peaks(projection: np.ndarray, threshold: float, *, gap: int = 4) -> list[int]:
    """Collapse runs of adjacent above-threshold positions to one coordinate."""
    hits = np.flatnonzero(projection >= threshold)
    if hits.size == 0:
        return []
    groups: list[list[int]] = [[int(hits[0])]]
    for value in hits[1:]:
        if value - groups[-1][-1] <= gap:
            groups[-1].append(int(value))
        else:
            groups.append([int(value)])
    return [int(sum(group) / len(group)) for group in groups]


def detect_grid(binary: np.ndarray) -> Grid:
    """Locate the table's horizontal and vertical rules.

    ``binary`` must still carry its rules -- run this before rule removal.
    """
    height, width = binary.shape[:2]
    ink = cv2.bitwise_not(binary)

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(20, int(width * HORIZONTAL_KERNEL)), 1)
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(20, int(height * 0.08)))
    )
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, vertical_kernel)

    row_lines = _peaks(horizontal.sum(axis=1) / 255.0, width * HORIZONTAL_SPAN)
    col_lines = _peaks(vertical.sum(axis=0) / 255.0, height * VERTICAL_SPAN)

    grid = Grid()
    grid.rows = [
        (top, bottom)
        for top, bottom in zip(row_lines, row_lines[1:])
        if bottom - top > 8  # discard the doubled strokes of a thick rule
    ]
    grid.cols = [
        (left, right)
        for left, right in zip(col_lines, col_lines[1:])
        if right - left > 15
    ]
    return grid


def assign_cells(words: list[Word], grid: Grid) -> list[list[str]]:
    """Place every word in its cell, returning a text matrix."""
    matrix: list[list[list[Word]]] = [
        [[] for _ in grid.cols] for _ in grid.rows
    ]
    for word in words:
        row_index = _band_of(word.centre, grid.rows)
        if row_index is None:
            continue
        column_index = _band_of(word.left + word.width / 2, grid.cols)
        if column_index is None:
            continue
        matrix[row_index][column_index].append(word)

    return [
        [
            " ".join(
                item.text
                for item in sorted(cell, key=lambda word: (word.top, word.left))
            )
            for cell in row
        ]
        for row in matrix
    ]


def rows_to_lines(words: list[Word], grid: Grid) -> list[OcrLine]:
    """Emit one line per row band, however many printed lines it spans.

    This is what makes the SBI layout readable: the two dates, the amounts and
    the reference sit on three separate printed lines but inside one ruled row,
    and the downstream parser only needs them to arrive together.

    Within a band, words are ordered by printed line and then left to right, so
    the amount still precedes the balance and the last two money figures on the
    assembled line remain the amount and the running balance.
    """
    buckets: list[list[Word]] = [[] for _ in grid.rows]
    for word in words:
        index = _band_of(word.centre, grid.rows)
        if index is not None:
            buckets[index].append(word)

    lines: list[OcrLine] = []
    for bucket, (top, bottom) in zip(buckets, grid.rows):
        if not bucket:
            continue
        pitch = max(median([item.height for item in bucket]), 1.0)
        ordered = sorted(bucket, key=lambda item: (round(item.centre / pitch), item.left))
        confidences = tuple(item.confidence for item in ordered)
        lines.append(
            OcrLine(
                text=" ".join(item.text for item in ordered),
                top=top,
                bottom=bottom,
                left=min(item.left for item in ordered),
                right=max(item.right for item in ordered),
                confidence=sum(confidences) / len(confidences),
                word_confidences=confidences,
            )
        )
    return lines


def _band_of(position: float, bands: list[tuple[int, int]]) -> int | None:
    for index, (start, end) in enumerate(bands):
        if start <= position < end:
            return index
    return None


@dataclass(slots=True)
class ColumnRoles:
    date: int | None = None
    value_date: int | None = None
    description: int | None = None
    reference: int | None = None
    money: list[int] = field(default_factory=list)

    @property
    def balance(self) -> int | None:
        return self.money[-1] if self.money else None

    @property
    def amounts(self) -> list[int]:
        return self.money[:-1]

    @property
    def usable(self) -> bool:
        return self.date is not None and len(self.money) >= 2


def classify_columns(matrix: list[list[str]]) -> ColumnRoles:
    """Work out what each column holds, from its contents.

    Deliberately ignores the header text: on these scans "Debit" comes back as
    "Bebit" and "Date" as "Oate" often enough that keying on it would be less
    reliable than keying on the data underneath.
    """
    if not matrix:
        return ColumnRoles()
    width = len(matrix[0])
    date_hits = [0] * width
    money_hits = [0] * width
    alpha = [0] * width
    digits = [0] * width

    for row in matrix:
        for index, cell in enumerate(row):
            if not cell.strip():
                continue
            if DATE_TOKEN.search(cell):
                date_hits[index] += 1
            if MONEY_TOKEN.search(cell):
                money_hits[index] += 1
            alpha[index] += sum(character.isalpha() for character in cell)
            digits[index] += sum(character.isdigit() for character in cell)

    roles = ColumnRoles()
    date_columns = [index for index in range(width) if date_hits[index] >= 3]
    if date_columns:
        roles.date = date_columns[0]
        if len(date_columns) > 1:
            roles.value_date = date_columns[1]

    roles.money = [
        index
        for index in range(width)
        if money_hits[index] >= 3 and index not in date_columns
    ]

    remaining = [
        index for index in range(width)
        if index not in date_columns and index not in roles.money
    ]
    if remaining:
        roles.description = max(remaining, key=lambda index: alpha[index])
        rest = [index for index in remaining if index != roles.description]
        if rest:
            roles.reference = max(rest, key=lambda index: digits[index])
    return roles
