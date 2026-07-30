"""The application shell: nav rail, screen stack, audit drawer."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..balance.chain import ChainReport
from ..money import ZERO
from ..parse.frame import ParseResult, RowState
from ..parse.profiles.base import detect_profile, get_profile
from ..store.audit import (
    ACTION_CATEGORY_SET, ACTION_JOB_PARSED, ACTION_RULE_CREATED, AuditStore,
    Job, SEVERITY_CLASSIFY,
)
from . import tokens
from .i18n import t
from .screens.queue import (
    QueueScreen, STATUS_FAILED, STATUS_NEEDS_REVIEW, STATUS_READING,
    STATUS_RECONCILED,
)
from .screens.reconcile import ReconcileScreen
from .screens.review import ReviewScreen
from .screens.shells import AccuracyScreen, ExportScreen
from .widgets.override import OverrideDialog
from .work.parse_worker import ParseWorker, detect_source, start

SCREENS = ("Queue", "Review", "Reconcile", "Export", "Accuracy")


class AuditDrawer(QFrame):
    """Immutable, partner-visible. There is no delete control anywhere."""

    def __init__(self, store: AuditStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setFixedWidth(tokens.AUDIT_DRAWER_WIDTH)
        self.setObjectName("auditDrawer")
        self.setStyleSheet(
            f"QFrame#auditDrawer {{ background: {tokens.NEUTRAL_100};"
            f" border-left: 1px solid {tokens.HAIRLINE}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel(t("Audit trail"))
        title.setProperty("role", "heading")
        layout.addWidget(title)
        subtitle = QLabel(t("immutable · visible to the partner"))
        subtitle.setProperty("role", "muted")
        layout.addWidget(subtitle)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

        footer = QLabel(t(
            "Overrides, bulk reassignments and rule creations are written here "
            "with the rows they touched. Nothing in this list can be edited or "
            "deleted."
        ))
        footer.setWordWrap(True)
        footer.setProperty("role", "muted")
        layout.addWidget(footer)
        self.refresh()

    def refresh(self, job_id: int | None = None) -> None:
        from PySide6.QtGui import QColor

        self.list.clear()
        for line in self.store.lines(job_id):
            item = QListWidgetItem(
                f"{line.ts:%d %b %H:%M}  {line.actor}\n{line.action} — {line.detail}"
            )
            if line.severity == "override":
                item.setForeground(QColor(tokens.BAD))
            elif line.severity == SEVERITY_CLASSIFY:
                item.setForeground(QColor(tokens.ACCENT_700))
            self.list.addItem(item)


class MainWindow(QMainWindow):
    def __init__(self, store: AuditStore | None = None, actor: str = "Sujata D.") -> None:
        super().__init__()
        self.setWindowTitle("StatementBridge — SuhagKuti Tax & Legal Services")
        self.store = store or AuditStore()
        self.actor = actor
        self.resize(1600, 940)

        self._result: ParseResult | None = None
        self._report: ChainReport | None = None
        self._diagnoses: list = []
        self._job_id: int | None = None
        self._overridden = False
        self._thread = None
        self._worker = None
        self._jobs: list[dict] = []

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The stack must exist before the rail, which connects to it.
        self.stack = QStackedWidget()
        root.addWidget(self._build_nav())

        self.queue = QueueScreen()  # noqa: E501 - screens added to the stack below
        self.review = ReviewScreen()
        self.reconcile = ReconcileScreen()
        self.export = ExportScreen()
        self.accuracy = AccuracyScreen()
        for screen in (self.queue, self.review, self.reconcile,
                       self.export, self.accuracy):
            self.stack.addWidget(screen)
        root.addWidget(self.stack, 1)

        self.drawer = AuditDrawer(self.store)
        self.drawer.hide()
        root.addWidget(self.drawer)

        self.setCentralWidget(central)

        self.queue.filesDropped.connect(self.add_files)
        self.review.ruleCreated.connect(self._rule_created)
        self.review.categoryChanged.connect(self._category_changed)
        self.reconcile.overrideRequested.connect(self.request_override)
        self.reconcile.openRow.connect(self._open_row)

    def _build_nav(self) -> QWidget:
        rail = QFrame()
        rail.setFixedWidth(212)
        rail.setObjectName("navRail")
        rail.setStyleSheet(
            f"QFrame#navRail {{ background: {tokens.SURFACE};"
            f" border-right: 1px solid {tokens.HAIRLINE}; }}"
        )
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(
            tokens.SPACE_3, tokens.SPACE_4, tokens.SPACE_3, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_1)

        brand = QLabel("StatementBridge")
        brand.setProperty("role", "heading")
        brand.setWordWrap(True)
        layout.addWidget(brand)
        firm = QLabel("SuhagKuti Tax & Legal")
        firm.setProperty("role", "muted")
        firm.setWordWrap(True)
        layout.addWidget(firm)
        layout.addSpacing(tokens.SPACE_4)

        self.nav = QListWidget()
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setStyleSheet(
            "QListWidget { background: transparent; }"
            f" QListWidget::item {{ padding: 7px 6px; }}"
            f" QListWidget::item:selected {{ background: {tokens.ACCENT_100};"
            f" color: {tokens.TEXT}; border-left: 2px solid {tokens.ACCENT}; }}"
        )
        for name in SCREENS:
            self.nav.addItem(QListWidgetItem(t(name)))
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.nav)
        layout.addStretch(1)

        self.audit_button = QPushButton(t("Audit trail"))
        self.audit_button.clicked.connect(self._toggle_drawer)
        layout.addWidget(self.audit_button)
        return rail

    def _toggle_drawer(self) -> None:
        self.drawer.setVisible(not self.drawer.isVisible())
        if self.drawer.isVisible():
            self.drawer.refresh(self._job_id)

    # --- jobs -----------------------------------------------------------

    def add_files(self, paths: list[Path]) -> None:
        for path in paths:
            job = self.store.add_job(Job(
                client=path.stem[:40], bank_key="", pdf_path=str(path),
                source=detect_source(path), status=STATUS_READING,
            ))
            self._jobs.append({
                "client": job.client, "bank": "—", "account": "—", "type": "—",
                "fy": "—", "source": job.source, "status": STATUS_READING,
                "progress": 0, "txns": "—", "flagged": "—", "id": job.id,
            })
        self.queue.set_jobs(self._jobs)
        if paths:
            self.start_parse(paths[0], row=len(self._jobs) - 1)

    def start_parse(self, pdf: Path, *, row: int = 0, profile_key: str = "") -> None:
        profile = get_profile(profile_key) if profile_key else (
            detect_profile(pdf.stem) or get_profile("gramin_cc")
        )
        self._job_id = self._jobs[row].get("id") if row < len(self._jobs) else None
        self._worker = ParseWorker(pdf, profile)
        self._worker.progress.connect(
            lambda page, total: self.queue.set_progress(
                row, int(100 * page / max(total, 1)), STATUS_READING
            )
        )
        self._worker.finished.connect(
            lambda result, report, diagnoses: self._parsed(
                result, report, diagnoses, row, profile
            )
        )
        self._worker.failed.connect(lambda message: self._failed(message, row))
        self._thread = start(self._worker)

    def _parsed(self, result, report, diagnoses, row: int, profile) -> None:
        self._result, self._report, self._diagnoses = result, report, diagnoses
        self._overridden = False

        flagged = sum(1 for r in result.rows if r.row_state is RowState.UNRESOLVED)
        if row < len(self._jobs):
            self._jobs[row].update({
                "bank": profile.name.split("—")[0].strip(),
                "status": STATUS_RECONCILED if report.reconciled else STATUS_NEEDS_REVIEW,
                "progress": 100, "txns": len(result.rows), "flagged": flagged,
            })
            self.queue.set_jobs(self._jobs)

        subtitle = t("{n} rows across {p} pages", n=len(result.rows), p=result.page_count)
        self.review.set_rows(result.rows, bank=profile.name, subtitle=subtitle)
        self.reconcile.set_job(report, diagnoses, result, subtitle=subtitle)
        self.export.set_state(
            reconciled=report.reconciled, variance=report.variance,
            unresolved=report.unresolved, subtitle=subtitle,
        )
        self.store.append(
            actor=self.actor, action=ACTION_JOB_PARSED, job_id=self._job_id,
            detail=t("{n} rows, {f} unresolved", n=len(result.rows), f=flagged),
        )
        self.drawer.refresh(self._job_id)
        self.nav.setCurrentRow(1)

    def _failed(self, message: str, row: int) -> None:
        if row < len(self._jobs):
            self._jobs[row].update({"status": STATUS_FAILED, "progress": 0})
            self._jobs[row]["flagged"] = message[:40]
            self.queue.set_jobs(self._jobs)

    def _open_row(self, index: int) -> None:
        self.nav.setCurrentRow(1)
        self.review.table.selectRow(index)

    # --- audit-writing interactions -------------------------------------

    def _category_changed(self, row: int, code: str) -> None:
        self.store.append(
            actor=self.actor, action=ACTION_CATEGORY_SET, job_id=self._job_id,
            detail=f"row {row + 1} → {code}", row_ids=[row],
            severity=SEVERITY_CLASSIFY,
        )
        self.drawer.refresh(self._job_id)

    def _rule_created(self, token: str, code: str, affected: int) -> None:
        self.store.append(
            actor=self.actor, action=ACTION_RULE_CREATED, job_id=self._job_id,
            detail=t('“{token}” → {code}, applied to {n} rows',
                     token=token, code=code, n=affected),
            severity=SEVERITY_CLASSIFY,
        )
        self.drawer.refresh(self._job_id)

    def request_override(self) -> None:
        if self._report is None:
            return
        dialog = OverrideDialog(self._report.variance, actor=self.actor, parent=self)
        if dialog.exec() != OverrideDialog.DialogCode.Accepted:
            return
        self.store.append_override(
            actor=self.actor, job_id=self._job_id,
            variance=self._report.variance, reason=dialog.reason_text(),
        )
        self._overridden = True
        self.export.set_state(
            reconciled=self._report.reconciled, variance=self._report.variance,
            unresolved=self._report.unresolved, overridden=True,
        )
        self.drawer.refresh(self._job_id)
        if not self.drawer.isVisible():
            self._toggle_drawer()
