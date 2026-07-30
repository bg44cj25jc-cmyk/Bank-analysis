"""Turn PDF pages into images fit for OCR.

Both fixtures are 150 DPI scans, which is half what Tesseract's models expect.
Upscaling adds no information, but it does materially help recognition because
the engine was trained near 300 DPI, so pages are rendered at 300 and the
scaling is done once, by Poppler, rather than compounding a second resample on
top of a first.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DPI = 300


@dataclass(slots=True)
class PageImage:
    page_no: int
    path: Path


def _require(binary: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise RuntimeError(
            f"{binary} not found. Install Poppler "
            f"(Windows: the poppler-utils build shipped with the app; "
            f"Linux: apt-get install poppler-utils)."
        )
    return found


def page_count(pdf: Path) -> int:
    output = subprocess.run(
        [_require("pdfinfo"), str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"^Pages:\s+(\d+)", output, re.MULTILINE)
    if not match:
        raise RuntimeError(f"could not read page count from {pdf}")
    return int(match.group(1))


def render(
    pdf: Path,
    *,
    dpi: int = DEFAULT_DPI,
    first: int | None = None,
    last: int | None = None,
    outdir: Path | None = None,
) -> list[PageImage]:
    """Rasterise a page range to greyscale PNGs."""
    target = Path(outdir) if outdir else Path(tempfile.mkdtemp(prefix="sbridge-"))
    target.mkdir(parents=True, exist_ok=True)
    prefix = target / "page"

    command = [_require("pdftoppm"), "-r", str(dpi), "-gray", "-png"]
    if first is not None:
        command += ["-f", str(first)]
    if last is not None:
        command += ["-l", str(last)]
    command += [str(pdf), str(prefix)]
    subprocess.run(command, check=True, capture_output=True)

    images: list[PageImage] = []
    for path in sorted(target.glob("page-*.png")):
        match = re.search(r"page-(\d+)\.png$", path.name)
        if match:
            images.append(PageImage(page_no=int(match.group(1)), path=path))
    return images
