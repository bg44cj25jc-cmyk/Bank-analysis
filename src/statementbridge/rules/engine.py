"""Running a pack over a settled statement.

The engine deliberately does not touch the rows it classifies. It reads a
narration and a signed amount and returns a decision, which the caller writes
wherever it keeps them. That keeps the interesting part -- which rule fired, and
why -- testable against a list of strings, with no PDF, no OCR and no database
anywhere near it, and it is why the whole of the client's 236-row workbook can be
replayed through this in milliseconds.

Two things are worth saying about what the engine refuses to do.

**It classifies unresolved rows.** A row whose amount the balance engine could
not settle still has a narration, and what a transaction *was* does not depend on
whether its figure survived the scan. Withholding the label would only mean a
reviewer fixing the amount had to categorise it by hand as well. The row is still
blocked from export by ``RowState.UNRESOLVED``; that is a separate gate and it
still holds.

**It never guesses.** Nothing matched means :attr:`Category.UNCLASSIFIED`, a
suspense ledger and no rule id -- the same posture ``RowState.UNRESOLVED`` takes
towards money it cannot explain. An unclassified row is cheap: someone reads it
once. A row confidently posted to the wrong ledger is not, because nothing
downstream will ever question it again.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Protocol, Sequence

from ..money import ZERO
from .normalise import narration as split_narration
from .pack import DEFAULT_PACK
from .rule import Context, Pack
from .taxonomy import Category, Direction


class Row(Protocol):
    """What the engine needs of a row: what it says, and which way it moved.

    Narrowed to this so the engine can be run over the client's workbook, a
    parsed statement or a list of test strings without caring which.
    """

    narration: str
    debit: Decimal
    credit: Decimal

    @property
    def signed_amount(self) -> Decimal: ...


@dataclass(frozen=True, slots=True)
class Classification:
    """What the engine decided about one row."""

    category: Category
    ledger: str
    contra: bool
    #: The rule that fired. ``None`` where nothing did.
    rule_id: str | None = None
    needs_review: bool = False

    @property
    def classified(self) -> bool:
        return self.category is not Category.UNCLASSIFIED


def classify_narration(
    text: str,
    signed_amount: Decimal,
    *,
    context: Context,
    holder: str | None = None,
    pack: Pack = DEFAULT_PACK,
) -> Classification:
    """Classify one narration. The unit everything else is built from."""
    parsed = split_narration(text)
    direction = Direction.of(signed_amount)
    rule = pack.first_match(parsed, direction, context)

    if rule is None:
        return Classification(
            category=Category.UNCLASSIFIED,
            ledger=Category.UNCLASSIFIED.ledger(holder),
            contra=Category.UNCLASSIFIED.contra,
            rule_id=None,
            # Not a defect, but not an answer either. Someone has to read it.
            needs_review=True,
        )

    return Classification(
        category=rule.category,
        ledger=rule.ledger_for(holder),
        contra=rule.category.contra,
        rule_id=rule.id,
        needs_review=rule.review,
    )


def classify(
    rows: Sequence[Row],
    *,
    holder: str | None = None,
    pack: Pack = DEFAULT_PACK,
) -> list[Classification]:
    """Classify a settled statement, one decision per row, in row order."""
    context = Context.for_holder(holder)
    return [
        classify_narration(
            row.narration, row.signed_amount, context=context, holder=holder, pack=pack
        )
        for row in rows
    ]


def unclassified(classifications: Iterable[Classification]) -> int:
    return sum(1 for item in classifications if not item.classified)


def needing_review(classifications: Iterable[Classification]) -> int:
    return sum(1 for item in classifications if item.needs_review)


@dataclass(frozen=True, slots=True)
class Movement:
    """A row's amounts, paired with what the engine decided about it.

    The pairing is the whole point: a category summary that reads its figures
    from anywhere other than the settled rows could disagree with the balance
    chain, and there would be no way to tell which was right.
    """

    classification: Classification
    debit: Decimal = ZERO
    credit: Decimal = ZERO

    @classmethod
    def of(cls, row: Row, classification: Classification) -> "Movement":
        return cls(classification=classification, debit=row.debit, credit=row.credit)


def movements(
    rows: Sequence[Row], classifications: Sequence[Classification]
) -> list[Movement]:
    if len(rows) != len(classifications):
        raise ValueError(
            f"{len(rows)} rows against {len(classifications)} classifications"
        )
    return [Movement.of(row, item) for row, item in zip(rows, classifications)]
