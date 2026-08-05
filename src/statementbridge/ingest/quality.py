"""Judge a statement's capture quality *before* anything expensive happens.

The measured cause of Phase 1 missing its accuracy bar is not the extraction
code, it is the capture: both sample statements are 150 DPI, and the Gramin
ledger is 1-bit bilevel on top of that -- the greyscale edge information the
recogniser was trained on was discarded by the scanner, before the file was
ever saved. No amount of rendering, conditioning or repair puts it back.

So the fix belongs at the scanner, and this module is what says so, in the two
seconds after upload rather than twenty minutes into a job that was never going
to reconcile. Every finding names the specific setting to change.

**Two stages, cheapest first.**

* Stage A reads the PDF's object structure -- image dimensions against their
  placement rectangle, bit depth, colour space, codec. It rasterises nothing,
  needs no Poppler and no Tesseract, and settles the two faults that actually
  matter (too few dots, and bilevel capture) on a sixty-page file in well under
  a second.
* Stage B renders a *sample* of pages -- three, not sixty -- for the two things
  structure cannot show: how straight the sheet went through the feeder, and
  whether the ink and paper are still separable. It degrades to "not measured"
  when Poppler is absent rather than failing the document.

**Digital pages are exempt from the capture checks.** A text-layer statement has
no DPI, no bit depth and no scanner behind it, and judging one against a dots
threshold would reject a perfect file. Classification runs first, per page, and
the capture checks apply only to pages that came from a scanner -- so a digital
export with one rescanned sheet stapled into it is reported as exactly that.

**This module measures; it does not set policy.** It returns a verdict and the
evidence for it. Whether a REJECT blocks an upload outright, or is overridable
the way a failed reconciliation is, belongs to the caller -- the firm has a
backlog of files already scanned at 150 DPI, and a gate that silently made them
unprocessable would be worse than the problem it solves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from statistics import median

from .classify import DocumentClass, PageClass, classify_pages

#: Below this a scan is rejected: there are too few dots on the character for
#: recognition to be recoverable by any downstream means.
DPI_FLOOR = 200

#: The target. At or above this a scan passes on resolution.
DPI_TARGET = 300

#: Between FLOOR and TARGET the file is processed but flagged. The firm has
#: real client statements at 200 DPI, so this band must not be fatal.
DPI_MARGINAL = (DPI_FLOOR, DPI_TARGET)

#: Degrees of skew tolerated before the sheet is called crooked. Deliberately
#: loose, because the estimator behind it is known to be biased by full-width
#: rules -- see :func:`preprocess.measure_skew`.
SKEW_LIMIT = 1.5

#: Otsu-separated ink/paper mean difference, as a fraction of full scale, below
#: which a page is called washed out.
#:
#: **Provisional.** Unlike the DPI thresholds -- which come from the measured
#: failure of the fixtures -- this number has not yet been calibrated against a
#: known-good rescan, because no rescan exists yet. Recalibrate it when one
#: arrives; until then it is set loose enough to catch only gross cases.
CONTRAST_FLOOR = 0.35

#: Pages rendered in stage B. Three is enough to catch a feeder that is
#: consistently crooked or a scanner with auto-contrast left on, and cheap
#: enough that the gate still answers in seconds on a sixty-page file.
SAMPLE_PAGES = 3

#: Stage B renders for measurement only, so it renders small. Skew and contrast
#: do not need the resolution that recognition does.
SAMPLE_DPI = 150


class Verdict(str, Enum):
    """Ordered worst-last, so ``max`` over a page's findings is its verdict."""

    PASS = "PASS"
    WARN = "WARN"
    REJECT = "REJECT"

    @property
    def rank(self) -> int:
        return {"PASS": 0, "WARN": 1, "REJECT": 2}[self.value]


def _worst(verdicts) -> Verdict:
    return max(verdicts, key=lambda verdict: verdict.rank, default=Verdict.PASS)


@dataclass(slots=True)
class Finding:
    """One thing wrong with one page, and the setting that would fix it."""

    code: str
    verdict: Verdict
    detail: str
    remedy: str = ""


@dataclass(slots=True)
class PageQuality:
    """What one page is, and what is wrong with it."""

    page_no: int
    page_class: PageClass
    dpi_x: float | None = None
    dpi_y: float | None = None
    bits: int | None = None
    colorspace: str | None = None
    codec: str | None = None
    skew: float | None = None
    contrast: float | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> Verdict:
        return _worst(finding.verdict for finding in self.findings)

    @property
    def dpi(self) -> float | None:
        """The page's effective resolution, as the lower of the two axes."""
        if self.dpi_x is None or self.dpi_y is None:
            return None
        return min(self.dpi_x, self.dpi_y)

    @property
    def scanned(self) -> bool:
        return self.page_class is PageClass.SCANNED


@dataclass(slots=True)
class DocumentQuality:
    """The whole file's verdict, and the evidence under it."""

    pdf: Path
    pages: list[PageQuality] = field(default_factory=list)
    sampled: tuple[int, ...] = ()
    stage_b_note: str = ""

    @property
    def verdict(self) -> Verdict:
        return _worst(page.verdict for page in self.pages)

    @property
    def scanned_pages(self) -> list[PageQuality]:
        return [page for page in self.pages if page.scanned]

    @property
    def mixed(self) -> bool:
        return len({page.page_class for page in self.pages}) > 1

    @property
    def effective_dpi(self) -> float | None:
        """Median resolution across scanned pages; None for a digital file."""
        values = [page.dpi for page in self.scanned_pages if page.dpi is not None]
        return median(values) if values else None

    def findings_of(self, code: str) -> list[tuple[int, Finding]]:
        return [
            (page.page_no, finding)
            for page in self.pages
            for finding in page.findings
            if finding.code == code
        ]

    @property
    def summary(self) -> str:
        """One line a queue screen can show without expanding anything."""
        if self.verdict is Verdict.PASS:
            return "Capture quality is good enough to process."
        codes = {finding.code for page in self.pages for finding in page.findings}
        if "BILEVEL" in codes:
            return "Scanned in black-and-white. Rescan in greyscale at 300 DPI."
        if "LOW_DPI" in codes:
            dpi = self.effective_dpi
            shown = f"{dpi:.0f} DPI" if dpi else "too low a resolution"
            return f"Scanned at {shown}. Rescan at 300 DPI greyscale."
        if "MARGINAL_DPI" in codes:
            return "Below the 300 DPI target — expect more rows to need checking."
        return "Capture quality is usable but flawed; see the findings."

    def render(self) -> str:
        """Operator-facing report, in the style of ``statementbridge audit``."""
        lines: list[str] = []
        add = lines.append

        add(f"StatementBridge quality gate — {self.pdf.name}")
        add("=" * 64)
        add(f"verdict               {self.verdict.value}")
        add(f"                      {self.summary}")
        add("")
        add("PAGES")
        scanned = len(self.scanned_pages)
        digital = len(self.pages) - scanned
        add(f"  pages in PDF        {len(self.pages)}")
        add(f"  scanned / digital   {scanned} / {digital}")
        if self.mixed:
            add("  -> mixed document: capture checks applied to scanned pages only.")
        dpi = self.effective_dpi
        if dpi is not None:
            add(f"  effective DPI       {dpi:.0f} (median over scanned pages)")
        elif scanned == 0:
            add("  effective DPI       n/a — text-layer PDF, nothing was scanned")

        if scanned:
            first = self.scanned_pages[0]
            add("")
            add("CAPTURE")
            add(f"  bit depth           {first.bits if first.bits else '?'}"
                f"{' (bilevel)' if first.bits == 1 else ''}")
            add(f"  colour space        {first.colorspace or '?'}")
            add(f"  codec               {first.codec or '?'}")
            if self.sampled:
                add("  sampled pages       " + ", ".join(str(p) for p in self.sampled))
                for page in self.pages:
                    if page.page_no not in self.sampled or page.skew is None:
                        continue
                    measured = f"    page {page.page_no:<3} skew {page.skew:+.2f}°"
                    if page.contrast is not None:
                        measured += f"   contrast {page.contrast:.2f}"
                    add(measured)
            elif self.stage_b_note:
                add(f"  sampled pages       none — {self.stage_b_note}")

        grouped: dict[str, list[tuple[int, Finding]]] = {}
        for page in self.pages:
            for finding in page.findings:
                grouped.setdefault(finding.code, []).append((page.page_no, finding))
        if grouped:
            add("")
            add("FINDINGS")
            for code, entries in grouped.items():
                page_nos = [str(page_no) for page_no, _ in entries]
                shown = ", ".join(page_nos[:6])
                if len(page_nos) > 6:
                    shown += f", … (+{len(page_nos) - 6} more)"
                finding = entries[0][1]
                add(f"  [{finding.verdict.value}] {code}  pages {shown}")
                add(f"        {finding.detail}")
                if finding.remedy:
                    add(f"     fix: {finding.remedy}")
        else:
            add("")
            add("FINDINGS")
            add("  none")

        return "\n".join(lines)


# --- stage A: structure only, no rendering ------------------------------


def _effective_dpi(image: dict) -> tuple[float | None, float | None]:
    """Resolution of one placed image, in dots per inch of printed page.

    The source pixel count is known exactly and so is the rectangle it is drawn
    into, so the resolution is just their ratio -- except that a page carrying a
    ``/Rotate`` swaps which source axis maps to which placed axis, and the
    Gramin fixture alternates 90 and 270 between sheets.

    Rather than reason about rotation semantics, both pairings are tried and the
    self-consistent one wins. Scanner pixels are square, so the correct pairing
    lands on a near-equal DPI pair and the wrong one does not: on these fixtures
    the right answer is exact to a tenth of a dot and the wrong one is out by
    48%, which is not a margin that needs a tolerance argument.
    """
    source = image.get("srcsize")
    width_pt, height_pt = image.get("width"), image.get("height")
    if not source or not width_pt or not height_pt:
        return None, None

    width_in, height_in = width_pt / 72.0, height_pt / 72.0
    if width_in <= 0 or height_in <= 0:
        return None, None

    best: tuple[float, float, float] | None = None
    for across, down in ((source[0], source[1]), (source[1], source[0])):
        dpi_x, dpi_y = across / width_in, down / height_in
        if dpi_x <= 0 or dpi_y <= 0:
            continue
        disagreement = abs(dpi_x - dpi_y) / max(dpi_x, dpi_y)
        if best is None or disagreement < best[0]:
            best = (disagreement, dpi_x, dpi_y)
    if best is None:
        return None, None
    return round(best[1], 1), round(best[2], 1)


def _name_of(value) -> str | None:
    """Flatten pdfminer's name wrappers into a plain string.

    Colour spaces arrive as bare names (``/DeviceRGB``) or as a list whose head
    is the family and whose tail is a parameter -- ``[/ICCBased, <stream>]``.
    Only the names are of interest; letting a stream's repr through would put
    an object address in an operator-facing report.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            name = _name_of(item)
            if name:
                return name
        return None
    text = getattr(value, "name", None)
    if text:
        return str(text)
    return str(value) if isinstance(value, (str, bytes)) else None


def _codec_of(image: dict) -> str | None:
    stream = image.get("stream")
    attrs = getattr(stream, "attrs", None)
    if not attrs:
        return None
    return _name_of(attrs.get("Filter"))


def _inspect_page(page, page_class: PageClass) -> PageQuality:
    quality = PageQuality(page_no=page.page_number, page_class=page_class)
    if page_class is PageClass.DIGITAL:
        # A text layer has no scanner behind it. Nothing here applies.
        return quality

    images = list(page.images)
    if not images:
        quality.findings.append(
            Finding(
                "NO_IMAGE",
                Verdict.WARN,
                "page has neither a text layer nor a scanned image",
                "Check the page is not blank, and that the PDF is not damaged.",
            )
        )
        return quality

    # The page image, not a logo or a signature crop.
    largest = max(images, key=lambda item: (item.get("srcsize") or (0, 0))[0]
                  * (item.get("srcsize") or (0, 0))[1])
    quality.dpi_x, quality.dpi_y = _effective_dpi(largest)
    quality.bits = largest.get("bits")
    quality.colorspace = _name_of(largest.get("colorspace"))
    quality.codec = _codec_of(largest)

    _judge_capture(quality)
    return quality


def _judge_capture(quality: PageQuality) -> None:
    """Apply the capture thresholds to one already-measured scanned page."""
    if quality.bits == 1:
        quality.findings.append(
            Finding(
                "BILEVEL",
                Verdict.REJECT,
                "captured as 1-bit black-and-white, so every grey edge the "
                "recogniser relies on was discarded at the scanner",
                "Set the scanner's colour mode to Greyscale. A 'Text', 'Fax' or "
                "'Black & White' preset produces this and cannot be undone later.",
            )
        )

    dpi = quality.dpi
    if dpi is None:
        quality.findings.append(
            Finding(
                "NO_DPI",
                Verdict.WARN,
                "resolution could not be determined from the page structure",
                "",
            )
        )
    elif dpi < DPI_FLOOR:
        quality.findings.append(
            Finding(
                "LOW_DPI",
                Verdict.REJECT,
                f"scanned at {dpi:.0f} DPI, below the {DPI_FLOOR} DPI floor",
                f"Set the scanner resolution to {DPI_TARGET} DPI "
                "(400 for dot-matrix or faint print).",
            )
        )
    elif dpi < DPI_TARGET:
        quality.findings.append(
            Finding(
                "MARGINAL_DPI",
                Verdict.WARN,
                f"scanned at {dpi:.0f} DPI, under the {DPI_TARGET} DPI target",
                f"Usable, but expect more rows to need checking. "
                f"{DPI_TARGET} DPI is the setting to standardise on.",
            )
        )

    # Colour is not an accuracy problem by itself, but it is always waste, and
    # a lossy codec on top of it costs real detail the pipeline then has to
    # fight. Worth one line so the office stops producing 17MB statements.
    colour = (quality.colorspace or "").upper()
    if quality.bits and quality.bits > 1 and "GRAY" not in colour and colour:
        lossy = (quality.codec or "").upper().startswith("DCT")
        quality.findings.append(
            Finding(
                "COLOUR_SCAN",
                Verdict.WARN,
                f"captured in colour ({quality.colorspace})"
                + (", JPEG-compressed" if lossy else ""),
                "Scan in Greyscale. Colour triples the file size for no gain, and "
                "JPEG softens the digit edges.",
            )
        )


# --- stage B: sampled render --------------------------------------------


def _sample_indices(pages: list[PageQuality], limit: int = SAMPLE_PAGES) -> list[int]:
    """Spread the sample across the scanned pages: first, middle, last."""
    scanned = [page.page_no for page in pages if page.scanned]
    if not scanned:
        return []
    if len(scanned) <= limit:
        return scanned
    step = (len(scanned) - 1) / (limit - 1) if limit > 1 else 0
    picked = {scanned[round(index * step)] for index in range(limit)}
    return sorted(picked)


def _measure_rendered(quality: PageQuality, image) -> None:
    """Skew and ink/paper separation for one rendered page."""
    import cv2
    import numpy as np

    from . import preprocess

    angle = preprocess.measure_skew(image)
    if angle is not None:
        quality.skew = round(angle, 2)
        if abs(angle) > SKEW_LIMIT:
            quality.findings.append(
                Finding(
                    "SKEWED",
                    Verdict.WARN,
                    f"the page sits {angle:+.1f}° off square",
                    "Square the stack in the feeder and use the paper guides. "
                    "Straightening it afterwards costs more detail than it recovers.",
                )
            )

    grey = preprocess.to_grey(image)
    threshold, _ = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = grey[grey <= threshold]
    paper = grey[grey > threshold]
    if ink.size and paper.size:
        separation = float(np.mean(paper) - np.mean(ink)) / 255.0
        quality.contrast = round(separation, 3)
        if separation < CONTRAST_FLOOR:
            quality.findings.append(
                Finding(
                    "LOW_CONTRAST",
                    Verdict.WARN,
                    f"ink and paper are only {separation:.2f} apart on a 0-1 scale",
                    "Turn auto-contrast, auto-exposure and background removal off, "
                    "and turn descreening off. They flatten faint print.",
                )
            )


def _run_stage_b(pdf: Path, report: DocumentQuality) -> None:
    """Render a sample and measure it. Never fatal: notes why it was skipped."""
    import shutil

    wanted = _sample_indices(report.pages)
    if not wanted:
        return
    if shutil.which("pdftoppm") is None:
        report.stage_b_note = "Poppler not installed, so skew and contrast were not measured"
        return

    try:
        import cv2

        from . import render
    except ImportError as error:  # pragma: no cover - environment-specific
        report.stage_b_note = f"skew and contrast were not measured ({error})"
        return

    by_page = {page.page_no: page for page in report.pages}
    measured: list[int] = []
    for page_no in wanted:
        try:
            images = render.render(pdf, dpi=SAMPLE_DPI, first=page_no, last=page_no)
        except Exception as error:  # pragma: no cover - depends on the file
            report.stage_b_note = f"page {page_no} could not be rendered ({error})"
            continue
        if not images:
            continue
        image = cv2.imread(str(images[0].path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue
        _measure_rendered(by_page[page_no], image)
        measured.append(page_no)

    report.sampled = tuple(measured)


# --- entry point ---------------------------------------------------------


def inspect(pdf: Path, *, render_sample: bool = True) -> DocumentQuality:
    """Grade a statement's capture quality.

    Set ``render_sample=False`` for the structural checks alone: they need no
    Poppler, touch no raster, and already decide the two faults that matter.
    """
    import pdfplumber

    pdf = Path(pdf)
    report = DocumentQuality(pdf=pdf)
    with pdfplumber.open(str(pdf)) as document:
        classification: DocumentClass = classify_pages(document)
        for index, page in enumerate(document.pages):
            page_class = (
                classification.pages[index]
                if index < len(classification.pages)
                else PageClass.SCANNED
            )
            report.pages.append(_inspect_page(page, page_class))

    if render_sample:
        _run_stage_b(pdf, report)
    return report
