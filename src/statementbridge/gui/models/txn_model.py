"""Qt table model over the Phase 1 transaction frame.

Deliberately a thin adapter. Every figure it shows is formatted by
``statementbridge.money`` and every state it colours is already recorded on the
:class:`~statementbridge.parse.frame.Txn` by the balance engine -- the model
decides presentation, never meaning. If the review screen and the reconciliation
report could disagree about whether a row is sound, one of them would be lying.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from ...money import ZERO, format_drcr, format_indian
from ...parse.frame import RowState, Txn
from .. import tokens
from ..i18n import t

#: Column order matches the mockup's TxnTable.
COL_TICK, COL_NO, COL_DATE, COL_PAGE, COL_NARRATION, \
    COL_DEBIT, COL_CREDIT, COL_BALANCE, COL_CATEGORY, COL_CONFIDENCE = range(10)

COLUMN_COUNT = 10

#: Extra roles the delegate and views read.
RowStateRole = int(Qt.ItemDataRole.UserRole) + 1
BarColourRole = int(Qt.ItemDataRole.UserRole) + 2
TxnRole = int(Qt.ItemDataRole.UserRole) + 3


class TxnTableModel(QAbstractTableModel):
    """Presents ``list[Txn]`` to a QTableView.

    QTableView is virtualised by construction -- it only asks for the cells it
    is about to paint -- so a 1,342-row ledger needs no special handling here.
    """

    def __init__(self, rows: Sequence[Txn] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[Txn] = list(rows or [])
        self._categories: dict[int, str] = {}

    # --- data plumbing --------------------------------------------------

    def set_rows(self, rows: Sequence[Txn]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self._categories.clear()
        self.endResetModel()

    def rows(self) -> list[Txn]:
        return self._rows

    def txn(self, row: int) -> Txn | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def category_of(self, row: int) -> str:
        """Category code for a row.

        Everything is UNCLASSIFIED until the Phase 2 rules engine exists. The
        mockup shows that state as a red left bar, which is correct: an
        unclassified row is not ready to post.
        """
        return self._categories.get(row, "UNCL")

    def set_category(self, row: int, code: str) -> None:
        if not (0 <= row < len(self._rows)):
            return
        self._categories[row] = code
        index = self.index(row, COL_CATEGORY)
        self.dataChanged.emit(self.index(row, 0), self.index(row, COLUMN_COUNT - 1))

    def category_counts(self) -> dict[str, tuple[int, Decimal]]:
        """Row count and rupee total per category, for the rail."""
        totals: dict[str, tuple[int, Decimal]] = {}
        for position, row in enumerate(self._rows):
            code = self.category_of(position)
            count, value = totals.get(code, (0, ZERO))
            totals[code] = (count + 1, value + row.debit + row.credit)
        return totals

    # --- QAbstractTableModel -------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else COLUMN_COUNT

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return None
        return {
            COL_TICK: "", COL_NO: t("#"), COL_DATE: t("Date"), COL_PAGE: t("Pg"),
            COL_NARRATION: t("Narration"), COL_DEBIT: t("Debit ₹"),
            COL_CREDIT: t("Credit ₹"), COL_BALANCE: t("Balance ₹"),
            COL_CATEGORY: t("Category"), COL_CONFIDENCE: t("Conf"),
        }.get(section, "")

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, index.row(), column)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column in (COL_DEBIT, COL_CREDIT, COL_BALANCE):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if column in (COL_NO, COL_PAGE, COL_CONFIDENCE):
                return int(Qt.AlignmentFlag.AlignCenter)
            return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            tint = self._tint(row, index.row())
            if tint.text:
                return QColor(tint.text)
            return None
        if role == Qt.ItemDataRole.BackgroundRole:
            tint = self._tint(row, index.row())
            return QColor(tint.wash) if tint.wash else None
        if role == BarColourRole:
            tint = self._tint(row, index.row())
            return tint.bar
        if role == RowStateRole:
            return row.row_state.value
        if role == TxnRole:
            return row
        if role == Qt.ItemDataRole.ToolTipRole:
            return row.repair_note or None
        return None

    # --- presentation ---------------------------------------------------

    def _display(self, row: Txn, position: int, column: int) -> str:
        if column == COL_TICK:
            return "" if row.row_state is RowState.UNRESOLVED else "✓"
        if column == COL_NO:
            return str(position + 1)
        if column == COL_DATE:
            return row.date.strftime("%d-%m-%Y") if row.date else "—"
        if column == COL_PAGE:
            return str(row.page_no)
        if column == COL_NARRATION:
            return row.narration
        if column == COL_DEBIT:
            return format_indian(row.debit, blank_zero=True)
        if column == COL_CREDIT:
            return format_indian(row.credit, blank_zero=True)
        if column == COL_BALANCE:
            # Dr/Cr belongs on balances only, per the mockup's IndianAmount rule.
            return format_drcr(row.balance) if row.balance is not None else "—"
        if column == COL_CATEGORY:
            return self.category_of(position)
        if column == COL_CONFIDENCE:
            return f"{row.ocr_confidence:.0f}%" if row.ocr_confidence else "—"
        return ""

    def _tint(self, row: Txn, position: int) -> tokens.RowTint:
        """Map a row's recorded state onto the mockup's four row treatments."""
        if row.row_state is RowState.UNRESOLVED:
            # The balance chain could not be made to agree here, so the figures
            # themselves are in doubt -- the mockup's "unreadable" treatment.
            return tokens.ROW_UNREADABLE
        if self.category_of(position) == "UNCL":
            return tokens.ROW_UNCLASSIFIED
        if row.ocr_confidence and row.ocr_confidence < tokens.LOW_CONFIDENCE * 100:
            return tokens.ROW_LOW_CONFIDENCE
        return tokens.ROW_NORMAL
