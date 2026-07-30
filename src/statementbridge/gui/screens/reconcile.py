"""Reconciliation: the verdict, the suspect rows, and the page chain.

This screen is the reason the GUI was brought forward ahead of the rules
engine. The Phase 1 balance engine already localises which field of which row
broke the chain; until now that only reached a log file. Here it becomes a
work queue: a reviewer sees what the scan read, what the running balance
requires instead, and how much of the variance each row explains.

Nothing on this screen invents a figure. Where the engine refused to choose
between two readings, the row says so and waits for a human.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ...balance.chain import ChainReport
from ...balance.repair import Diagnosis
from ...money import ZERO, format_drcr, format_indian
from ...parse.frame import ParseResult
from .. import tokens
from ..i18n import t
from ..widgets.common import Hairline, mono_font


def clear_layout(layout, *, keep: int = 0) -> None:
    """Remove and destroy every child widget beyond ``keep`` items.

    Uses ``setParent(None)`` rather than ``deleteLater``: deferred deletion
    only happens once the event loop spins, so a screen repopulated between
    two paints -- or rendered offscreen for a screenshot -- would still show
    the widgets it thought it had removed.
    """
    while layout.count() > keep:
        item = layout.takeAt(0)
        widget = item.widget() if item else None
        if widget is not None:
            widget.setParent(None)


class VerdictPanel(QFrame):
    """Opening + credits − debits = computed, against the printed closing.

    Green only at exactly zero variance. There is no "close enough" state, and
    that is deliberate: the whole pipeline is built on Decimal so that a tie is
    a fact rather than a tolerance.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4
        )
        outer.setSpacing(tokens.SPACE_2)

        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(tokens.SPACE_6)
        self._grid.setVerticalSpacing(tokens.SPACE_2)
        self._grid.setColumnStretch(2, 1)
        outer.addLayout(self._grid)

        # Kept out of the grid: a word-wrapped paragraph inside a column-sized
        # cell collides with the figures beside it.
        self._note = QLabel()
        self._note.setWordWrap(True)
        self._note.setProperty("role", "muted")
        self._note.hide()
        outer.addWidget(self._note)

        self.set_report(None)

    def _line(self, row: int, label: str, value: str, *, muted: str = "",
              strong: bool = False, colour: str | None = None) -> None:
        name = QLabel(label)
        if muted:
            name.setToolTip(muted)
        amount = QLabel(value)
        amount.setFont(mono_font(tokens.SIZE_BODY + (1 if strong else 0)))
        amount.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        style = f"color: {colour};" if colour else ""
        if strong:
            style += " font-weight: 600;"
        if style:
            amount.setStyleSheet(style)
            name.setStyleSheet(style)
        self._grid.addWidget(name, row, 0)
        self._grid.addWidget(amount, row, 1)
        if muted:
            note = QLabel(muted)
            note.setProperty("role", "muted")
            self._grid.addWidget(note, row, 2)

    def set_report(self, report: ChainReport | None) -> None:
        clear_layout(self._grid)

        if report is None:
            placeholder = QLabel(t("No statement loaded."))
            placeholder.setProperty("role", "muted")
            self._grid.addWidget(placeholder, 0, 0)
            return

        # Three states, not two. Green is reserved for a statement that is
        # actually safe to post: the arithmetic ties *and* every row resolved.
        # A statement whose totals agree while rows remain unresolved is a real
        # and dangerous middle case -- a dropped row leaves the closing balance
        # untouched -- so it gets the gold "look at this" treatment rather than
        # a green tick that would invite someone to export it.
        ties = report.balances_tie
        if report.reconciled:
            colour, headline = tokens.GOOD, t("Fully reconciled")
        elif ties:
            colour, headline = tokens.ACCENT_700, t("Balances tie, but rows need review")
        else:
            colour, headline = tokens.BAD, t("Does not reconcile")
        verdict = QLabel(headline)
        verdict.setProperty("role", "heading")
        verdict.setStyleSheet(f"color: {colour}; font-weight: 600;")
        self._grid.addWidget(verdict, 0, 0, 1, 3)

        self._line(1, t("Opening balance"), format_drcr(report.opening))
        self._line(2, t("Add: total credits"), format_indian(report.total_credit),
                   muted=t("{n} rows", n=report.credit_count))
        self._line(3, t("Less: total debits"), format_indian(report.total_debit),
                   muted=t("{n} rows", n=report.debit_count))
        self._grid.addWidget(Hairline(), 4, 0, 1, 3)
        self._line(5, t("Computed closing"), format_drcr(report.closing_computed),
                   strong=True)
        if report.closing_printed is not None:
            self._line(6, t("Closing printed on the statement"),
                       format_drcr(report.closing_printed))
            self._line(7, t("Variance"), format_indian(report.variance),
                       strong=True, colour=colour)
        else:
            self._line(6, t("Closing printed on the statement"), "—",
                       muted=t("not captured from the scan"))

        if ties and not report.reconciled:
            self._note.setText(t(
                "The arithmetic ties, but {n} rows could not be resolved. A row the "
                "scan dropped entirely leaves the closing balance untouched, so a "
                "tie alone is not enough to export.", n=report.unresolved))
            self._note.show()
        else:
            self._note.hide()


class SuspectRow(QFrame):
    """One row the chain could not settle, with read vs implied side by side."""

    openRow = Signal(int)

    def __init__(self, diagnosis: Diagnosis, narration: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Scope the rule to this frame by object name. An unscoped stylesheet
        # cascades to every child, which paints the status bar down the side of
        # each individual label instead of once down the card.
        self.setObjectName("suspectCard")
        self.setStyleSheet(
            f"QFrame#suspectCard {{ background: {tokens.NEUTRAL_100};"
            f" border-left: 3px solid {tokens.BAD}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_3 + 3, tokens.SPACE_2, tokens.SPACE_3, tokens.SPACE_2
        )
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(tokens.SPACE_2)
        identifier = QLabel(f"#{diagnosis.index + 1}")
        identifier.setFont(mono_font(tokens.SIZE_SMALL))
        top.addWidget(identifier)
        page = QLabel(t("page {n}", n=diagnosis.page_no))
        page.setProperty("role", "muted")
        top.addWidget(page)
        top.addStretch(1)
        kind = QLabel(diagnosis.kind.replace("_", " ").lower())
        kind.setProperty("role", "muted")
        top.addWidget(kind)
        layout.addLayout(top)

        if narration:
            text = QLabel(narration)
            text.setWordWrap(True)
            layout.addWidget(text)

        # The heart of it: what the page appeared to say, and what the running
        # balance requires instead.
        if diagnosis.read_value is not None or diagnosis.implied_value is not None:
            comparison = QHBoxLayout()
            comparison.setSpacing(tokens.SPACE_4)
            for label, value in (
                (t("read"), diagnosis.read_value),
                (t("implies"), diagnosis.implied_value),
            ):
                caption = QLabel(label)
                caption.setProperty("role", "muted")
                figure = QLabel(format_indian(value) if value is not None else "—")
                figure.setFont(mono_font(tokens.SIZE_SMALL))
                comparison.addWidget(caption)
                comparison.addWidget(figure)
            comparison.addStretch(1)
            layout.addLayout(comparison)

        why = QLabel(diagnosis.detail)
        why.setWordWrap(True)
        why.setProperty("role", "muted")
        layout.addWidget(why)

        open_button = QPushButton(t("Open row"))
        open_button.clicked.connect(lambda: self.openRow.emit(diagnosis.index))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(open_button)
        layout.addLayout(row)


class PageChainGrid(QWidget):
    """One tile per page: does the chain survive that page, and do its totals agree?

    A failing page narrows the hunt from the whole statement to the rows on one
    sheet, which is the difference between a reviewer checking 56 lines and
    checking 1,342.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setSpacing(tokens.SPACE_1)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def set_pages(self, failing: dict[int, int], total_pages: int) -> None:
        clear_layout(self._layout)
        for position in range(total_pages):
            page = position + 1
            bad = failing.get(page, 0)
            tile = QLabel(str(page))
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setFixedSize(34, 28)
            colour = tokens.BAD if bad else tokens.GOOD
            wash = tokens.BAD_WASH if bad else tokens.GOOD_WASH
            tile.setStyleSheet(
                f"border: 1px solid {colour}; color: {colour}; background: {wash};"
                f" border-radius: {tokens.RADIUS_SM}px; font-size: {tokens.SIZE_TINY}pt;"
            )
            tile.setToolTip(
                t("{n} unresolved rows on this page", n=bad) if bad
                else t("chain intact")
            )
            self._layout.addWidget(tile, position // 12, position % 12)
        # Without this the columns share the spare width and the tiles drift
        # apart into a sparse row instead of reading as one block.
        self._layout.setColumnStretch(12, 1)


class ReconcileScreen(QWidget):
    """Verdict, suspects, page chain, and the route to a logged override."""

    openRow = Signal(int)
    overrideRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._report: ChainReport | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.SPACE_6, tokens.SPACE_4, tokens.SPACE_6, tokens.SPACE_4
        )
        outer.setSpacing(tokens.SPACE_3)

        self._title = QLabel(t("Reconciliation"))
        self._title.setProperty("role", "title")
        outer.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setProperty("role", "muted")
        outer.addWidget(self._subtitle)

        body = QHBoxLayout()
        body.setSpacing(tokens.SPACE_6)

        left = QVBoxLayout()
        left.setSpacing(tokens.SPACE_3)
        self.verdict = VerdictPanel()
        left.addWidget(self.verdict)

        chain_label = QLabel(t("Page-by-page balance chain"))
        chain_label.setProperty("role", "heading")
        left.addWidget(chain_label)
        self.page_chain = PageChainGrid()
        left.addWidget(self.page_chain)

        self.totals_label = QLabel()
        self.totals_label.setProperty("role", "muted")
        self.totals_label.setWordWrap(True)
        left.addWidget(self.totals_label)

        self.override_button = QPushButton(t("Override and allow export…"))
        self.override_button.clicked.connect(self.overrideRequested.emit)
        left.addWidget(self.override_button, alignment=Qt.AlignmentFlag.AlignLeft)
        override_note = QLabel(t(
            "An override needs a typed reason and is logged against your name. "
            "Export stays blocked until then."
        ))
        override_note.setWordWrap(True)
        override_note.setProperty("role", "muted")
        left.addWidget(override_note)
        left.addStretch(1)
        body.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(tokens.SPACE_2)
        self._suspect_heading = QLabel(t("Suspect rows"))
        self._suspect_heading.setProperty("role", "heading")
        right.addWidget(self._suspect_heading)
        hint = QLabel(t("the running balance stops chaining here"))
        hint.setProperty("role", "muted")
        right.addWidget(hint)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._suspect_host = QWidget()
        self._suspect_layout = QVBoxLayout(self._suspect_host)
        self._suspect_layout.setContentsMargins(0, 0, 0, 0)
        self._suspect_layout.setSpacing(tokens.SPACE_2)
        self._suspect_layout.addStretch(1)
        self._scroll.setWidget(self._suspect_host)
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        right.addWidget(self._scroll, 1)
        body.addLayout(right, 2)

        outer.addLayout(body, 1)

    # --- population -----------------------------------------------------

    def set_job(
        self,
        report: ChainReport,
        diagnoses: list[Diagnosis],
        result: ParseResult,
        *,
        subtitle: str = "",
    ) -> None:
        self._report = report
        self._subtitle.setText(subtitle)
        self.verdict.set_report(report)

        failing: dict[int, int] = {}
        for row in result.rows:
            if row.row_state.blocks_export:
                failing[row.page_no] = failing.get(row.page_no, 0) + 1
        self.page_chain.set_pages(failing, max(result.page_count, 1))

        self._set_totals(result)
        self._set_suspects(diagnoses, result)
        self.override_button.setEnabled(not report.reconciled)

    def _set_totals(self, result: ParseResult) -> None:
        """Compare the bank's own printed page totals against ours."""
        printed_credit = sum(
            (a.value for a in result.anchors_of("PAGE_TOTAL_CREDIT") if a.value), ZERO
        )
        printed_debit = sum(
            (a.value for a in result.anchors_of("PAGE_TOTAL_DEBIT") if a.value), ZERO
        )
        if printed_credit == ZERO and printed_debit == ZERO:
            self.totals_label.setText(
                t("No printed page totals were legible on this statement.")
            )
            return
        summed_credit = sum((row.credit for row in result.rows), ZERO)
        summed_debit = sum((row.debit for row in result.rows), ZERO)
        self.totals_label.setText(
            t("Page totals cross-check — printed {pc} Cr / {pd} Dr, "
              "summed {sc} Cr / {sd} Dr.",
              pc=format_indian(printed_credit), pd=format_indian(printed_debit),
              sc=format_indian(summed_credit), sd=format_indian(summed_debit))
        )

    def _set_suspects(self, diagnoses: list[Diagnosis], result: ParseResult) -> None:
        clear_layout(self._suspect_layout, keep=1)

        unresolved = [d for d in diagnoses if not d.applied]
        # Sorted by how much of the variance each explains, so the row most
        # worth a reviewer's next minute is at the top.
        unresolved.sort(
            key=lambda d: abs((d.implied_value or ZERO) - (d.read_value or ZERO)),
            reverse=True,
        )
        self._suspect_heading.setText(
            t("Suspect rows ({n})", n=len(unresolved)) if unresolved
            else t("Suspect rows")
        )
        for diagnosis in unresolved[:60]:
            narration = ""
            if 0 <= diagnosis.index < len(result.rows):
                narration = result.rows[diagnosis.index].narration
            widget = SuspectRow(diagnosis, narration)
            widget.openRow.connect(self.openRow.emit)
            self._suspect_layout.insertWidget(
                self._suspect_layout.count() - 1, widget
            )
