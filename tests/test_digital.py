"""The pdfplumber family, against synthetic text-layer PDFs.

Neither supplied fixture has a text layer, so these PDFs are built by the test
suite. They cannot prove the parser handles a real bank's export, but they do
prove the digital path shares the frame contract, the trap classifier and the
balance engine with the OCR path -- which is the part most likely to rot.
"""

from decimal import Decimal

import pytest

from statementbridge.balance.repair import settle
from statementbridge.ingest.classify import PageClass, classify
from statementbridge.parse import digital
from statementbridge.parse.profiles.base import BankProfile

from .synthpdf import write_pdf

PROFILE = BankProfile(key="synthetic", name="Synthetic test bank")

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


@pytest.fixture()
def ledger_pdf(tmp_path):
    return write_pdf(tmp_path / "synthetic.pdf", [LEDGER])


def test_a_text_layer_pdf_is_classified_as_digital(ledger_pdf):
    result = classify(ledger_pdf)
    assert result.pages == [PageClass.DIGITAL]
    assert result.dominant is PageClass.DIGITAL
    assert not result.mixed


def test_scanned_fixture_is_classified_as_scanned(fixture_dir):
    """The real fixtures have no text layer at all -- that is why they need OCR."""
    if fixture_dir is None:
        pytest.skip("fixtures not available")
    pdf = fixture_dir / "fixture_gramin_cc_scanned.pdf.pdf"
    if not pdf.exists():
        pytest.skip("Gramin fixture not present")
    result = classify(pdf)
    assert result.dominant is PageClass.SCANNED
    assert result.median_chars < 50


def test_digital_parser_extracts_the_transactions(ledger_pdf):
    result = digital.parse_pdf(ledger_pdf, PROFILE)
    narrations = [row.narration for row in result.rows]

    assert len(result.rows) == 4
    assert any("RAMESH" in text for text in narrations)
    assert any("CASH DEPOSIT" in text for text in narrations)
    # The header, the rule and the page totals must not appear as transactions.
    assert not any("Particulars" in text for text in narrations)
    assert not any("Page Total" in text for text in narrations)


def test_page_totals_are_captured_as_anchors(ledger_pdf):
    result = digital.parse_pdf(ledger_pdf, PROFILE)
    credits = result.anchors_of("PAGE_TOTAL_CREDIT")
    debits = result.anchors_of("PAGE_TOTAL_DEBIT")
    assert credits and credits[0].value == Decimal("24150.00")
    assert debits and debits[0].value == Decimal("22118.00")


def test_digital_rows_reconcile_through_the_shared_balance_engine(ledger_pdf):
    """Same chain, same repair, same report as the scanned path."""
    result = digital.parse_pdf(ledger_pdf, PROFILE)
    report, diagnoses = settle(
        result.rows, Decimal("100000.00"), closing=Decimal("102032.00")
    )
    assert diagnoses == []
    assert report.total_credit == Decimal("24150.00")
    assert report.total_debit == Decimal("22118.00")
    assert report.reconciled
    assert report.variance == Decimal("0.00")


def test_direction_is_derived_from_the_balance_not_the_column(ledger_pdf):
    result = digital.parse_pdf(ledger_pdf, PROFILE)
    settle(result.rows, Decimal("100000.00"), closing=Decimal("102032.00"))
    by_narration = {row.narration: row for row in result.rows}
    credit_row = next(r for k, r in by_narration.items() if "RAMESH" in k)
    debit_row = next(r for k, r in by_narration.items() if "SUPPLIER" in k)
    assert credit_row.credit == Decimal("15400.00") and credit_row.debit == 0
    assert debit_row.debit == Decimal("22000.00") and debit_row.credit == 0


def test_multi_page_document_tracks_pages(tmp_path):
    pdf = write_pdf(tmp_path / "two.pdf", [LEDGER, LEDGER])
    result = digital.parse_pdf(pdf, PROFILE)
    assert result.page_count == 2
    assert len(result.rows) == 8
    assert {row.page_no for row in result.rows} == {1, 2}
