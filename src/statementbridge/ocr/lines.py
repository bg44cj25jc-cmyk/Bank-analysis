"""Assemble OCR words into the physical rows of a ledger.

Tesseract's own line grouping cannot be trusted on these scans. It breaks a
single ledger row into two or three fragments wherever the dot-matrix printing
leaves a wide gap, and a fragment like ``4,72Dr 11831KC`` then looks exactly
like a transaction carrying an amount and a balance. Those phantom rows were
the largest single source of chain damage on the Gramin fixture -- far worse
than ordinary character errors, because a wrong digit is repairable from the
balance delta while an invented row is not.

Clustering words by their vertical centre instead reconstructs the row the
printer actually produced. The tolerance is derived from the page's own median
word height, so it adapts to resolution and to the two very different type
sizes in the fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .engine import OcrLine


@dataclass(slots=True)
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def centre(self) -> float:
        return self.top + self.height / 2

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def group_into_rows(
    words: Iterable[Word], *, tolerance_ratio: float = 0.6
) -> list[OcrLine]:
    """Cluster words into ledger rows by vertical position."""
    ordered = sorted(words, key=lambda word: (word.centre, word.left))
    if not ordered:
        return []

    pitch = median([word.height for word in ordered]) or 1.0
    tolerance = pitch * tolerance_ratio

    rows: list[list[Word]] = []
    current: list[Word] = [ordered[0]]
    anchor = ordered[0].centre

    for word in ordered[1:]:
        if abs(word.centre - anchor) <= tolerance:
            current.append(word)
            # Track the row's running centre so a slight baseline drift across
            # a wide row does not split it at the right-hand edge.
            anchor = sum(item.centre for item in current) / len(current)
        else:
            rows.append(current)
            current = [word]
            anchor = word.centre
    rows.append(current)

    return [_to_line(row) for row in rows]


def _to_line(words: list[Word]) -> OcrLine:
    words = sorted(words, key=lambda word: word.left)
    confidences = tuple(word.confidence for word in words)
    return OcrLine(
        text=" ".join(word.text for word in words),
        top=min(word.top for word in words),
        bottom=max(word.bottom for word in words),
        left=min(word.left for word in words),
        right=max(word.right for word in words),
        confidence=sum(confidences) / len(confidences),
        word_confidences=confidences,
    )
