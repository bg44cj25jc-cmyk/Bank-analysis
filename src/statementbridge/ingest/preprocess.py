"""Image conditioning, chosen per scan class.

The two fixtures need opposite treatment, which is why this is profile-driven
rather than a single fixed pipeline:

* The Gramin ledger is a 1-bit CCITT G4 dot-matrix scan. It is already binary,
  so re-thresholding it achieves nothing; what helps is a morphological close
  that bridges the gaps between the printer's dots so strokes become
  continuous and the character shapes match what Tesseract expects.
* The SBI statement is a JPEG with a shaded table background and printed rules.
  A global threshold reads the shading as ink; Sauvola's local threshold does
  not. The long rules are removed separately, because Tesseract otherwise reads
  them as a column of pipe characters that fragments every line.
"""

from __future__ import annotations

import cv2
import numpy as np


def to_grey(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


#: Below this the page is straight enough that rotating it would cost more in
#: resampling blur than it recovers.
SKEW_FLOOR = 0.5


def measure_skew(image: np.ndarray) -> float | None:
    """Dominant ink angle in degrees, or None when the page carries no ink.

    Separated out from :func:`deskew` so the upload quality gate can report an
    angle without rotating anything.

    **Advisory only.** This estimator keys on dominant ink orientation, which
    the full-width rules and right-hand user-id block of these ledgers bias --
    see :func:`prepare` for the page where it chose an angle that destroyed
    extraction outright. It is good enough to flag a sheet that went through the
    feeder crooked; it is not good enough to act on unsupervised.
    """
    grey = to_grey(image)
    inverted = cv2.bitwise_not(grey)
    _, binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    coords = cv2.findNonZero(binary)
    if coords is None:
        return None
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle += 90
    elif angle > 45:
        angle -= 90
    return float(angle)


def deskew(image: np.ndarray, *, limit: float = 5.0, floor: float = SKEW_FLOOR) -> np.ndarray:
    """Straighten a scan using the dominant text angle.

    Continuous stationery fed through a flatbed is rarely square, and a degree
    or two of skew smears a row's characters across two scan lines.
    """
    grey = to_grey(image)
    angle = measure_skew(grey)
    if angle is None:
        return image
    if abs(angle) < floor or abs(angle) > limit:
        return image
    height, width = grey.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        image, matrix, (width, height),
        flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE,
    )


def sauvola(grey: np.ndarray, *, window: int = 41, k: float = 0.2, r: float = 128.0) -> np.ndarray:
    """Local adaptive threshold: survives uneven shading a global one does not."""
    if window % 2 == 0:
        window += 1
    values = grey.astype(np.float32)
    mean = cv2.boxFilter(values, cv2.CV_32F, (window, window))
    sq_mean = cv2.boxFilter(values * values, cv2.CV_32F, (window, window))
    std = cv2.sqrt(cv2.max(sq_mean - mean * mean, 0))
    threshold = mean * (1 + k * ((std / r) - 1))
    return np.where(values > threshold, 255, 0).astype(np.uint8)


def close_dots(binary: np.ndarray, *, size: int = 2) -> np.ndarray:
    """Join dot-matrix dots into continuous strokes."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
    return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)


def remove_rules(binary: np.ndarray, *, length: int = 60) -> np.ndarray:
    """Strip long horizontal and vertical table rules.

    Tesseract reads a printed rule as a run of pipes, which breaks the line into
    fragments and drags punctuation into the narration.
    """
    ink = cv2.bitwise_not(binary)
    for kernel in (
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)),
        cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)),
    ):
        rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
        ink = cv2.subtract(ink, rules)
    return cv2.bitwise_not(ink)


def prepare(image: np.ndarray, *, dot_matrix: bool, strip_rules: bool = False) -> np.ndarray:
    """Full conditioning pass for one page.

    The dot-matrix path deliberately does almost nothing. Measured on the
    Gramin fixture, every binarisation variant scored *worse* than the raw
    greyscale render -- well-formed money tokens 78 with Otsu-plus-close
    against 81 raw, legible balances 24 against 34. The source is already
    bilevel, so rasterising it at 300 DPI hands Tesseract a clean antialiased
    upscale, and re-thresholding that only discards the greyscale edge
    information the recogniser was trained to use. Only a genuinely skewed
    page is touched.

    The ruled-table path is the opposite case: shading defeats a global
    threshold, so Sauvola earns its cost there (money tokens 18 raw against 41
    conditioned on the SBI fixture).
    """
    grey = to_grey(image)
    if dot_matrix:
        # Deliberately untouched, including no deskew. The angle estimator keys
        # on the dominant ink orientation, and these ledgers carry full-width
        # rules and a right-hand block of user-id columns that bias it; on page
        # 3 of the Gramin fixture it chose an angle that dropped row agreement
        # from 38% to 0% and lost three rows outright. Straightening is
        # available via deskew() for genuinely skewed input, but it is not
        # applied blind.
        return grey
    binary = sauvola(deskew(grey))
    if strip_rules:
        binary = remove_rules(binary)
    return binary
