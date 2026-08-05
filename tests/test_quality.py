"""The upload capture-quality gate.

Two things are being defended here.

The first is that the gate reaches the *right verdict on the real files*, and
for the right stated reason -- these two fixtures are the entire evidence base
for the claim that the accuracy problem is capture rather than code, so a gate
that agreed with that claim by accident would be worthless.

The second is that it stays **cheap and unconditional**: structural checks that
need no Poppler, no Tesseract and no raster, because the whole point is to
answer in the seconds after upload rather than twenty minutes into a doomed job.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from statementbridge.ingest.classify import PageClass
from statementbridge.ingest.quality import (
    CONTRAST_FLOOR,
    DPI_FLOOR,
    DPI_TARGET,
    DocumentQuality,
    Finding,
    PageQuality,
    Verdict,
    inspect,
)

from .synthpdf import write_image_pdf, write_pdf


def codes(report: DocumentQuality) -> set[str]:
    return {finding.code for page in report.pages for finding in page.findings}


# --- the real fixtures: the failing case, in both its flavours ----------

@pytest.mark.fixtures
def test_gramin_is_rejected_as_bilevel_and_low_dpi(gramin_pdf):
    """The dot-matrix ledger fails on both counts, and says so separately.

    Bilevel and low resolution are different faults with different fixes -- one
    is the colour-mode setting, the other the resolution setting -- so reporting
    them as one finding would send the office to change only half of it.
    """
    report = inspect(gramin_pdf, render_sample=False)

    assert report.verdict is Verdict.REJECT
    assert "BILEVEL" in codes(report)
    assert "LOW_DPI" in codes(report)
    assert report.effective_dpi == 150

    first = report.pages[0]
    assert first.bits == 1
    assert first.codec == "CCITTFaxDecode"
    assert all(page.page_class is PageClass.SCANNED for page in report.pages)


@pytest.mark.fixtures
def test_gramin_dpi_survives_the_page_rotation(gramin_pdf):
    """Every Gramin sheet carries a /Rotate, alternating 90 and 270.

    Divided naively, the source pixels and the placed rectangle give 108 x 208
    DPI -- non-square pixels, which a scanner cannot produce. The gate resolves
    the pairing by self-consistency instead, and must land on a square 150.
    """
    report = inspect(gramin_pdf, render_sample=False)

    for page in report.pages:
        assert page.dpi_x == pytest.approx(150, abs=1)
        assert page.dpi_y == pytest.approx(150, abs=1)


@pytest.mark.fixtures
def test_sbi_is_rejected_for_resolution_and_flagged_for_colour(sbi_pdf):
    """The ruled table is 8-bit, so only the resolution is fatal.

    Colour is waste rather than damage -- it is what makes this file 17MB -- so
    it warns and does not reject on its own.
    """
    report = inspect(sbi_pdf, render_sample=False)

    assert report.verdict is Verdict.REJECT
    assert "LOW_DPI" in codes(report)
    assert "COLOUR_SCAN" in codes(report)
    assert "BILEVEL" not in codes(report)
    assert report.effective_dpi == 150
    assert report.pages[0].codec == "DCTDecode"


@pytest.mark.fixtures
def test_structural_stage_is_fast_and_needs_no_external_tools(sbi_pdf, monkeypatch):
    """60 pages and 17MB, with Poppler and Tesseract made unavailable.

    "Never let someone wait twenty minutes to learn the input was hopeless" is
    the requirement, so the stage that decides REJECT must not depend on the
    tooling that makes the job slow in the first place.
    """
    monkeypatch.setattr("shutil.which", lambda _name: None)

    started = time.perf_counter()
    report = inspect(sbi_pdf, render_sample=False)
    elapsed = time.perf_counter() - started

    assert report.verdict is Verdict.REJECT
    assert elapsed < 3.0, f"structural stage took {elapsed:.2f}s"


@pytest.mark.fixtures
@pytest.mark.slow
def test_sampled_render_measures_skew_without_changing_the_verdict(gramin_pdf):
    """Stage B samples three pages and adds detail, never a different answer.

    The last Gramin sheet went through the feeder visibly crooked; that is a
    real finding, but the file was already rejected on capture and must not
    become "rejected for skew".
    """
    report = inspect(gramin_pdf)

    assert len(report.sampled) == 3
    assert report.verdict is Verdict.REJECT
    measured = [page for page in report.pages if page.page_no in report.sampled]
    assert all(page.skew is not None for page in measured)
    assert all(page.contrast is not None for page in measured)
    # Bilevel capture is maximally "contrasty" -- which is exactly why contrast
    # cannot substitute for the bit-depth check.
    assert all(page.contrast > CONTRAST_FLOOR for page in measured)


# --- the passing case, which has to be synthesised ----------------------

def test_a_300_dpi_greyscale_scan_passes(tmp_path):
    report = inspect(write_image_pdf(tmp_path / "good.pdf", dpi=DPI_TARGET, bits=8))

    assert report.verdict is Verdict.PASS
    assert not codes(report)
    assert report.effective_dpi == pytest.approx(DPI_TARGET, abs=1)


def test_a_150_dpi_bilevel_scan_is_rejected(tmp_path):
    report = inspect(write_image_pdf(tmp_path / "fax.pdf", dpi=150, bits=1))

    assert report.verdict is Verdict.REJECT
    assert codes(report) >= {"BILEVEL", "LOW_DPI"}


def test_200_dpi_warns_rather_than_rejecting(tmp_path):
    """The firm has real client statements at 200 DPI.

    A gate that refused them would make the existing backlog unprocessable,
    which is a worse problem than the one it set out to solve.
    """
    report = inspect(write_image_pdf(tmp_path / "marginal.pdf", dpi=DPI_FLOOR, bits=8))

    assert report.verdict is Verdict.WARN
    assert "MARGINAL_DPI" in codes(report)
    assert "LOW_DPI" not in codes(report)


def test_the_remedy_names_the_setting_to_change(tmp_path):
    """A verdict the office cannot act on is not worth showing them."""
    report = inspect(write_image_pdf(tmp_path / "fax.pdf", dpi=150, bits=1))

    findings = [f for page in report.pages for f in page.findings]
    assert findings
    for finding in findings:
        assert finding.remedy, f"{finding.code} offers no remedy"
    remedies = " ".join(finding.remedy for finding in findings).lower()
    assert "greyscale" in remedies
    assert str(DPI_TARGET) in remedies


# --- digital pages are exempt -------------------------------------------

def test_a_text_layer_pdf_is_not_judged_on_dpi(tmp_path):
    """The export target is a digital Bandhan statement, not a scan.

    A text-layer statement has no scanner behind it and no resolution to have.
    Measuring one against a dots threshold would reject a perfect file, so the
    capture checks must not fire at all.
    """
    pdf = write_pdf(
        tmp_path / "digital.pdf",
        [[
            "BANDHAN BANK LIMITED            Statement of Account",
            "Account Number : 52230041965732            Page 1",
            "01-04-2025  UPI/CR/BISHAL NAG/YBL      15,400.00   1,15,400.00",
            "02-04-2025  NEFT CR-UTIB0001506-PHONEPE   8,750.00   1,24,150.00",
        ]],
    )

    report = inspect(pdf)

    assert report.verdict is Verdict.PASS
    assert not codes(report)
    assert report.effective_dpi is None
    assert all(page.page_class is PageClass.DIGITAL for page in report.pages)
    assert all(page.dpi is None for page in report.pages)


def test_the_summary_line_is_actionable(tmp_path):
    good = inspect(write_image_pdf(tmp_path / "good.pdf", dpi=DPI_TARGET, bits=8))
    fax = inspect(write_image_pdf(tmp_path / "fax.pdf", dpi=150, bits=1))

    assert "good enough" in good.summary
    assert "greyscale" in fax.summary.lower()


# --- aggregation --------------------------------------------------------

def _page(page_class: PageClass, *findings: Finding, page_no: int = 1) -> PageQuality:
    return PageQuality(page_no=page_no, page_class=page_class, findings=list(findings))


def test_the_document_verdict_is_the_worst_page():
    report = DocumentQuality(
        pdf=Path("x.pdf"),
        pages=[
            _page(PageClass.DIGITAL, page_no=1),
            _page(
                PageClass.SCANNED,
                Finding("MARGINAL_DPI", Verdict.WARN, "", ""),
                page_no=2,
            ),
            _page(PageClass.SCANNED, Finding("BILEVEL", Verdict.REJECT, "", ""), page_no=3),
        ],
    )

    assert report.verdict is Verdict.REJECT
    assert report.mixed
    assert [page_no for page_no, _ in report.findings_of("BILEVEL")] == [3]


def test_a_clean_document_has_no_findings():
    report = DocumentQuality(
        pdf=Path("x.pdf"),
        pages=[_page(PageClass.SCANNED, page_no=1)],
    )

    assert report.verdict is Verdict.PASS
    assert not report.mixed
