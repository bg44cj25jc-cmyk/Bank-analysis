"""Read page one, so a human has something to confirm rather than to type.

This is the step that cannot happen in the upload request. Identifying the bank
means matching phrases against the statement's own text, and a scanned statement
has no text until a page has been through OCR -- six seconds or so on the NAS,
which does not belong in an HTTP handler. So it happens here, once, on one page.

What comes back is a proposal, never a decision: the profile, the account number
and the holder as they were read, for the desktop's confirm-header screen to
accept or correct. The holder name in particular goes on to decide which
transfers count as the client's own, so a guess accepted silently would be a
misclassification nobody could later explain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..ingest import render
from ..ingest.classify import PageClass, classify_pages
from ..ingest.quality import DocumentQuality, inspect
from ..parse.profiles import gramin_cc, sbi_current  # noqa: F401  (registers profiles)
from ..parse.profiles.base import BankProfile, detect_profile, get_profile


@dataclass(slots=True)
class HeaderFindings:
    page_count: int
    text: str = ""
    profile_key: str | None = None
    account_no: str | None = None
    holder: str | None = None
    quality: DocumentQuality | None = None


def first_page_text(pdf: Path, *, dpi: int = render.DEFAULT_DPI) -> tuple[str, int, PageClass]:
    """The text of page one, however it has to be obtained."""
    import pdfplumber

    with pdfplumber.open(str(pdf)) as document:
        page_count = len(document.pages)
        if not page_count:
            return "", 0, PageClass.SCANNED
        page_class = classify_pages(document).pages[0]
        if page_class is PageClass.DIGITAL:
            return (document.pages[0].extract_text() or ""), page_count, page_class

    # A scan: one page through the recogniser is enough to name the bank.
    import cv2

    from ..ocr.tesseract import TesseractEngine

    images = render.render(pdf, dpi=dpi, first=1, last=1)
    if not images:
        return "", page_count, page_class
    raster = cv2.imread(str(images[0].path), cv2.IMREAD_GRAYSCALE)
    if raster is None:
        return "", page_count, page_class
    lines = TesseractEngine().read_lines(raster)
    return "\n".join(line.text for line in lines), page_count, page_class


def _match(pattern: str | None, text: str) -> str | None:
    if not pattern:
        return None
    found = re.search(pattern, text, re.IGNORECASE)
    if not found:
        return None
    value = (found.group(1) if found.groups() else found.group(0)).strip()
    return re.sub(r"\s{2,}", " ", value) or None


def read(pdf: Path, *, profile_key: str | None = None) -> HeaderFindings:
    """Grade the capture properly, then propose what the header says."""
    # The upload gate ran structure only. Now that seconds are affordable, the
    # sampled render adds skew and ink separation to what it already found.
    quality = inspect(pdf)

    text, page_count, _ = first_page_text(pdf)
    findings = HeaderFindings(page_count=page_count, text=text, quality=quality)

    profile: BankProfile | None = None
    if profile_key:
        try:
            profile = get_profile(profile_key)
        except KeyError:
            profile = None
    if profile is None:
        profile = detect_profile(text)

    if profile is not None:
        findings.profile_key = profile.key
        findings.account_no = _match(profile.account_no_pattern, text)
        findings.holder = _match(profile.holder_pattern, text)

    return findings
