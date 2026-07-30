"""The signed running-balance model.

One convention is used everywhere inside the pipeline: **credit positive,
debit negative**. A savings account sits above zero, a cash-credit or overdraft
account sits below it, and an account that crosses zero mid-statement needs no
special handling at all -- it simply changes sign. The printed ``Dr``/``Cr``
marker is a presentation detail reapplied only at export.

Direction is derived from the balance delta, never from which column a figure
was printed in. On these scans column position is the least trustworthy signal
on the page, while the running balance is checked against every neighbouring
row and against a printed anchor at nearly every page boundary.

    delta = balance[n] - balance[n-1]
    delta > 0  ->  credit of |delta|
    delta < 0  ->  debit  of |delta|

Worked against the Gramin cash-credit fixture, where the balance is a debit
figure that grows on debit:

    -71,85,895.72  -  4,25,53,191.50  +  4,06,40,716.00  =  -90,98,371.22
    i.e. opening 71,85,895.72 Dr  ->  closing 90,98,371.22 Dr
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..money import ZERO, q2
from ..parse.frame import RowState, Txn


@dataclass(slots=True)
class ChainReport:
    """Outcome of settling a document's balance chain."""

    opening: Decimal
    closing_computed: Decimal
    closing_printed: Decimal | None = None
    total_debit: Decimal = ZERO
    total_credit: Decimal = ZERO
    debit_count: int = 0
    credit_count: int = 0
    repaired: int = 0
    unresolved: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def variance(self) -> Decimal:
        """Printed closing minus computed closing. Exact, never floating."""
        if self.closing_printed is None:
            return ZERO
        return q2(self.closing_printed - self.closing_computed)

    @property
    def balances_tie(self) -> bool:
        """Opening + credits - debits equals the printed closing, to the paisa."""
        return self.closing_printed is not None and self.variance == 0

    @property
    def reconciled(self) -> bool:
        """Safe to export: the arithmetic ties *and* nothing is unresolved.

        The second condition is not belt-and-braces. A row the OCR dropped
        entirely leaves the chain's endpoints untouched -- the missing
        transaction's effect is simply absorbed into the neighbouring row's
        delta -- so the statement still balances perfectly while a real
        transaction is gone. Arithmetic alone cannot detect that; only the
        unresolved flag, the printed page totals and the printed transaction
        counts can. Treating a tie as sufficient would ship exactly the error
        this pipeline exists to prevent.
        """
        return self.balances_tie and self.unresolved == 0

    def summary(self) -> str:
        from ..money import format_drcr, format_indian

        lines = [
            f"opening        {format_drcr(self.opening)}",
            f"total credits  {format_indian(self.total_credit)}  ({self.credit_count})",
            f"total debits   {format_indian(self.total_debit)}  ({self.debit_count})",
            f"closing (calc) {format_drcr(self.closing_computed)}",
        ]
        if self.closing_printed is not None:
            lines.append(f"closing (print){format_drcr(self.closing_printed)}")
            lines.append(f"variance       {format_indian(self.variance)}")
        lines.append(f"repaired {self.repaired}   unresolved {self.unresolved}")
        return "\n".join(lines)


def deltas(rows: list[Txn], opening: Decimal) -> list[Decimal | None]:
    """Balance change implied by each row, or None where a balance is missing."""
    out: list[Decimal | None] = []
    previous: Decimal | None = q2(opening)
    for row in rows:
        if row.balance is None or previous is None:
            out.append(None)
        else:
            out.append(q2(row.balance - previous))
        if row.balance is not None:
            previous = row.balance
    return out


def is_consistent(delta: Decimal | None, amount: Decimal | None) -> bool:
    """Does the printed amount agree with the balance movement, to the paisa?"""
    if delta is None or amount is None:
        return False
    return abs(delta) == q2(abs(amount))


def apply_directions(rows: list[Txn], opening: Decimal) -> None:
    """Set debit/credit on every row from its balance delta."""
    previous = q2(opening)
    for row in rows:
        if row.balance is None:
            continue
        row.set_direction(row.balance - previous)
        previous = row.balance


def recompute_forward(rows: list[Txn], opening: Decimal) -> Decimal:
    """Rebuild every balance from the opening plus the settled amounts.

    Used after repair to guarantee the emitted chain is internally consistent:
    whatever the scan said, the exported balances always add up.
    """
    running = q2(opening)
    for row in rows:
        running = q2(running + row.signed_amount)
        row.balance = running
    return running


def summarise(rows: list[Txn], opening: Decimal, closing_printed: Decimal | None) -> ChainReport:
    total_debit = ZERO
    total_credit = ZERO
    debit_count = 0
    credit_count = 0
    repaired = 0
    unresolved = 0
    for row in rows:
        if row.debit > 0:
            total_debit += row.debit
            debit_count += 1
        if row.credit > 0:
            total_credit += row.credit
            credit_count += 1
        if row.row_state is RowState.REPAIRED:
            repaired += 1
        elif row.row_state is RowState.UNRESOLVED:
            unresolved += 1
    return ChainReport(
        opening=q2(opening),
        closing_computed=q2(opening + total_credit - total_debit),
        closing_printed=closing_printed,
        total_debit=q2(total_debit),
        total_credit=q2(total_credit),
        debit_count=debit_count,
        credit_count=credit_count,
        repaired=repaired,
        unresolved=unresolved,
    )
