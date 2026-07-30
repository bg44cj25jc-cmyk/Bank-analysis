"""The transaction frame contract shared by both parser families.

The digital-text parser and the OCR parser are completely different machines up
to the point of row assembly, and identical afterwards. This module defines the
boundary: whatever comes out of either family is a list of :class:`Txn`, and
every stage downstream -- balance repair, categorisation, reconciliation,
export -- is written against that and nothing else.

Beyond the nine columns in the original specification each row also carries
provenance: the raw text the numbers came from, an OCR confidence, a row state
and a repair note. Those are what make a correction auditable when a partner
has to explain a figure to a client, and what the review screen sorts on.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable

import pandas as pd

from ..money import ZERO, q2


class RowState(str, Enum):
    """How much the pipeline trusts a row's numbers."""

    CLEAN = "CLEAN"            # printed amount and balance delta agree exactly
    REPAIRED = "REPAIRED"      # one field was corrected, uniquely and plausibly
    UNRESOLVED = "UNRESOLVED"  # could not be reconciled -- needs a human

    @property
    def blocks_export(self) -> bool:
        return self is RowState.UNRESOLVED


#: Column order for CSV/Excel emission. The first nine are the agreed contract;
#: the rest are provenance.
FRAME_COLUMNS: tuple[str, ...] = (
    "date",
    "value_date",
    "instrument_no",
    "narration",
    "debit",
    "credit",
    "balance",
    "page_no",
    "source_row",
    "raw_amount_text",
    "raw_balance_text",
    "ocr_confidence",
    "row_state",
    "repair_note",
)

CONTRACT_COLUMNS: tuple[str, ...] = FRAME_COLUMNS[:9]


@dataclass(slots=True)
class Txn:
    """One transaction line.

    ``balance`` is the *signed* running balance under the uniform convention
    (credit positive, debit negative), not the printed magnitude. The Dr/Cr
    marker is reapplied at export by :func:`statementbridge.money.format_drcr`.
    Exactly one of ``debit``/``credit`` is non-zero on a settled row.
    """

    page_no: int
    source_row: int
    narration: str = ""
    date: date | None = None
    value_date: date | None = None
    instrument_no: str = ""
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    balance: Decimal | None = None

    # --- provenance -----------------------------------------------------
    raw_amount_text: str = ""
    raw_balance_text: str = ""
    ocr_confidence: float = 0.0
    row_state: RowState = RowState.CLEAN
    repair_note: str = ""

    #: Amount as printed, before the balance chain had its say. Kept separate
    #: from debit/credit so a repair can always be shown against the original.
    printed_amount: Decimal | None = None
    #: Set when the amount column carried its own Dr/Cr marker.
    printed_marker: str | None = None

    #: Pixel bounds (left, top, right, bottom) of the line this row came from,
    #: in the coordinate space of the rendered page. The review screen zooms
    #: the source image to this box so a reviewer can check a figure against
    #: the scan without hunting for it. None for digital-text pages, where the
    #: question does not arise.
    bbox: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        self.debit = q2(self.debit)
        self.credit = q2(self.credit)
        if self.balance is not None:
            self.balance = q2(self.balance)

    @property
    def signed_amount(self) -> Decimal:
        """Effect on the balance: positive credit, negative debit."""
        return q2(self.credit - self.debit)

    def set_direction(self, delta: Decimal) -> None:
        """Assign debit/credit from a balance delta.

        Direction is *always* derived this way and never from which column the
        figure appeared in -- on these scans the column position is the least
        reliable signal on the page.
        """
        delta = q2(delta)
        if delta >= 0:
            self.credit, self.debit = delta, ZERO
        else:
            self.credit, self.debit = ZERO, -delta

    def note(self, message: str) -> None:
        self.repair_note = f"{self.repair_note}; {message}" if self.repair_note else message

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["row_state"] = self.row_state.value
        return {column: record.get(column) for column in FRAME_COLUMNS}


@dataclass(slots=True)
class Anchor:
    """A printed figure used to verify extraction rather than to populate it.

    Page totals, per-page brought-forward balances and printed transaction
    counts are all redundant with the transaction rows. That redundancy is the
    whole basis of accuracy at 150 DPI, so these lines are captured here
    instead of merely being filtered out as noise.
    """

    kind: str                      # PAGE_TOTAL_CREDIT | PAGE_TOTAL_DEBIT | BF_BALANCE | ...
    page_no: int
    source_row: int
    value: Decimal | None = None
    marker: str | None = None      # DR / CR where printed
    raw: str = ""


@dataclass(slots=True)
class ParseResult:
    """Everything one document yielded."""

    rows: list[Txn] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)
    page_count: int = 0
    #: Per-page notes for the audit report (skew, OCR confidence, drops).
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def anchors_of(self, kind: str) -> list[Anchor]:
        return [anchor for anchor in self.anchors if anchor.kind == kind]

    @property
    def unresolved(self) -> list[Txn]:
        return [row for row in self.rows if row.row_state is RowState.UNRESOLVED]

    def to_dataframe(self) -> pd.DataFrame:
        frame = pd.DataFrame(
            [row.as_record() for row in self.rows], columns=list(FRAME_COLUMNS)
        )
        # Money stays object-dtype: pandas would coerce Decimal to float64 and
        # reintroduce exactly the drift this pipeline exists to avoid.
        return frame


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=list(FRAME_COLUMNS))


def totals(rows: Iterable[Txn]) -> tuple[Decimal, Decimal, int, int]:
    """Sum debits and credits, and count each, over settled rows."""
    total_debit = ZERO
    total_credit = ZERO
    debit_count = 0
    credit_count = 0
    for row in rows:
        if row.debit > 0:
            total_debit += row.debit
            debit_count += 1
        if row.credit > 0:
            total_credit += row.credit
            credit_count += 1
    return q2(total_debit), q2(total_credit), debit_count, credit_count
