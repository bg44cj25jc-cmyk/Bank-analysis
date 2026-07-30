"""Background parsing.

A 24-page scan takes roughly two minutes of OCR. Doing that on the GUI thread
would freeze the window for the whole run, which on a shared office machine
reads as a crash and gets the app force-quit. The worker owns the pipeline call
and reports progress through the callback ``parse_pdf`` already accepts.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ...ingest.classify import PageClass, classify
from ...balance.repair import settle
from ...money import signed_from_drcr
from ...parse import scanned
from ...parse.frame import ParseResult
from ...parse.profiles.base import BankProfile


class ParseWorker(QObject):
    """Runs one statement through the Phase 1 pipeline off the GUI thread."""

    progress = Signal(int, int)                 # page, total
    finished = Signal(object, object, object)   # ParseResult, ChainReport, [Diagnosis]
    failed = Signal(str)

    def __init__(
        self,
        pdf: Path,
        profile: BankProfile,
        *,
        dpi: int = 300,
        first: int | None = None,
        last: int | None = None,
    ) -> None:
        super().__init__()
        self.pdf = Path(pdf)
        self.profile = profile
        self.dpi = dpi
        self.first = first
        self.last = last

    def run(self) -> None:
        try:
            result = scanned.parse_pdf(
                self.pdf, self.profile,
                dpi=self.dpi, first=self.first, last=self.last,
                progress=lambda position, total: self.progress.emit(position, total),
            )
            report, diagnoses = settle(result.rows, self._opening(result))
            self.finished.emit(result, report, diagnoses)
        except Exception as error:
            # Surfaced on the queue row as a reason, not swallowed and not a
            # percentage: a failed job should say what went wrong.
            self.failed.emit(str(error))

    def _opening(self, result: ParseResult) -> Decimal:
        """Seed the chain from the statement's own brought-forward figure."""
        for anchor in result.anchors:
            if anchor.kind in ("BF_BALANCE", "OPENING_BALANCE") and anchor.value:
                marker = anchor.marker or (
                    "DR" if self.profile.is_overdraft else "CR"
                )
                return signed_from_drcr(anchor.value, marker)
        return Decimal("0.00")


def start(worker: ParseWorker) -> QThread:
    """Move a worker onto its own thread and start it.

    The thread is returned so the caller can hold a reference; letting a
    running QThread fall out of scope destroys it and takes the process down.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.start()
    return thread


def detect_source(pdf: Path) -> str:
    """``digital`` or ``scanned``, for the queue row's badge."""
    try:
        return "digital" if classify(pdf).dominant is PageClass.DIGITAL else "scanned"
    except Exception:
        return "scanned"
