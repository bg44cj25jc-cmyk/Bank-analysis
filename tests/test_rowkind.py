"""Every trap in the fixtures, including OCR-mangled forms of each."""

from decimal import Decimal

import pytest

from statementbridge.parse.rowkind import RowKind, canon, classify_line


def kind(text: str) -> RowKind:
    return classify_line(text).kind


# --- page totals: the trap that would double a whole page ----------------

@pytest.mark.parametrize(
    "line",
    [
        "Page Total Credit :        12,34,567.00",
        "Page Total Debit :          9,87,654.32",
        "PAGE TOTAL CREDIT : 12,34,567.00",
    ],
)
def test_page_totals_never_reach_the_frame(line):
    assert kind(line) is RowKind.PAGE_TOTAL


@pytest.mark.parametrize(
    "line",
    [
        "Paqe Tota1 Credit :   12,34,567.00",   # q for g, 1 for l
        "Page Tota| Debit :     9,87,654.32",   # pipe for l
        "Paqe TotaI Credlt :   12,34,567.00",   # capital I, i->l
    ],
)
def test_page_totals_survive_dot_matrix_damage(line):
    """An exact regex would let these straight through into the frame."""
    assert kind(line) is RowKind.PAGE_TOTAL


def test_page_total_is_captured_as_an_anchor_with_its_figure():
    result = classify_line("Page Total Credit :  12,34,567.00", page_no=4, source_row=61)
    assert result.anchor is not None
    assert result.anchor.kind == "PAGE_TOTAL_CREDIT"
    assert result.anchor.value == Decimal("1234567.00")
    assert result.anchor.page_no == 4


# --- repeated headers, separators, and the Gramin trailer ----------------

@pytest.mark.parametrize(
    "line",
    [
        "Service Outlet : RAJBARI",
        "Peg Review date : 31/03/2026",
        "Statement of Account",
        "Printed On : 01/04/2026",
        "Date  Particulars  Chq No  Withdrawal  Deposit  Balance",
        "Txn Date   Value Date   Description   Debit   Credit   Balance",
    ],
)
def test_repeated_headers_are_rejected(line):
    assert kind(line) is RowKind.HEADER_REPEAT


@pytest.mark.parametrize(
    "line",
    [
        "..............................................",
        "----------------------------------------------",
        "______________________________________________",
        "Order by GL. Date",
        "* * * * * * * * * * * *",
    ],
)
def test_separators_and_sort_notes_are_rejected(line):
    assert kind(line) in (RowKind.SEPARATOR, RowKind.BLANK_FILLER)


@pytest.mark.parametrize(
    "line",
    [
        "Limits : 75,00,000.00   Draw Power : 72,00,000.00   Int Rate : 9.50",
        "Drawing Power   72,00,000.00",
        "Sanction Limit : 75,00,000.00",
    ],
)
def test_gramin_limits_trailer_is_not_transactional(line):
    assert kind(line) is RowKind.LIMITS_TABLE


@pytest.mark.parametrize("line", ["", "   ", "\t"])
def test_blank_filler_rows_are_rejected(line):
    assert kind(line) is RowKind.BLANK_FILLER


# --- opening / carry-forward anchors -------------------------------------

def test_sbi_brought_forward_is_an_opening_anchor():
    result = classify_line("BROUGHT FORWARD                    0.00", page_no=1)
    assert result.kind is RowKind.OPENING
    assert result.anchor is not None
    assert result.anchor.value == Decimal("0.00")


def test_bf_balance_is_an_opening_anchor_with_dr_marker():
    result = classify_line("B/F Balance    71,85,895.72 Dr", page_no=1)
    assert result.kind is RowKind.OPENING
    assert result.anchor.value == Decimal("7185895.72")
    assert result.anchor.marker == "DR"


def test_carried_forward_is_captured_separately():
    assert kind("Carried Forward   90,98,371.22 Dr") is RowKind.CARRY_FORWARD


# --- the false positives that would silently delete real transactions ----

@pytest.mark.parametrize(
    "line",
    [
        "15/07/2025  CASH DEPOSIT SELF DHARMANAGAR      50,000.00   1,20,000.00",
        "16/07/2025  MIN BALANCE CHARGES GST             118.00     1,19,882.00",
        "17/07/2025  ATM WITHDRAWAL AGARTALA           10,000.00   1,09,882.00",
        "18/07/2025  NEFT CR-UTIB0001506-PHONEPE LIMITED  1,335.00  1,11,217.00",
        "19/07/2025  UPI/DR/BISHAL NAG/YBL               960.00     1,10,257.00",
        "20/07/2025  INT CREDITED                         12.50     1,10,269.50",
    ],
)
def test_real_transactions_are_not_mistaken_for_noise(line):
    """A narration containing 'deposit', 'balance' or 'credit' is still a row.

    This is why generic single words are not trap patterns: matching them would
    drop genuine transactions and the reconciliation would fail with no clue as
    to where the money went.
    """
    assert kind(line) is RowKind.TRANSACTION


def test_column_header_needs_several_tokens_and_no_money():
    # Three header words, no figures -> header.
    assert kind("Date  Description  Balance") is RowKind.HEADER_REPEAT
    # The same words carrying a figure is a transaction, not a header.
    assert kind("01/04/2025 OPENING DESCRIPTION BALANCE 1,234.00") is not RowKind.HEADER_REPEAT


# --- the canonicalisation that makes the above work ----------------------

def test_canonicalisation_collapses_confusable_glyphs():
    assert canon("Paqe Tota1 Credit") == canon("Page Total Credit")
    assert canon("8R0UGHT F0RWARD") == canon("BROUGHT FORWARD")
    assert canon("5ervice 0utlet") == canon("Service Outlet")
