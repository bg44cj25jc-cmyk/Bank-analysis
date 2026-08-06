"""Locate the sample PDFs, and skip cleanly when they are absent.

The fixtures live in the Ba-resources repository, not here: they are 18MB of
client bank statements and do not belong in the application repo. Tests that
need them are marked ``fixtures`` and skip when the directory cannot be found,
so the suite stays green on a machine that has only checked out the code.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

GRAMIN = "fixture_gramin_cc_scanned.pdf.pdf"
SBI = "fixture_sbi_current_clean.pdf.pdf"
#: The client's finished migration workbook. Not a statement: 236 rows a person
#: categorised by hand, which is the only labelled data the rules engine has.
TALLY_WORKBOOK = "Ajoy Nag FY2025-26 Tally.xlsx"

#: Searched in order. SB_FIXTURE_DIR wins, then a sibling checkout.
CANDIDATES = (
    Path(__file__).resolve().parents[2] / "Ba-resources",
    Path.home() / "Ba-resources",
)


def _locate() -> Path | None:
    override = os.environ.get("SB_FIXTURE_DIR")
    if override:
        path = Path(override)
        return path if (path / GRAMIN).exists() else None
    for candidate in CANDIDATES:
        if (candidate / GRAMIN).exists():
            return candidate
    return None


@pytest.fixture(scope="session")
def fixture_dir() -> Path | None:
    return _locate()


@pytest.fixture(scope="session")
def gramin_pdf(fixture_dir) -> Path:
    if fixture_dir is None or not (fixture_dir / GRAMIN).exists():
        pytest.skip("Gramin fixture not available (set SB_FIXTURE_DIR)")
    return fixture_dir / GRAMIN


@pytest.fixture(scope="session")
def sbi_pdf(fixture_dir) -> Path:
    if fixture_dir is None or not (fixture_dir / SBI).exists():
        pytest.skip("SBI fixture not available (set SB_FIXTURE_DIR)")
    return fixture_dir / SBI


@pytest.fixture(scope="session")
def tally_workbook(fixture_dir) -> Path:
    if fixture_dir is None or not (fixture_dir / TALLY_WORKBOOK).exists():
        pytest.skip("client Tally workbook not available (set SB_FIXTURE_DIR)")
    return fixture_dir / TALLY_WORKBOOK


@pytest.fixture(scope="session")
def require_ocr() -> None:
    for binary in ("pdftoppm", "tesseract"):
        if shutil.which(binary) is None:
            pytest.skip(f"{binary} not installed")
