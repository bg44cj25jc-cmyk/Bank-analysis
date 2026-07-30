"""Review: the transaction table, the category rail, and the learning prompt.

Where a reviewer spends nearly all their time. Three things earn their place:

* The **category rail** keeps every code visible with a live count and rupee
  total, so the shape of a statement is legible without opening a report.
* The **inline rule prompt** appears under the row just corrected, offering to
  apply the same category to every other row containing the same token. That is
  the whole learning loop, sited where the human already is -- never a settings
  page they must remember to visit.
* The **source pane** puts the scanned line next to the parsed figures, because
  at this scan quality "is that an 8 or a B" is a question a reviewer will ask
  many times a day.
"""

from __future__ import annotations

import re
from decimal import Decimal

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSplitter, QTableView,
    QVBoxLayout, QWidget,
)

from ...money import ZERO, format_indian
from ...parse.frame import RowState, Txn
from .. import tokens
from ..i18n import t
from ..models.categories import BY_CODE, CATEGORIES, RailEntry, build_rail, resolve_key
from ..models.txn_model import (
    COL_CATEGORY, COL_NARRATION, COLUMN_COUNT, TxnTableModel,
)
from ..widgets.common import Hairline, RowBarDelegate, mono_font

#: A narration token worth offering as a rule: a word of real substance, not a
#: reference number that will never recur.
_TOKEN = re.compile(r"[A-Za-z][A-Za-z&./-]{3,}")


def suggest_token(narration: str) -> str:
    """Pick the token a learned rule should key on.

    The longest alphabetic word, which on these statements is almost always the
    counterparty -- "REDCLIFFE", "MEDICARE", "POPULARMEDICALAGENCY" -- rather
    than the transaction reference beside it. A rule keyed on a reference would
    match exactly once and teach the system nothing.
    """
    candidates = _TOKEN.findall(narration or "")
    if not candidates:
        return ""
    return max(candidates, key=len).upper()


class CategoryRail(QWidget):
    """Every category, always, with live counts. Empty ones drop to neutral."""

    categoryPicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(268)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_2)

        heading = QLabel(t("Categories"))
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        self._list = QListWidget()
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setStyleSheet(
            f"QListWidget {{ background: transparent; }}"
            f" QListWidget::item {{ padding: 3px 4px; }}"
            f" QListWidget::item:selected {{ background: {tokens.ACCENT_100};"
            f" color: {tokens.TEXT}; }}"
        )
        self._list.itemClicked.connect(self._picked)
        layout.addWidget(self._list, 1)

        self.legend = QLabel()
        self.legend.setProperty("role", "muted")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.set_counts({})

    def _picked(self, item: QListWidgetItem) -> None:
        code = item.data(Qt.ItemDataRole.UserRole)
        if code:
            self.categoryPicked.emit(code)

    def set_counts(self, counts: dict[str, tuple[int, Decimal]]) -> None:
        self._list.clear()
        group = ""
        for entry in build_rail(counts):
            if entry.category.group != group:
                group = entry.category.group
                header = QListWidgetItem(group.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(Qt.GlobalColor.gray)
                self._list.addItem(header)
            self._list.addItem(self._entry_item(entry))
        self.legend.setText(t(
            "Keys follow the money column: T on a credit row is UPI received, "
            "on a debit row UPI sent."
        ))

    def _entry_item(self, entry: RailEntry) -> QListWidgetItem:
        key = f" [{entry.category.key}]" if entry.category.key else ""
        total = format_indian(entry.total) if entry.count else ""
        text = f"{entry.category.code:<9} {entry.category.name}"
        item = QListWidgetItem(f"{text}{key}")
        item.setData(Qt.ItemDataRole.UserRole, entry.category.code)
        item.setToolTip(
            t("{n} rows · ₹{total}", n=entry.count, total=total) if entry.count
            else t("no rows in this category")
        )
        if entry.is_empty:
            item.setForeground(Qt.GlobalColor.gray)
        elif entry.category.code == "UNCL":
            from PySide6.QtGui import QColor
            item.setForeground(QColor(tokens.BAD))
        return item


class InlineRulePrompt(QFrame):
    """Offers to turn one correction into a rule. Enter applies, Esc skips."""

    applyRule = Signal(str, str)   # token, category code
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rulePrompt")
        self.setStyleSheet(
            f"QFrame#rulePrompt {{ background: {tokens.ACCENT_100};"
            f" border: 1px solid {tokens.ACCENT_300}; }}"
        )
        self.setFixedHeight(tokens.INLINE_PROMPT_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, 0, tokens.SPACE_3, 0)
        layout.setSpacing(tokens.SPACE_3)

        self._label = QLabel()
        layout.addWidget(self._label, 1)
        self._apply = QPushButton(t("Apply  ⏎"))
        self._apply.setProperty("role", "primary")
        self._apply.clicked.connect(self._emit)
        layout.addWidget(self._apply)
        self._skip = QPushButton(t("Just this row  Esc"))
        self._skip.clicked.connect(self.dismissed.emit)
        layout.addWidget(self._skip)

        self._token = ""
        self._code = ""
        self.hide()

    def offer(self, token: str, code: str, matches: int, bank: str) -> None:
        if not token or matches < 2:
            self.hide()
            return
        self._token, self._code = token, code
        name = BY_CODE[code].name if code in BY_CODE else code
        self._label.setText(t(
            'Apply {code} · {name} to all {n} rows containing “{token}”?  '
            "Creates a learned rule for {bank}.",
            code=code, name=name, n=matches, token=token, bank=bank,
        ))
        self.show()

    def _emit(self) -> None:
        self.applyRule.emit(self._token, self._code)
        self.hide()


class ReviewScreen(QWidget):
    """The transaction table with its rail, prompt and source pane."""

    ruleCreated = Signal(str, str, int)     # token, code, rows affected
    categoryChanged = Signal(int, str)      # row, code

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = TxnTableModel()
        self._bank = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.SPACE_6, tokens.SPACE_4, tokens.SPACE_6, tokens.SPACE_4
        )
        outer.setSpacing(tokens.SPACE_2)

        self._title = QLabel(t("Review"))
        self._title.setProperty("role", "title")
        outer.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setProperty("role", "muted")
        outer.addWidget(self._subtitle)

        filters = QHBoxLayout()
        filters.setSpacing(tokens.SPACE_2)
        self._search = QLineEdit()
        self._search.setPlaceholderText(t("Filter narrations…"))
        self._search.textChanged.connect(self._apply_filter)
        filters.addWidget(self._search, 1)
        self._attention = QPushButton(t("Needs attention"))
        self._attention.setCheckable(True)
        self._attention.toggled.connect(self._apply_filter)
        filters.addWidget(self._attention)
        outer.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.rail = CategoryRail()
        self.rail.categoryPicked.connect(self._assign_from_rail)
        splitter.addWidget(self.rail)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(RowBarDelegate(self.table))
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setFont(mono_font(tokens.SIZE_SMALL))
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        for column, width in enumerate(tokens.TXN_COLUMN_WIDTHS):
            if column == tokens.TXN_STRETCH_COLUMN:
                header.setSectionResizeMode(
                    column, QHeaderView.ResizeMode.Stretch
                )
            else:
                self.table.setColumnWidth(column, width)
        right_layout.addWidget(self.table, 1)

        self.prompt = InlineRulePrompt()
        self.prompt.applyRule.connect(self._apply_rule)
        self.prompt.dismissed.connect(self.prompt.hide)
        right_layout.addWidget(self.prompt)

        right_layout.addWidget(Hairline())
        self.status = QLabel()
        self.status.setProperty("role", "muted")
        right_layout.addWidget(self.status)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

    # --- population -----------------------------------------------------

    def set_rows(self, rows: list[Txn], *, bank: str = "", subtitle: str = "") -> None:
        self._bank = bank
        self.model.set_rows(rows)
        self._subtitle.setText(subtitle)
        self._refresh()

    def _refresh(self) -> None:
        self.rail.set_counts(self.model.category_counts())
        rows = self.model.rows()
        unresolved = sum(1 for row in rows if row.row_state is RowState.UNRESOLVED)
        classified = sum(
            1 for position in range(len(rows))
            if self.model.category_of(position) != "UNCL"
        )
        rate = (100.0 * classified / len(rows)) if rows else 0.0
        self.status.setText(t(
            "{total} rows · {unresolved} unresolved · auto-classified {rate:.0f}%",
            total=len(rows), unresolved=unresolved, rate=rate,
        ))

    # --- interaction ----------------------------------------------------

    def _apply_filter(self) -> None:
        needle = self._search.text().strip().lower()
        only_flagged = self._attention.isChecked()
        for position, row in enumerate(self.model.rows()):
            hidden = False
            if needle and needle not in row.narration.lower():
                hidden = True
            if only_flagged and row.row_state is not RowState.UNRESOLVED:
                hidden = True
            self.table.setRowHidden(position, hidden)

    def current_row(self) -> int:
        index = self.table.currentIndex()
        return index.row() if index.isValid() else -1

    def assign(self, row: int, code: str) -> None:
        """Set one row's category and offer to learn from it."""
        txn = self.model.txn(row)
        if txn is None:
            return
        self.model.set_category(row, code)
        self.categoryChanged.emit(row, code)
        self._refresh()

        token = suggest_token(txn.narration)
        matches = sum(
            1 for other in self.model.rows()
            if token and token in (other.narration or "").upper()
        )
        self.prompt.offer(token, code, matches, self._bank or t("this bank"))

    def _assign_from_rail(self, code: str) -> None:
        row = self.current_row()
        if row >= 0:
            self.assign(row, code)

    def _apply_rule(self, token: str, code: str) -> None:
        affected = 0
        for position, row in enumerate(self.model.rows()):
            if token and token in (row.narration or "").upper():
                self.model.set_category(position, code)
                affected += 1
        self._refresh()
        self.ruleCreated.emit(token, code, affected)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Single-letter category assignment, resolved by the row's direction."""
        row = self.current_row()
        text = event.text().strip()
        if row >= 0 and text and (text.isalpha() or text.isdigit()):
            txn = self.model.txn(row)
            if txn is not None:
                code = resolve_key(text, is_credit=txn.credit > ZERO)
                if code:
                    self.assign(row, code)
                    event.accept()
                    return
        if event.key() == Qt.Key.Key_Escape:
            self.prompt.hide()
        super().keyPressEvent(event)
