"""Queue: drop PDFs in, watch them parse.

The drop zone is the whole window, not a small target. Staff arrive with a
folder of statements and drag several at once; making them aim at a rectangle
is a tax paid many times a day.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import tokens
from ..i18n import t

STATUS_QUEUED = "Queued"
STATUS_READING = "Reading"
STATUS_NEEDS_REVIEW = "Needs review"
STATUS_RECONCILED = "Reconciled"
STATUS_FAILED = "Failed"

_STATUS_COLOUR = {
    STATUS_RECONCILED: tokens.GOOD,
    STATUS_FAILED: tokens.BAD,
    STATUS_NEEDS_REVIEW: tokens.ACCENT_700,
}


class DropZone(QFrame):
    """Dashed accent frame. Rejects non-PDFs inline, never with a modal."""

    filesDropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self._style(False)
        self.setMinimumHeight(120)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(tokens.SPACE_1)

        title = QLabel(t("Drop bank statement PDFs here"))
        title.setProperty("role", "heading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._hint = QLabel(
            t("one PDF per account, per financial year · "
              "scanned pages are OCR'd automatically")
        )
        self._hint.setProperty("role", "muted")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)

        browse = QPushButton(t("Browse…"))
        browse.clicked.connect(self._browse)
        layout.addWidget(browse, alignment=Qt.AlignmentFlag.AlignCenter)

    def _style(self, active: bool) -> None:
        colour = tokens.ACCENT if active else tokens.NEUTRAL_400
        background = tokens.ACCENT_100 if active else "transparent"
        self.setStyleSheet(
            f"QFrame#dropZone {{ border: 2px dashed {colour};"
            f" border-radius: {tokens.RADIUS_LG}px; background: {background}; }}"
        )

    def _browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, t("Choose statement PDFs"), "", "PDF files (*.pdf)"
        )
        if paths:
            self.filesDropped.emit([Path(p) for p in paths])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._style(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._style(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._style(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
        rejected = len(paths) - len(pdfs)
        if rejected:
            self._hint.setText(
                t("{n} file(s) ignored — only PDFs can be read.", n=rejected)
            )
            self._hint.setStyleSheet(f"color: {tokens.BAD};")
        if pdfs:
            self.filesDropped.emit(pdfs)
        event.acceptProposedAction()


class QueueScreen(QWidget):
    """The job list and its drop target."""

    filesDropped = Signal(list)
    jobActivated = Signal(int)

    COLUMNS = ("Client", "Bank", "Account", "Type", "FY", "Source",
               "Status", "Progress", "Txns", "Flagged")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_6, tokens.SPACE_4, tokens.SPACE_6, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel(t("Job queue"))
        title.setProperty("role", "title")
        layout.addWidget(title)
        self.summary = QLabel()
        self.summary.setProperty("role", "muted")
        layout.addWidget(self.summary)

        self.drop = DropZone()
        self.drop.filesDropped.connect(self.filesDropped.emit)
        layout.addWidget(self.drop)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([t(c) for c in self.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.cellDoubleClicked.connect(
            lambda row, _column: self.jobActivated.emit(row)
        )
        layout.addWidget(self.table, 1)

        self.footer = QLabel()
        self.footer.setProperty("role", "muted")
        layout.addWidget(self.footer)
        self.set_jobs([])

    def set_jobs(self, jobs: list[dict]) -> None:
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = [
                job.get("client", ""), job.get("bank", ""), job.get("account", ""),
                job.get("type", ""), job.get("fy", ""), job.get("source", ""),
                job.get("status", STATUS_QUEUED),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 6:
                    colour = _STATUS_COLOUR.get(str(value))
                    if colour:
                        from PySide6.QtGui import QColor
                        item.setForeground(QColor(colour))
                self.table.setItem(row, column, item)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(job.get("progress", 0)))
            bar.setTextVisible(True)
            bar.setFixedHeight(16)
            self.table.setCellWidget(row, 7, bar)

            for column, key in ((8, "txns"), (9, "flagged")):
                item = QTableWidgetItem(str(job.get(key, "—")))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

        # Size to content after filling, so an account number or a bank name is
        # never clipped in favour of empty space in the client column.
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )

        needing = sum(
            1 for job in jobs if job.get("status") == STATUS_NEEDS_REVIEW
        )
        self.summary.setText(
            t("{n} jobs · {r} need review", n=len(jobs), r=needing) if jobs
            else t("Nothing in the queue")
        )

    def set_progress(self, row: int, percent: int, status: str = "") -> None:
        widget = self.table.cellWidget(row, 7)
        if widget is not None:
            widget.setValue(percent)
        if status:
            item = self.table.item(row, 6)
            if item is not None:
                item.setText(status)

    def set_footer(self, text: str) -> None:
        self.footer.setText(text)
