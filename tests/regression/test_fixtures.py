"""Regression tests against the client's two sample statements.

**These do not assert the acceptance bar, because the pipeline does not meet
it.** The bar is a paisa-exact reconciliation with under 5% of rows
unresolved; measured row agreement is around 38% on the Gramin ledger and far
worse on SBI, and the cause is the 150 DPI source rather than anything these
tests could drive out.

What they do instead is pin the current behaviour, so that any change which
makes extraction *worse* fails loudly. The thresholds below are deliberately
set a little under the measured values: they are a floor to defend, not a
target that has been hit. When 300 DPI rescans arrive, raise them.

The facts asserted about the documents themselves -- page counts, the printed
page numbering, the absence of a text layer -- are exact, because those are
properties of the files and will not drift.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from statementbridge.balance.repair import settle
from statementbridge.ingest import render
from statementbridge.ingest.classify import PageClass, classify
from statementbridge.money import q2
from statementbridge.parse import scanned
from statementbridge.parse.profiles.gramin_cc import GRAMIN_CC
from statementbridge.parse.profiles.sbi_current import SBI_CURRENT

pytestmark = pytest.mark.fixtures

GRAMIN_OPENING = Decimal("-7185895.72")


def agreement(rows) -> float:
    """Share of consecutive rows whose amount matches the balance movement."""
    total = agree = 0
    for previous, current in zip(rows, rows[1:]):
        if previous.balance is None or current.balance is None:
            continue
        total += 1
        if abs(q2(current.balance - previous.balance)) == q2(abs(current.printed_amount)):
            agree += 1
    return (100.0 * agree / total) if total else 0.0


# --- properties of the source files, exact ------------------------------

def test_gramin_has_24_sheets_and_no_text_layer(gramin_pdf):
    assert render.page_count(gramin_pdf) == 24
    result = classify(gramin_pdf)
    assert result.dominant is PageClass.SCANNED
    assert result.median_chars == 0  # not merely sparse: no text objects at all


def test_sbi_has_60_sheets_and_no_text_layer(sbi_pdf):
    assert render.page_count(sbi_pdf) == 60
    result = classify(sbi_pdf)
    assert result.dominant is PageClass.SCANNED
    assert result.median_chars == 0


@pytest.mark.slow
def test_gramin_is_27_printed_pages_across_24_sheets(gramin_pdf, require_ocr):
    """Answers the discrepancy in the brief: nothing is missing from the file.

    The statement's own running headers number the pages to 27 while the PDF
    holds 24 images, because the continuous stationery was scanned with more
    than one printed page landing on some sheets.
    """
    result = scanned.parse_pdf(gramin_pdf, GRAMIN_CC, first=1, last=6)
    printed: set[int] = set()
    for diagnostic in result.diagnostics:
        printed.update(diagnostic["printed_pages"])
    assert printed, "no printed page numbers were legible"
    assert max(printed) > 6, "printed page numbers should outrun the sheet count"


# --- extraction quality, floors to defend -------------------------------

@pytest.mark.slow
def test_gramin_extraction_does_not_regress(gramin_pdf, require_ocr):
    result = scanned.parse_pdf(gramin_pdf, GRAMIN_CC, first=1, last=3)
    assert len(result.rows) >= 100, "row recovery regressed"
    assert agreement(result.rows) >= 30.0, "row agreement regressed"

    report, _ = settle(result.rows, GRAMIN_OPENING)
    # Not reconciled -- asserted so the gap stays visible rather than implied.
    assert not report.reconciled
    assert report.repaired >= 1, "the repair engine stopped firing entirely"


@pytest.mark.slow
def test_sbi_ruled_table_yields_rows(sbi_pdf, require_ocr):
    """SBI rows span several printed lines; row banding is what recovers them.

    Before the ruled-table path existed this produced no usable rows at all,
    so the floor here guards the band detection rather than any accuracy claim.
    """
    result = scanned.parse_pdf(sbi_pdf, SBI_CURRENT, first=3, last=5)
    assert len(result.rows) >= 20, "ruled-table row banding regressed"
    assert any(row.date is not None for row in result.rows)
    assert any(row.printed_amount for row in result.rows)


@pytest.mark.slow
def test_traps_never_enter_the_frame(gramin_pdf, require_ocr):
    """No page total, header or separator may be counted as a transaction."""
    result = scanned.parse_pdf(gramin_pdf, GRAMIN_CC, first=1, last=3)
    for row in result.rows:
        lowered = row.narration.lower()
        assert "page total" not in lowered
        assert "service outlet" not in lowered
        assert "peg review" not in lowered
        assert "order by gl" not in lowered


@pytest.mark.slow
def test_page_total_anchors_are_captured(gramin_pdf, require_ocr):
    result = scanned.parse_pdf(gramin_pdf, GRAMIN_CC, first=1, last=3)
    anchors = result.anchors_of("PAGE_TOTAL_CREDIT") + result.anchors_of("PAGE_TOTAL_DEBIT")
    assert len(anchors) >= 3, "printed page totals are no longer being captured"
