"""PaddleOCR implementation, for comparison against Tesseract.

Kept behind the same Protocol so switching engines is a constructor argument.
Imported lazily: PaddlePaddle is a large dependency and the application must
start on a machine where it was never installed.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .engine import OcrLine
from .lines import Word, group_into_rows


class PaddleEngine:
    name = "paddleocr"

    def __init__(self, *, lang: str = "en") -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:  # pragma: no cover - depends on install
            raise RuntimeError(
                "PaddleOCR is not installed. Install the optional extra: "
                "pip install 'statementbridge[paddle]'"
            ) from error
        self._ocr = self._construct(PaddleOCR, lang)

    @staticmethod
    def _construct(factory, lang: str):
        # The constructor signature moved between 2.x and 3.x; try the modern
        # form first and fall back rather than pinning the whole application to
        # one PaddleOCR release.
        for kwargs in (
            {"lang": lang, "use_doc_orientation_classify": False,
             "use_doc_unwarping": False, "use_textline_orientation": False},
            {"lang": lang, "use_angle_cls": False, "show_log": False},
            {"lang": lang},
        ):
            try:
                return factory(**kwargs)
            except TypeError:
                continue
        return factory()

    def read_words(self, image: np.ndarray, *, whitelist: str | None = None) -> list[Word]:
        raw = self._predict(image)
        words: list[Word] = []
        for box, text, confidence in raw:
            if not text or not text.strip():
                continue
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            left, right = int(min(xs)), int(max(xs))
            top, bottom = int(min(ys)), int(max(ys))
            words.append(
                Word(
                    text=text.strip(),
                    left=left,
                    top=top,
                    width=max(right - left, 1),
                    height=max(bottom - top, 1),
                    confidence=float(confidence) * 100.0,
                )
            )
        return words

    def _predict(self, image: np.ndarray):
        """Normalise the several result shapes PaddleOCR has shipped."""
        if hasattr(self._ocr, "predict"):
            results = self._ocr.predict(image)
            out = []
            for page in results or []:
                data = page if isinstance(page, dict) else getattr(page, "res", {}) or {}
                polys = data.get("rec_polys") or data.get("dt_polys") or []
                texts = data.get("rec_texts") or []
                scores = data.get("rec_scores") or []
                for index, text in enumerate(texts):
                    box = polys[index] if index < len(polys) else [[0, 0]] * 4
                    score = scores[index] if index < len(scores) else 0.0
                    out.append((box, text, score))
            if out:
                return out
        results = self._ocr.ocr(image)
        out = []
        for page in results or []:
            for entry in page or []:
                box, (text, score) = entry[0], entry[1]
                out.append((box, text, score))
        return out

    def read_lines(self, image: np.ndarray) -> Sequence[OcrLine]:
        words = self.read_words(image)
        return group_into_rows(words) if words else []

    def read_region(self, image: np.ndarray, *, whitelist: str | None = None) -> str:
        # PaddleOCR has no alphabet restriction, which is precisely the lever
        # that matters most on these scans -- see ocr/columns.py.
        return " ".join(word.text for word in self.read_words(image))
