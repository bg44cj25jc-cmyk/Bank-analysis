"""Per-page routing between the two parser families.

The bug being closed here is that ``ingest.classify`` decided, per page, whether
a sheet was text or a picture of text -- and nothing on the parse path ever
asked it. Both CLI commands went straight to the OCR family, so a downloaded
statement would have been rasterised and its exact characters guessed at again.
The statement behind the client's target workbook is exactly that kind of file.

So the sharpest test here is a negative one: parsing a text-layer PDF must never
reach the rasteriser at all.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from statementbridge.balance.repair import settle
from statementbridge.ingest import render
from statementbridge.parse import route, scanned
from statementbridge.parse.profiles.base import BankProfile
from statementbridge.parse.profiles.gramin_cc import GRAMIN_CC
from statementbridge.money import q2

from .synthpdf import write_mixed_pdf, write_pdf

PROFILE = BankProfile(key="synthetic-route", name="Synthetic routing bank")

LEDGER = [
    "ACME BANK LIMITED                      Statement of Account",
    "Account Number : 1234567890            Page 1",
    "Date        Particulars              Debit      Credit     Balance",
    "-----------------------------------------------------------------",
    "01-04-2025  Opening Balance                              1,00,000.00",
    "02-04-2025  UPI/CR/RAMESH/YBL                 15,400.00  1,15,400.00",
    "03-04-2025  CASH DEPOSIT SELF                  8,750.00  1,24,150.00",
    "04-04-2025  NEFT TO SUPPLIER        22,000.00             1,02,150.00",
    "05-04-2025  MIN BALANCE CHARGES        118.00             1,02,032.00",
    "Page Total Credit :  24,150.00",
    "Page Total Debit :   22,118.00",
]


def agreement(rows) -> float:
    total = agree = 0
    for previous, current in zip(rows, rows[1:]):
        if previous.balance is None or current.balance is None:
            continue
        total += 1
        if abs(q2(current.balance - previous.balance)) == q2(abs(current.printed_amount)):
            agree += 1
    return (100.0 * agree / total) if total else 0.0


# --- the bug ------------------------------------------------------------

def test_a_text_layer_pdf_is_never_rasterised(tmp_path, monkeypatch):
    """The negative assertion that gives this module its reason to exist.

    Rendering a page that already carries exact characters throws away the
    geometry and the characters both, then asks OCR to guess them back. If the
    router ever reaches the rasteriser on a digital page, this fails loudly
    rather than quietly returning worse rows.
    """
    def explode(*args, **kwargs):
        raise AssertionError("a digital page was sent to the rasteriser")

    monkeypatch.setattr(render, "render", explode)

    result = route.parse_statement(write_pdf(tmp_path / "digital.pdf", [LEDGER]), PROFILE)

    assert len(result.rows) == 4
    assert all(d["page_class"] == "DIGITAL" for d in result.diagnostics)


def test_digital_rows_reconcile_through_the_router(tmp_path):
    """Routing changes which family reads the page, and nothing after it."""
    result = route.parse_statement(write_pdf(tmp_path / "digital.pdf", [LEDGER]), PROFILE)

    report, diagnoses = settle(
        result.rows, Decimal("100000.00"), closing=Decimal("102032.00")
    )
    assert diagnoses == []
    assert report.reconciled
    assert report.variance == Decimal("0.00")


# --- mixed documents ----------------------------------------------------

def test_a_mixed_document_sends_each_page_to_the_right_family(tmp_path):
    """A rescanned sheet stapled into a digital export.

    This is the case per-page classification was written for, and the case a
    document-level decision gets wrong by construction.
    """
    pdf = write_mixed_pdf(tmp_path / "mixed.pdf", [LEDGER, None, LEDGER])

    result = route.parse_statement(pdf, PROFILE)

    classes = [d["page_class"] for d in result.diagnostics]
    assert classes == ["DIGITAL", "SCANNED", "DIGITAL"]
    # The two text pages still yield their transactions.
    assert len([row for row in result.rows if row.page_no in (1, 3)]) == 8


def test_page_ranges_are_honoured(tmp_path):
    pdf = write_pdf(tmp_path / "three.pdf", [LEDGER, LEDGER, LEDGER])

    result = route.parse_statement(pdf, PROFILE, first=2, last=3)

    assert result.page_count == 2
    assert {row.page_no for row in result.rows} == {2, 3}


def test_an_empty_range_yields_nothing(tmp_path):
    pdf = write_pdf(tmp_path / "one.pdf", [LEDGER])

    result = route.parse_statement(pdf, PROFILE, first=5, last=9)

    assert result.rows == []
    assert result.page_count == 0


# --- equivalence with the family it replaces on the parse path ----------

@pytest.mark.fixtures
@pytest.mark.slow
def test_the_router_extracts_exactly_what_the_ocr_family_did(gramin_pdf, require_ocr):
    """The refactor that made routing possible must not move a single figure.

    ``read_page`` was lifted out of two near-identical copies. If that changed
    anything at all about extraction, it shows up here as a differing row.
    """
    direct = scanned.parse_pdf(gramin_pdf, GRAMIN_CC, first=1, last=3)
    routed = route.parse_statement(gramin_pdf, GRAMIN_CC, first=1, last=3)

    assert len(routed.rows) == len(direct.rows)
    assert agreement(routed.rows) == agreement(direct.rows)

    def fields(row):
        return (
            row.page_no, row.source_row, row.narration, row.printed_amount,
            row.balance, row.date, row.value_date, row.instrument_no,
            row.raw_amount_text, row.raw_balance_text,
        )

    assert [fields(r) for r in routed.rows] == [fields(r) for r in direct.rows]
    assert [(a.kind, a.value) for a in routed.anchors] == [
        (a.kind, a.value) for a in direct.anchors
    ]
