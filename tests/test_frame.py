"""The transaction frame's contract, now that it carries an accounting decision.

Everything downstream of extraction is written against ``Txn`` and
``FRAME_COLUMNS``, so what is asserted here is the shape of the boundary rather
than any particular parser's behaviour.
"""

from __future__ import annotations

import json
from decimal import Decimal

from statementbridge.parse.frame import (
    CONTRACT_COLUMNS,
    FRAME_COLUMNS,
    ParseResult,
    RowState,
    Txn,
)
from statementbridge.rules.engine import classify_narration
from statementbridge.rules.rule import Context
from statementbridge.rules.taxonomy import Category
from statementbridge.store.jobs import record_of


def classified_row() -> Txn:
    row = Txn(
        page_no=1,
        source_row=0,
        narration="UPI/CR/BISHAL NAG/AXL",
        credit=Decimal("100.00"),
        balance=Decimal("231.24"),
    )
    row.apply(
        classify_narration(
            row.narration, row.signed_amount, context=Context.for_holder("MR. AJOY NAG"),
            holder="MR. AJOY NAG",
        )
    )
    return row


def test_the_nine_agreed_columns_have_not_moved():
    """The contract the client signed off. Anything added goes after it."""
    assert CONTRACT_COLUMNS == (
        "date", "value_date", "instrument_no", "narration",
        "debit", "credit", "balance", "page_no", "source_row",
    )
    assert FRAME_COLUMNS[:9] == CONTRACT_COLUMNS


def test_a_row_carries_its_decision_as_well_as_its_money():
    row = classified_row()
    assert row.category is Category.UPI_IN
    assert row.tally_ledger == "Sundry Receipts / Debtors"
    assert row.rule_id == "upi.in"
    assert row.contra is False
    assert row.needs_review is False


def test_an_unclassified_row_and_an_unread_one_are_distinguishable():
    """``None`` means the rules never ran; ``UNCL`` means they ran and found nothing."""
    untouched = Txn(page_no=1, source_row=0, narration="ANYTHING")
    assert untouched.category is None

    row = Txn(page_no=1, source_row=1, narration="A LINE NOBODY HAS SEEN",
              credit=Decimal("5.00"))
    row.apply(classify_narration(row.narration, row.signed_amount, context=Context()))
    assert row.category is Category.UNCLASSIFIED


def test_the_record_carries_the_code_the_firm_reads():
    record = classified_row().as_record()
    assert record["category"] == "T1"
    assert record["row_state"] == RowState.CLEAN.value
    assert set(record) == set(FRAME_COLUMNS)


def test_an_unclassified_record_says_none_rather_than_inventing_a_code():
    record = Txn(page_no=1, source_row=0, narration="X").as_record()
    assert record["category"] is None
    assert record["tally_ledger"] == ""


def test_the_transported_record_is_json_safe_and_keeps_money_as_text():
    """``record_of`` is what the worker posts, so it must survive json.dumps."""
    record = record_of(classified_row())
    round_tripped = json.loads(json.dumps(record))

    assert round_tripped["category"] == "T1"
    assert round_tripped["credit"] == "100.00"
    assert round_tripped["balance"] == "231.24"
    assert round_tripped["contra"] is False
    assert round_tripped["needs_review"] is False


def test_the_dataframe_gains_the_decision_columns():
    result = ParseResult(rows=[classified_row()])
    frame = result.to_dataframe()
    assert list(frame.columns) == list(FRAME_COLUMNS)
    assert frame.loc[0, "category"] == "T1"
    assert frame.loc[0, "tally_ledger"] == "Sundry Receipts / Debtors"
