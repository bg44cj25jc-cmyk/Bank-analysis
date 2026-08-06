"""The category summary, and the invariant that makes it trustworthy.

Every settled row belongs to exactly one category, so the category totals must
equal the balance chain's totals to the paisa. The chain is built here by
``settle`` rather than by hand, so the two sides are computed by genuinely
different code from the same rows -- which is the only arrangement in which the
agreement means anything.
"""

from __future__ import annotations

from decimal import Decimal

from statementbridge.balance.chain import ChainReport
from statementbridge.balance.repair import settle
from statementbridge.money import q2
from statementbridge.parse.frame import RowState, Txn
from statementbridge.rules.engine import classify, movements
from statementbridge.rules.summary import summarise
from statementbridge.rules.taxonomy import Category

HOLDER = "MR. AJOY NAG"

#: (narration, signed movement). Credit positive, debit negative, as everywhere.
ENTRIES = [
    ("CASA CREDIT INTEREST CAPITALIZED", "1.00"),
    ("CASH DEP-SELF-CASH DHARMANAGAR", "10000.00"),
    ("UPI/CR/BISHAL NAG/AXL", "100.00"),
    ("UPI/DR/BIDYUT DAS/BDBL", "-250.00"),
    ("IMPS-532116454511-BISHAL NAG-UCBA0002520", "-19900.00"),
    ("GST 1818-GST", "-337.50"),
    ("OBO INITIATED: 90001511966165 AJOY NAG", "150000.00"),
    ("184693 DHARMANAGAR", "200.00"),
    ("A NARRATION THE PACK HAS NEVER SEEN", "-42.00"),
]

OPENING = Decimal("131.24")


def statement() -> tuple[list[Txn], ChainReport]:
    """Settled rows and the chain report they produced."""
    rows: list[Txn] = []
    running = OPENING
    for index, (text, movement) in enumerate(ENTRIES):
        signed = Decimal(movement)
        running = q2(running + signed)
        rows.append(
            Txn(
                page_no=1,
                source_row=index,
                narration=text,
                printed_amount=abs(signed),
                balance=running,
            )
        )
    chain, _ = settle(rows, OPENING, closing=running)
    return rows, chain


def summary_for(rows, holder=HOLDER):
    return summarise(movements(rows, classify(rows, holder=holder)))


# --- the invariant --------------------------------------------------------


def test_the_category_totals_equal_the_balance_chains_totals():
    rows, chain = statement()
    summary = summary_for(rows)

    assert summary.reconciles_with(chain)
    assert summary.total_credit == chain.total_credit
    assert summary.total_debit == chain.total_debit
    assert summary.variance_against(chain) == (Decimal("0.00"), Decimal("0.00"))


def test_every_row_lands_in_exactly_one_category():
    rows, chain = statement()
    summary = summary_for(rows)
    assert summary.count == len(rows)
    assert summary.count == chain.credit_count + chain.debit_count


def test_a_dropped_row_breaks_the_tie_which_is_the_whole_point():
    """The check has to be able to fail, or it is decoration."""
    rows, chain = statement()
    short = summary_for(rows[:-1])
    assert not short.reconciles_with(chain)


def test_an_unclassified_row_still_ties():
    """Ties prove the arithmetic of the classification, never its correctness."""
    rows, chain = statement()
    summary = summary_for(rows)
    assert summary.unclassified == 1
    assert summary.reconciles_with(chain)


def test_a_row_the_balance_engine_could_not_settle_is_still_categorised():
    """What a transaction was does not depend on whether its figure survived."""
    rows, _ = statement()
    rows[2].row_state = RowState.UNRESOLVED
    summary = summary_for(rows)
    assert summary.of(Category.UPI_IN).count == 1


# --- what the sheet says --------------------------------------------------


def test_the_summary_lists_every_category_including_the_empty_ones():
    """The zero lines are the checklist: considered and absent, not overlooked."""
    rows, _ = statement()
    summary = summary_for(rows)
    assert len(summary.totals) == len(Category)
    assert summary.of(Category.PENSION).count == 0
    assert not summary.of(Category.PENSION).occurred


def test_the_figures_land_against_the_right_categories():
    rows, _ = statement()
    summary = summary_for(rows)

    assert summary.of(Category.INTEREST_CREDITED).credit == Decimal("1.00")
    assert summary.of(Category.CASH_DEPOSIT).credit == Decimal("10000.00")
    assert summary.of(Category.UPI_IN).credit == Decimal("100.00")
    assert summary.of(Category.UPI_OUT).debit == Decimal("250.00")
    assert summary.of(Category.IMPS_OUT).debit == Decimal("19900.00")
    assert summary.of(Category.BANK_CHARGES).debit == Decimal("337.50")
    assert summary.of(Category.SELF_TRANSFER).credit == Decimal("150000.00")
    assert summary.of(Category.CHEQUE_DEPOSIT).credit == Decimal("200.00")
    assert summary.of(Category.UNCLASSIFIED).debit == Decimal("42.00")


def test_contra_rows_are_counted_so_they_can_be_posted_as_contra_vouchers():
    rows, _ = statement()
    summary = summary_for(rows)
    # The cash deposit and the transfer from the holder's own account.
    assert summary.contra_count == 2


def test_the_ledgers_actually_used_are_reported_once_each():
    """The firm creates these in Tally once, before anything is posted."""
    rows, _ = statement()
    summary = summary_for(rows)
    assert len(summary.ledgers) == len(set(summary.ledgers))
    assert "Cash A/c (Contra)" in summary.ledgers
    assert "Ajoy Nag - Own Accounts (Contra)" in summary.ledgers


def test_money_leaves_the_summary_as_text_never_as_a_json_number():
    """The rule the whole service layer runs on: JSON has no decimal type."""
    rows, _ = statement()
    payload = summary_for(rows).as_dict()
    assert payload["total_credit"] == "160301.00"
    assert isinstance(payload["total_debit"], str)
    for line in payload["categories"]:
        assert isinstance(line["credit"], str)
        assert isinstance(line["debit"], str)


def test_the_rendered_sheet_says_whether_it_ties():
    rows, chain = statement()
    rendered = summary_for(rows).render(chain)
    assert "against the balance chain: ties" in rendered
    assert "TOTAL" in rendered
    assert "unclassified 1" in rendered
