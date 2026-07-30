"""Compare OCR engines on a real statement page.

Scored on the only metric that decides whether this application works: the
proportion of consecutive rows whose printed amount agrees, to the paisa, with
the movement in the running balance. Character accuracy is a proxy; row
agreement is the thing itself, because a single wrong digit anywhere in a row
breaks that row's reconciliation regardless of how many other characters were
correct.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2

from ..money import MONEY_TOKEN, q2
from ..parse.lineparse import build_txn
from ..parse.profiles.base import BankProfile
from ..parse.rowkind import classify_line


@dataclass(slots=True)
class EngineScore:
    engine: str
    rows: int = 0
    agreeing: int = 0
    comparisons: int = 0
    money_tokens: int = 0
    seconds: float = 0.0

    @property
    def agreement(self) -> float:
        return (100.0 * self.agreeing / self.comparisons) if self.comparisons else 0.0

    def line(self) -> str:
        return (
            f"  {self.engine:12} rows={self.rows:4}  money={self.money_tokens:4}  "
            f"row agreement={self.agreement:5.1f}%  {self.seconds:6.1f}s"
        )


def score_lines(lines, profile: BankProfile) -> EngineScore:
    score = EngineScore(engine="")
    rows = []
    for index, line in enumerate(lines):
        score.money_tokens += len(MONEY_TOKEN.findall(line.text))
        classification = classify_line(
            line.text, page_no=1, source_row=index, extra_patterns=profile.patterns()
        )
        if not classification.kind.is_transaction:
            continue
        row = build_txn(
            line.text, page_no=1, source_row=index, is_overdraft=profile.is_overdraft
        )
        if row is not None:
            rows.append(row)
    score.rows = len(rows)
    for previous, current in zip(rows, rows[1:]):
        score.comparisons += 1
        if current.balance is None or previous.balance is None:
            continue
        if abs(q2(current.balance - previous.balance)) == q2(abs(current.printed_amount)):
            score.agreeing += 1
    return score


def run(
    pdf: Path,
    profile: BankProfile,
    *,
    pages: list[int],
    dpi: int = 300,
) -> list[EngineScore]:
    from ..ingest import render
    from ..ocr.tesseract import TesseractEngine
    from ..parse.scanned import _read_image

    engines = [("tesseract", TesseractEngine())]
    try:
        from ..ocr.paddle import PaddleEngine

        engines.append(("paddleocr", PaddleEngine()))
    except Exception as error:  # pragma: no cover - optional dependency
        print(f"  (paddleocr unavailable: {error})")

    scores: list[EngineScore] = []
    for name, engine in engines:
        total = EngineScore(engine=name)
        start = time.time()
        for page in pages:
            images = render.render(pdf, dpi=dpi, first=page, last=page)
            if not images:
                continue
            image = cv2.imread(str(images[0].path), cv2.IMREAD_GRAYSCALE)
            _, lines = _read_image(image, profile, engine)
            page_score = score_lines(lines, profile)
            total.rows += page_score.rows
            total.agreeing += page_score.agreeing
            total.comparisons += page_score.comparisons
            total.money_tokens += page_score.money_tokens
        total.seconds = time.time() - start
        scores.append(total)
    return scores
