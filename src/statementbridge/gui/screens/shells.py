"""Export and Accuracy, built as honest shells.

Both screens depend on phases that do not exist yet -- the Excel writer is
Phase 3 and the metrics store is Phase 5. They are laid out now so the shape of
the app is reviewable, and they say plainly what is missing rather than
displaying invented figures. A demo number on an accuracy dashboard is the kind
of thing that survives into a client meeting.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ...money import format_indian
from .. import tokens
from ..i18n import t
from ..widgets.common import Hairline

#: The four sheets, exactly as the client's existing workbook is laid out.
SHEETS = (
    ("Account Header", "17 rows",
     "Holder · A/c no · Type · Joint holder · Bank & branch · IFSC · Period · "
     "Opening · Closing · Total credits · Total debits · Net cash flow · Count"),
    ("Ledger", "one row per transaction",
     "S.No · Date · Description · Cat · Tally Ledger · Credit ₹ · Debit ₹ · "
     "Contra? · Running Balance"),
    ("Category Summary", "39 rows + reconciliation block",
     "Category · Description · Count · Credit ₹ · Debit ₹, then the recon check"),
    ("Notes", "assumptions and overrides",
     "Period isolation · balance verification · contra treatment · "
     "self vs third-party calls · suggested Tally groups"),
)


class SheetCard(QFrame):
    def __init__(self, name: str, rows: str, columns: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sheetCard")
        self.setStyleSheet(
            f"QFrame#sheetCard {{ background: {tokens.NEUTRAL_100};"
            f" border: 1px solid {tokens.DIVIDER};"
            f" border-radius: {tokens.RADIUS_MD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_3, tokens.SPACE_2, tokens.SPACE_3, tokens.SPACE_2
        )
        layout.setSpacing(2)
        title = QLabel(name)
        title.setProperty("role", "heading")
        layout.addWidget(title)
        count = QLabel(rows)
        count.setProperty("role", "muted")
        layout.addWidget(count)
        cols = QLabel(columns)
        cols.setWordWrap(True)
        cols.setProperty("role", "muted")
        layout.addWidget(cols)


class ExportScreen(QWidget):
    """Output picker and sheet preview. Blocked until reconciliation passes."""

    exportRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_6, tokens.SPACE_4, tokens.SPACE_6, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel(t("Export"))
        title.setProperty("role", "title")
        layout.addWidget(title)
        self.subtitle = QLabel()
        self.subtitle.setProperty("role", "muted")
        layout.addWidget(self.subtitle)

        self.blocker = QLabel()
        self.blocker.setWordWrap(True)
        self.blocker.setStyleSheet(
            f"color: {tokens.BAD}; background: {tokens.BAD_WASH};"
            f" border-left: 3px solid {tokens.BAD}; padding: {tokens.SPACE_2}px;"
        )
        layout.addWidget(self.blocker)

        choices = QHBoxLayout()
        self.choices: dict[str, QRadioButton] = {}
        for key, label in (
            ("excel", t("Excel workbook")),
            ("xml", t("Tally XML")),
            ("both", t("Both")),
        ):
            button = QRadioButton(label)
            self.choices[key] = button
            choices.addWidget(button)
        self.choices["both"].setChecked(True)
        choices.addStretch(1)
        layout.addLayout(choices)

        self.button = QPushButton(t("Export  Ctrl+E"))
        self.button.setProperty("role", "primary")
        self.button.clicked.connect(self._emit)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.pending = QLabel(t(
            "The writer itself is Phase 3. This screen is laid out now so the "
            "flow can be reviewed; it does not yet produce a file."
        ))
        self.pending.setWordWrap(True)
        self.pending.setProperty("role", "muted")
        layout.addWidget(self.pending)

        layout.addWidget(Hairline())
        sheets_label = QLabel(t("Four sheets will be written"))
        sheets_label.setProperty("role", "heading")
        layout.addWidget(sheets_label)
        for name, rows, columns in SHEETS:
            layout.addWidget(SheetCard(name, rows, columns))
        layout.addStretch(1)

        self.set_state(reconciled=False, variance=Decimal("0.00"))

    def _emit(self) -> None:
        for key, button in self.choices.items():
            if button.isChecked():
                self.exportRequested.emit(key)
                return

    def set_state(self, *, reconciled: bool, variance: Decimal,
                  overridden: bool = False, unresolved: int = 0,
                  subtitle: str = "") -> None:
        self.subtitle.setText(subtitle)
        allowed = reconciled or overridden
        if reconciled:
            self.blocker.hide()
        else:
            if overridden:
                message = t("Reconciliation was overridden and logged. "
                            "Export is allowed.")
            elif variance != 0:
                message = t(
                    "Export is blocked — reconciliation is off by ₹{v}. "
                    "Fix the suspect rows, or override with a logged reason.",
                    v=format_indian(abs(variance)),
                )
            else:
                # Saying "off by ₹0.00" here would be nonsense and would send a
                # reviewer hunting for a variance that does not exist. The
                # totals agree; what blocks export is that some rows could not
                # be read, and a row the scan lost leaves the closing balance
                # untouched.
                message = t(
                    "Export is blocked — the totals agree, but {n} rows could not "
                    "be resolved. A dropped row leaves the closing balance "
                    "unchanged, so a tie alone is not proof the ledger is whole.",
                    n=unresolved or 1,
                )
            self.blocker.setText(message)
            self.blocker.show()
        # Phase 3 has not built the writer, so the control stays disabled even
        # when reconciliation passes. Saying so beats a button that does nothing.
        self.button.setEnabled(False)
        self.button.setToolTip(
            t("Excel and Tally XML writers arrive in Phase 3.") if allowed
            else t("Blocked until reconciliation passes or is overridden.")
        )


class AccuracyScreen(QWidget):
    """Where the learning loop will report. Empty until Phase 5 records it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_6, tokens.SPACE_4, tokens.SPACE_6, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel(t("Is the tool getting better?"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        note = QLabel(t(
            "Auto-classification rate, correction rate and per-bank trends are "
            "recorded by the learning loop in Phase 5. Nothing is shown here yet "
            "because there is nothing measured yet — a placeholder figure on this "
            "screen would be worse than an empty one."
        ))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)

        expectation = QLabel(t(
            "When it does report, the dot-matrix banks will sit lowest. A "
            "correction on a Tripura Gramin statement is worth more than one "
            "anywhere else, and the per-bank breakdown should make that visible."
        ))
        expectation.setWordWrap(True)
        layout.addWidget(expectation)
        layout.addStretch(1)
