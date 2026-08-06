"""The rules engine against 236 rows a person categorised by hand.

The client's finished migration workbook is the only labelled data this project
has: every row of its ``Ledger`` sheet carries a narration, the category someone
assigned it, the Tally ledger they chose and whether they marked it contra. That
makes it a corpus, and replaying it is the only way to find out whether the
default pack is any good rather than merely plausible.

**Unlike the OCR regressions next door, these thresholds are exact, not floors.**
The distinction matters. Extraction accuracy is measured through Tesseract, and
row agreement moves between recogniser versions -- 37.8% against 45.5% on the
same fixture -- so those tests pin a floor and defend it. Nothing here touches a
recogniser. The narrations are read as text from a spreadsheet and matched by
deterministic string rules, so the same input gives the same answer on every
machine for ever. A floor would only hide the day a rule change silently
reclassified a row.

**What this does not prove.** The workbook exercises ten of the taxonomy's
thirty-three categories and eleven of the pack's rules: one savings account for
one year, with no ATM withdrawal, no salary, no cheque paid and no utility bill
in it. Agreement here says the rules that fire are right about this account. It
says nothing about the rules that never fired, and a second labelled statement
would be worth more than any amount of further work on this one.

The workbook is also not infallible, and says so: its own Notes ask for the
name-matched self-transfers (item 4) and the branch deposits (item 6) to be
confirmed before posting. The engine agrees with those rows *and* flags them,
which is the behaviour those notes ask for.
"""

from __future__ import annotations

import collections
from decimal import Decimal
from pathlib import Path

import pytest

from statementbridge.money import q2
from statementbridge.rules.engine import classify, movements
from statementbridge.rules.pack import DEFAULT_PACK
from statementbridge.rules.summary import summarise
from statementbridge.rules.taxonomy import Category

pytestmark = pytest.mark.fixtures

#: As the workbook's Account Header sheet prints it, honorific and all -- which
#: is how it would reach the engine from the confirm-header screen.
HOLDER = "MR. AJOY NAG"

#: The workbook's own control totals, from its Category Summary sheet.
EXPECTED_ROWS = 236
EXPECTED_CREDIT = Decimal("290529.87")
EXPECTED_DEBIT = Decimal("287420.39")


class LabelledRow:
    """One row of the workbook: what it said, and what a person decided."""

    __slots__ = ("narration", "credit", "debit", "label", "ledger", "contra")

    def __init__(self, narration, credit, debit, label, ledger, contra) -> None:
        self.narration = narration or ""
        # openpyxl hands back floats, because that is what the workbook stores.
        # They become Decimal here and never go back: the client's own sheet
        # carries a closing balance of 3240.71999999997 from not doing this.
        self.credit = q2(Decimal(str(credit or 0)))
        self.debit = q2(Decimal(str(debit or 0)))
        self.label = Category(label)
        self.ledger = ledger
        self.contra = bool(contra)

    @property
    def signed_amount(self) -> Decimal:
        return q2(self.credit - self.debit)


def load_corpus(path: Path) -> list[LabelledRow]:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        rows = []
        for record in book["Ledger"].iter_rows(min_row=2, values_only=True):
            if record[0] is None:  # the sheet is padded well past its last row
                continue
            _, _, narration, label, ledger, credit, debit, contra, _ = record[:9]
            rows.append(LabelledRow(narration, credit, debit, label, ledger, contra))
        return rows
    finally:
        book.close()


@pytest.fixture(scope="module")
def corpus(tally_workbook) -> list[LabelledRow]:
    return load_corpus(tally_workbook)


@pytest.fixture(scope="module")
def decisions(corpus):
    return classify(corpus, holder=HOLDER)


# --- properties of the workbook itself, exact ----------------------------


def test_the_workbook_holds_the_rows_its_own_summary_counts(corpus):
    assert len(corpus) == EXPECTED_ROWS
    assert q2(sum((row.credit for row in corpus), Decimal("0.00"))) == EXPECTED_CREDIT
    assert q2(sum((row.debit for row in corpus), Decimal("0.00"))) == EXPECTED_DEBIT


# --- agreement, exact ----------------------------------------------------


def test_every_row_lands_in_the_category_a_person_gave_it(corpus, decisions):
    disagreements = [
        (row.narration, row.label.value, decision.category.value)
        for row, decision in zip(corpus, decisions)
        if decision.category is not row.label
    ]
    assert not disagreements, f"{len(disagreements)} of {len(corpus)}: {disagreements[:5]}"


def test_every_row_gets_the_tally_ledger_a_person_chose(corpus, decisions):
    """Stricter than the category: the ledger is what is actually posted.

    This is the assertion that caught the engine naming the self-transfer
    ledger ``MR. AJOY NAG - Own Accounts`` from a header that shouts, where the
    firm keeps ``Ajoy Nag - Own Accounts``.
    """
    disagreements = [
        (row.narration, row.ledger, decision.ledger)
        for row, decision in zip(corpus, decisions)
        if decision.ledger != row.ledger
    ]
    assert not disagreements, f"{len(disagreements)} of {len(corpus)}: {disagreements[:5]}"


def test_no_row_is_made_contra_that_was_not_and_none_is_lost(corpus, decisions):
    """A wrong contra flag posts a real expense outside the P&L entirely."""
    disagreements = [
        (row.narration, row.contra, decision.contra)
        for row, decision in zip(corpus, decisions)
        if decision.contra != row.contra
    ]
    assert not disagreements


def test_nothing_falls_through_to_unclassified(corpus, decisions):
    unmatched = [
        row.narration for row, decision in zip(corpus, decisions)
        if not decision.classified
    ]
    assert not unmatched


# --- what the engine adds to the workbook --------------------------------


def test_the_rows_flagged_for_review_are_the_ones_the_workbook_queried(
    corpus, decisions
):
    """Its Notes ask for exactly these two groups to be confirmed before posting.

    Item 4: the name-matched self-transfers, in case an ``AJOY NAG`` VPA turns
    out to be a merchant. Item 6: the bare-instrument-number branch deposits.
    The engine reaches the same answers *and* says which ones it is not certain
    of, which is the thing a spreadsheet cannot do.
    """
    flagged = collections.Counter(
        decision.rule_id for decision in decisions if decision.needs_review
    )
    assert flagged == {"self.holder-name": 41, "cheque.bare-number": 9}


def test_the_summary_reproduces_the_workbooks_control_totals_without_the_drift(
    corpus, decisions
):
    """The client's sheet computes a closing of 3240.71999999997. Decimal does not."""
    summary = summarise(movements(corpus, decisions))
    assert summary.count == EXPECTED_ROWS
    assert summary.total_credit == EXPECTED_CREDIT
    assert summary.total_debit == EXPECTED_DEBIT

    opening = Decimal("131.24")
    closing = q2(opening + summary.total_credit - summary.total_debit)
    assert closing == Decimal("3240.72")


def test_the_per_category_counts_match_the_workbooks_summary_sheet(corpus, decisions):
    summary = summarise(movements(corpus, decisions))
    for code, count in {
        "C": 6, "D": 3, "F": 41, "S": 2, "T1": 37, "T2": 90, "U1": 9,
        "NEFT_IN": 35, "IMPS_IN": 5, "IMPS_OUT": 8,
    }.items():
        assert summary.of(Category(code)).count == count, code


# --- the limits of this corpus, stated rather than implied ---------------


def test_this_corpus_exercises_a_third_of_the_taxonomy_and_a_sixth_of_the_pack(
    corpus, decisions
):
    """Pinned so the caveat is re-read if the fixture is ever changed.

    One savings account for one year. No ATM withdrawal, no salary, no cheque
    paid, no utility bill. A second labelled statement is worth more here than
    any further work on this one.
    """
    assert len({row.label for row in corpus}) == 10
    assert len(Category) == 33
    assert len({decision.rule_id for decision in decisions}) == 11
    assert len(DEFAULT_PACK) == 73
