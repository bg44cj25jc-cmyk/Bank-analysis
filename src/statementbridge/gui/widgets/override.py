"""The override dialog.

Exporting a statement whose figures do not match the bank's printed closing
balance is sometimes the right call -- a genuinely illegible page, a bank error
the partner has already confirmed. It is never a routine one, so the dialog is
deliberately unhelpful about being dismissed quickly: it will not submit
without a real reason, and what is typed goes into an immutable log under the
user's own name and into the workbook's Notes sheet.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget,
)

from ...money import format_indian
from .. import tokens
from ..i18n import t


class OverrideDialog(QDialog):
    """Blocks until a reason of at least ``OVERRIDE_REASON_MINIMUM`` characters."""

    def __init__(
        self, variance: Decimal, *, actor: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Override a failed reconciliation"))
        self.setModal(True)
        self._variance = variance

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_6, tokens.SPACE_4, tokens.SPACE_6, tokens.SPACE_4
        )
        layout.setSpacing(tokens.SPACE_3)

        headline = QLabel(t("This job is off by ₹{v}", v=format_indian(abs(variance))))
        headline.setProperty("role", "heading")
        headline.setStyleSheet(f"color: {tokens.BAD};")
        layout.addWidget(headline)

        warning = QLabel(t(
            "Exporting anyway sends figures to Tally that do not match the bank's "
            "printed closing balance."
        ))
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.reason = QPlainTextEdit()
        self.reason.setPlaceholderText(t("Why is this being overridden?"))
        self.reason.setFixedHeight(90)
        self.reason.textChanged.connect(self._validate)
        layout.addWidget(self.reason)

        self.hint = QLabel()
        self.hint.setProperty("role", "muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        note = QLabel(t(
            "Your name, the variance and this reason go into the audit trail. "
            "The partner sees it."
        ))
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            t("Override && log")
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._actor = actor
        self._validate()

    def _validate(self) -> None:
        length = len(self.reason.toPlainText().strip())
        needed = tokens.OVERRIDE_REASON_MINIMUM
        ok = length >= needed
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        self.hint.setText(
            "" if ok else t("{n} more characters needed.", n=needed - length)
        )

    def reason_text(self) -> str:
        return self.reason.toPlainText().strip()
