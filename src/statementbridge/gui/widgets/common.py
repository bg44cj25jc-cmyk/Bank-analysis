"""Small shared widgets: amounts, confidence, chips, hairlines."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QLabel, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from ...money import format_drcr, format_indian
from .. import tokens
from ..models.txn_model import BarColourRole


def mono_font(size: int = tokens.SIZE_BODY) -> QFont:
    """Tabular figures. A ledger column that does not line up is unreadable."""
    font = QFont(tokens.FONT_MONO.split('"')[0], size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class IndianAmount(QLabel):
    """The one money label. ``₹1,23,456.78``, two decimals, always.

    Formatting is delegated to ``statementbridge.money`` so the screen and the
    exported workbook cannot drift apart. ``Dr``/``Cr`` appears on balances
    only, per the mockup.
    """

    def __init__(
        self,
        value: Decimal | None = None,
        *,
        balance: bool = False,
        prefix: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._balance = balance
        self._prefix = prefix
        self.setFont(mono_font())
        self.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.set_value(value)

    def set_value(self, value: Decimal | None) -> None:
        if value is None:
            self.setText("—")
            return
        if self._balance:
            text = format_drcr(value)
        else:
            text = format_indian(value)
        # U+2212 MINUS SIGN, not a hyphen: it aligns with the digits.
        text = text.replace("-", "−")
        self.setText(f"₹{text}" if self._prefix else text)


class ConfidenceMarker(QWidget):
    """Three states only, as specified: confirmed, medium, low.

    Below 0.70 is low and turns gold. Deliberately not a continuous gradient --
    a reviewer needs to sort rows into "look at this" and "do not", and a
    spectrum invites them to hesitate over every row instead.
    """

    def __init__(self, confidence: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._confidence = confidence
        self.setFixedSize(54, 20)

    def set_confidence(self, confidence: float) -> None:
        self._confidence = confidence
        self.update()

    @property
    def state(self) -> str:
        if self._confidence >= 0.95:
            return "confirmed"
        if self._confidence >= tokens.LOW_CONFIDENCE:
            return "medium"
        return "low"

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        state = self.state
        centre = QRect(2, 5, 10, 10)

        if state == "confirmed":
            painter.setPen(QPen(QColor(tokens.NEUTRAL_500), 1.4))
            painter.drawLine(3, 10, 6, 13)
            painter.drawLine(6, 13, 12, 5)
        elif state == "medium":
            painter.setPen(QPen(QColor(tokens.NEUTRAL_600), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.ACCENT))
            painter.drawEllipse(centre)

        if state != "confirmed":
            painter.setPen(QColor(tokens.NEUTRAL_700))
            font = painter.font()
            font.setPointSize(tokens.SIZE_TINY)
            painter.setFont(font)
            painter.drawText(
                QRect(16, 0, 38, 20),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                f"{self._confidence * 100:.0f}%",
            )
        painter.end()


class CategoryChip(QLabel):
    """``code · short name``. Border only, never filled.

    Filled chips would compete with the row wash that marks an unreadable row,
    and on a dense ledger the two would be hard to tell apart at a glance.
    """

    def __init__(self, code: str, name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_category(code, name)

    def set_category(self, code: str, name: str = "", *, low: bool = False) -> None:
        self.setText(f"{code} · {name}" if name else code)
        if code == "UNCL":
            colour = tokens.BAD
        elif low:
            colour = tokens.ACCENT
        else:
            colour = tokens.NEUTRAL_400
        self.setStyleSheet(
            f"border: 1px solid {colour}; border-radius: {tokens.RADIUS_SM}px;"
            f" padding: 1px 6px; color: {tokens.NEUTRAL_800};"
            f" font-size: {tokens.SIZE_SMALL}pt; background: transparent;"
        )


class Hairline(QFrame):
    """A one-pixel rule. The design leans on these instead of boxes."""

    def __init__(self, vertical: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(
            QFrame.Shape.VLine if vertical else QFrame.Shape.HLine
        )
        self.setFixedWidth(1) if vertical else self.setFixedHeight(1)
        self.setStyleSheet(f"background: {tokens.HAIRLINE}; border: none;")


class RowBarDelegate(QStyledItemDelegate):
    """Paints the left status bar on a transaction row.

    The bar is the mockup's primary signal: gold for low confidence, red for
    UNCLASSIFIED or an unreadable row. It sits in the first column so a
    reviewer can scan a single edge down the page rather than reading every
    cell to find what needs attention.
    """

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        if index.column() != 0:
            return
        colour = index.data(BarColourRole)
        if not colour:
            return
        painter.save()
        painter.fillRect(
            QRect(option.rect.left(), option.rect.top(), 3, option.rect.height()),
            QColor(colour),
        )
        painter.restore()


def titled(title: str, widget: QWidget, *, muted: str = "") -> QWidget:
    """A heading, an optional muted subtitle, and a body widget."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(tokens.SPACE_2)

    heading = QLabel(title)
    heading.setProperty("role", "heading")
    layout.addWidget(heading)
    if muted:
        subtitle = QLabel(muted)
        subtitle.setProperty("role", "muted")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
    layout.addWidget(widget, 1)
    return container
