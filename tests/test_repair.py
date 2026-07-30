"""Error localisation, exercised by corrupting a chain whose truth is known.

Each test takes a clean five-row chain, damages it in one specific way that a
150 DPI scan actually produces, and asserts two things: that the engine reaches
the *correct diagnosis*, and -- for the cases that cannot be resolved -- that it
refuses to guess. The second half matters as much as the first. A tool that
silently invents a transaction to make a statement balance is worse than one
that admits defeat, because the error reaches a client's books unflagged.
"""

from decimal import Decimal

import pytest

from statementbridge.balance.repair import Diagnosis, ocr_plausible, resolve, settle
from statementbridge.parse.frame import RowState

from .helpers import BASE_CLOSING, base_chain


def kinds(diagnoses: list[Diagnosis]) -> list[str]:
    return [diagnosis.kind for diagnosis in diagnoses]


# --- the happy path -------------------------------------------------------

def test_clean_chain_needs_no_repair():
    rows, opening = base_chain()
    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)
    assert diagnoses == []
    assert all(row.row_state is RowState.CLEAN for row in rows)
    assert report.reconciled
    assert report.variance == Decimal("0.00")


# --- one field wrong, uniquely recoverable --------------------------------

def test_corrupt_amount_is_corrected_from_the_balance_delta():
    """8,750.00 scanned as 8,760.00. The balances either side are intact."""
    rows, opening = base_chain()
    rows[1].printed_amount = Decimal("8760.00")

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["AMOUNT_CORRUPT"]
    assert diagnoses[0].applied
    assert diagnoses[0].index == 1
    assert rows[1].debit == Decimal("8750.00")
    assert rows[1].row_state is RowState.REPAIRED
    assert report.reconciled


def test_corrupt_balance_is_corrected_and_confirmed_by_the_following_row():
    """A wrong balance breaks exactly two deltas -- that pair is the signature."""
    rows, opening = base_chain()
    rows[1].balance = Decimal("106660.00")  # true value 106650.00

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["BALANCE_CORRUPT"]
    assert diagnoses[0].applied
    assert rows[1].balance == Decimal("106650.00")
    assert rows[1].debit == Decimal("8750.00")
    assert rows[2].credit == Decimal("22000.00")
    # The row after a corrected balance is repaired too -- its delta changed.
    assert rows[2].row_state is RowState.REPAIRED
    assert report.reconciled


def test_illegible_balance_is_interpolated_when_neighbours_pin_it_down():
    rows, opening = base_chain()
    rows[1].balance = None

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["BALANCE_MISSING"]
    assert diagnoses[0].applied
    assert rows[1].balance == Decimal("106650.00")
    assert report.reconciled


def test_illegible_amount_is_recovered_from_the_delta():
    rows, opening = base_chain()
    rows[3].printed_amount = None

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["AMOUNT_MISSING"]
    assert diagnoses[0].applied
    assert rows[3].debit == Decimal("5000.00")
    assert report.reconciled


# --- the final row, where there is no successor to corroborate ------------

def test_last_row_balance_is_resolved_by_the_printed_closing():
    rows, opening = base_chain()
    rows[-1].balance = Decimal("124910.00")  # true closing 124900.00

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["BALANCE_CORRUPT"]
    assert rows[-1].balance == BASE_CLOSING
    assert report.reconciled


def test_last_row_amount_is_resolved_by_the_printed_closing():
    rows, opening = base_chain()
    rows[-1].printed_amount = Decimal("1260.00")  # true 1250.00

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["AMOUNT_CORRUPT"]
    assert rows[-1].credit == Decimal("1250.00")
    assert report.reconciled


def test_last_row_without_a_printed_closing_is_not_guessed():
    rows, opening = base_chain()
    rows[-1].printed_amount = Decimal("1260.00")

    report, diagnoses = settle(rows, opening, closing=None)

    assert kinds(diagnoses) == ["AMBIGUOUS"]
    assert not diagnoses[0].applied
    assert rows[-1].row_state is RowState.UNRESOLVED


# --- structural damage: a row the scan lost entirely ----------------------

def test_dropped_row_is_reported_never_fabricated():
    """OCR loses the 22,000.00 credit. The balances still chain, so the gap
    surfaces as an amount that cannot plausibly be a misread of 5,000.00."""
    rows, opening = base_chain()
    del rows[2]

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["MISSING_ROW"]
    assert not diagnoses[0].applied
    assert rows[2].row_state is RowState.UNRESOLVED
    # The row's own direction is unknown, so both possible gaps are offered
    # rather than one being picked arbitrarily. The true value is 22,000.
    assert "22000.00" in diagnoses[0].detail
    assert " or " in diagnoses[0].detail

    # The arithmetic still ties perfectly -- the lost transaction's effect is
    # absorbed into the surviving row's delta, so the closing balance is
    # untouched. This is precisely why a tie alone must not authorise export.
    assert report.balances_tie
    assert not report.reconciled


def test_a_plausible_single_digit_error_is_repaired_rather_than_called_a_dropped_row():
    """The discriminator is OCR plausibility, not the size of the discrepancy."""
    rows, opening = base_chain()
    rows[1].printed_amount = Decimal("3750.00")  # 8->3, one glyph

    _, diagnoses = settle(rows, opening, closing=BASE_CLOSING)
    assert kinds(diagnoses) == ["AMOUNT_CORRUPT"]


# --- damage that cannot be localised: refuse to guess ---------------------

def test_amount_and_balance_both_wrong_goes_to_review():
    rows, opening = base_chain()
    rows[1].balance = Decimal("106660.00")
    rows[1].printed_amount = Decimal("9999.00")

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert diagnoses[0].kind == "AMBIGUOUS"
    assert not diagnoses[0].applied
    assert rows[1].row_state is RowState.UNRESOLVED
    assert not report.reconciled


def test_one_real_fault_does_not_manufacture_a_second():
    """A broken row poisons the next delta; that must not become its own fault.

    Without containment the row after an unrepaired balance looks like a
    dropped transaction, and a single scanning error would be reported as two
    unrelated ones -- sending the reviewer hunting for a row that never existed.
    """
    rows, opening = base_chain()
    rows[1].balance = Decimal("106660.00")
    rows[1].printed_amount = Decimal("9999.00")

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert kinds(diagnoses) == ["AMBIGUOUS", "UPSTREAM_BREAK"]
    assert "MISSING_ROW" not in kinds(diagnoses)
    # Damage is held to the break and the row after it; the chain then recovers.
    assert report.unresolved == 2
    assert rows[3].row_state is RowState.CLEAN
    assert rows[4].row_state is RowState.CLEAN


def test_unresolved_rows_block_export_and_are_listed_with_their_page():
    rows, opening = base_chain()
    rows[1].balance = Decimal("106660.00")
    rows[1].printed_amount = Decimal("9999.00")

    report, _ = settle(rows, opening, closing=BASE_CLOSING)

    assert RowState.UNRESOLVED.blocks_export
    assert report.notes and "page 1" in report.notes[0]
    assert any(row.row_state is RowState.UNRESOLVED for row in rows)


def test_wholly_illegible_row_is_not_invented():
    rows, opening = base_chain()
    rows[2].balance = None
    rows[2].printed_amount = None

    _, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert not diagnoses[0].applied
    assert rows[2].row_state is RowState.UNRESOLVED


# --- repairs never cascade past a repaired row ----------------------------

def test_two_independent_errors_are_repaired_separately():
    rows, opening = base_chain()
    rows[0].printed_amount = Decimal("15500.00")   # amount error
    rows[3].balance = Decimal("123660.00")         # balance error

    report, diagnoses = settle(rows, opening, closing=BASE_CLOSING)

    assert set(kinds(diagnoses)) == {"AMOUNT_CORRUPT", "BALANCE_CORRUPT"}
    assert all(diagnosis.applied for diagnosis in diagnoses)
    assert report.reconciled


# --- the plausibility model itself ---------------------------------------

@pytest.mark.parametrize(
    "observed, candidate, expected",
    [
        (Decimal("15400.00"), Decimal("15400.00"), True),    # identical
        (Decimal("16400.00"), Decimal("15400.00"), True),    # one glyph
        (Decimal("16500.00"), Decimal("15400.00"), True),    # two glyphs
        (Decimal("1540.00"), Decimal("15400.00"), True),     # decimal point moved
        (Decimal("154000.00"), Decimal("15400.00"), True),   # and the other way
        (Decimal("98765.43"), Decimal("15400.00"), False),   # unrelated number
        (Decimal("5000.00"), Decimal("17000.00"), False),    # the dropped-row case
        (None, Decimal("15400.00"), True),                   # nothing was read
    ],
)
def test_ocr_plausibility_boundaries(observed, candidate, expected):
    assert ocr_plausible(observed, candidate) is expected


def test_resolve_is_idempotent():
    """Running the engine twice must not re-diagnose an already-clean chain."""
    rows, opening = base_chain()
    rows[1].printed_amount = Decimal("8760.00")

    first = resolve(rows, opening, closing=BASE_CLOSING)
    second = resolve(rows, opening, closing=BASE_CLOSING)

    assert len(first) == 1
    assert second == []
