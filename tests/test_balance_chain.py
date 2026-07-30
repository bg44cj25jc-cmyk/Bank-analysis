"""The signed balance model, including the cash-credit zero crossing."""

from decimal import Decimal

import pytest

from statementbridge.money import format_drcr, q2
from statementbridge.parse.frame import RowState, Txn
from statementbridge.balance.chain import (
    apply_directions,
    deltas,
    is_consistent,
    recompute_forward,
    summarise,
)
from statementbridge.balance.repair import settle


def build(opening: str, movements: list[str]) -> tuple[list[Txn], Decimal]:
    """Build a clean chain from signed movements (positive credit, negative debit)."""
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


def test_direction_comes_from_the_delta_not_the_column():
    rows, opening = build("1000.00", ["500.00", "-200.00", "-300.00"])
    apply_directions(rows, opening)
    assert (rows[0].credit, rows[0].debit) == (Decimal("500.00"), Decimal("0.00"))
    assert (rows[1].debit, rows[1].credit) == (Decimal("200.00"), Decimal("0.00"))
    assert (rows[2].debit, rows[2].credit) == (Decimal("300.00"), Decimal("0.00"))


def test_cash_credit_balance_crossing_zero_needs_no_special_case():
    """An OD/CC balance is a Dr figure that grows on debit and may cross into Cr."""
    rows, opening = build(
        "-5000.00",
        ["-2000.00", "9000.00", "1000.00", "-6000.00", "-1500.00"],
    )
    apply_directions(rows, opening)

    printed = [format_drcr(row.balance) for row in rows]
    assert printed == [
        "7,000.00 Dr",   # debit grows the Dr balance
        "2,000.00 Cr",   # crosses zero into credit
        "3,000.00 Cr",
        "3,000.00 Dr",   # and back again
        "4,500.00 Dr",
    ]
    assert rows[0].debit == Decimal("2000.00")
    assert rows[1].credit == Decimal("9000.00")


def test_gramin_identity_reconciles_to_the_paisa():
    """71,85,895.72 Dr + 4,25,53,191.50 Dr - 4,06,40,716.00 Cr = 90,98,371.22 Dr."""
    opening = Decimal("-7185895.72")
    rows, _ = build(str(opening), ["-42553191.50", "40640716.00"])
    report, _ = settle(rows, opening, closing=Decimal("-9098371.22"))

    assert report.total_debit == Decimal("42553191.50")
    assert report.total_credit == Decimal("40640716.00")
    assert format_drcr(report.closing_computed) == "90,98,371.22 Dr"
    assert report.variance == Decimal("0.00")
    assert report.reconciled


def test_sbi_identity_reconciles_to_the_paisa():
    """Brought forward 0.00, closing 1,97,817.10 CR."""
    opening = Decimal("0.00")
    rows, _ = build("0.00", ["214589593.12", "-214391776.02"])
    report, _ = settle(rows, opening, closing=Decimal("197817.10"))

    assert report.total_credit == Decimal("214589593.12")
    assert report.total_debit == Decimal("214391776.02")
    assert format_drcr(report.closing_computed) == "1,97,817.10 Cr"
    assert report.reconciled


def test_zero_variance_is_exact_not_approximate():
    rows, opening = build("131.24", ["290529.87", "-287420.39"])
    report, _ = settle(rows, opening, closing=Decimal("3240.72"))
    assert report.variance == Decimal("0.00")
    assert str(report.closing_computed) == "3240.72"


def test_deltas_report_gaps_where_a_balance_is_missing():
    rows, opening = build("1000.00", ["500.00", "-200.00"])
    rows[0].balance = None
    values = deltas(rows, opening)
    assert values[0] is None
    assert not is_consistent(values[0], rows[0].printed_amount)


def test_recompute_forward_guarantees_an_internally_consistent_chain():
    rows, opening = build("1000.00", ["500.00", "-200.00", "-300.00"])
    apply_directions(rows, opening)
    for row in rows:
        row.balance = Decimal("0.00")  # scribble over every balance
    closing = recompute_forward(rows, opening)
    assert [row.balance for row in rows] == [
        Decimal("1500.00"), Decimal("1300.00"), Decimal("1000.00")
    ]
    assert closing == Decimal("1000.00")


def test_summary_counts_debits_and_credits_separately():
    rows, opening = build("0.00", ["100.00", "-50.00", "-25.00", "200.00"])
    apply_directions(rows, opening)
    report = summarise(rows, opening, None)
    assert (report.credit_count, report.debit_count) == (2, 2)
    assert report.total_credit == Decimal("300.00")
    assert report.total_debit == Decimal("75.00")


def test_empty_document_does_not_explode():
    report, diagnoses = settle([], Decimal("0.00"), closing=Decimal("0.00"))
    assert report.closing_computed == Decimal("0.00")
    assert diagnoses == []
