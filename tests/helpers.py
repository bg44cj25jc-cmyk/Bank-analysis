"""Synthetic chain construction shared by the balance and repair tests."""

from __future__ import annotations

from decimal import Decimal

from statementbridge.money import q2
from statementbridge.parse.frame import Txn


def build_chain(opening: str, movements: list[str]) -> tuple[list[Txn], Decimal]:
    """A perfectly clean chain from signed movements (positive credit, negative debit).

    Tests corrupt this deliberately, so that what the repair engine is asked to
    recover is known exactly.
    """
    running = Decimal(opening)
    rows: list[Txn] = []
    for index, movement in enumerate(movements):
        signed = Decimal(movement)
        running = q2(running + signed)
        rows.append(
            Txn(
                page_no=1 + index // 20,
                source_row=index,
                narration=f"TXN {index}",
                printed_amount=abs(signed),
                balance=running,
            )
        )
    return rows, Decimal(opening)


#: A five-row current account used across the repair tests.
#: balances: 1,15,400.00 / 1,06,650.00 / 1,28,650.00 / 1,23,650.00 / 1,24,900.00
BASE_OPENING = "100000.00"
BASE_MOVEMENTS = ["15400.00", "-8750.00", "22000.00", "-5000.00", "1250.00"]
BASE_CLOSING = Decimal("124900.00")


def base_chain() -> tuple[list[Txn], Decimal]:
    return build_chain(BASE_OPENING, BASE_MOVEMENTS)
