"""Design tokens, taken from the approved StatementBridge mockup.

Values are copied from the mockup's CSS custom properties rather than
re-derived, so the desktop build and the design stay in step. The system is
mono-gold on a warm light ground; there is deliberately **no dark mode**.

Two colours exist outside the gold ramp -- one green, one brick red -- at the
same lightness as `ACCENT_600`. They carry the reconciliation verdict and
nothing else. A ledger needs an unambiguous pass/fail signal, and if those two
colours also appeared as decoration the signal would stop meaning anything.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- ground and ink -----------------------------------------------------
BG = "#f3f2f2"
SURFACE = "#eae9e9"
TEXT = "#201f1d"

# --- neutral ramp -------------------------------------------------------
NEUTRAL_100 = "#f8f4f4"
NEUTRAL_200 = "#eae7e7"
NEUTRAL_300 = "#d7d3d3"
NEUTRAL_400 = "#bab6b6"
NEUTRAL_500 = "#9b9797"   # zero-count categories drop to this
NEUTRAL_600 = "#7d7979"
NEUTRAL_700 = "#605d5d"
NEUTRAL_800 = "#444141"
NEUTRAL_900 = "#2d2b2b"

# --- gold accent --------------------------------------------------------
ACCENT = "#b68235"
ACCENT_100 = "#fff3e4"
ACCENT_200 = "#ffe3bf"
ACCENT_300 = "#facb8d"
ACCENT_400 = "#e1ad66"
ACCENT_500 = "#c28d41"
ACCENT_600 = "#a06f24"
ACCENT_700 = "#7d5411"
ACCENT_800 = "#5a3b0a"

# --- the only two non-gold colours in the system ------------------------
#: Reconciliation ties exactly.
GOOD = "#4d6b3d"
#: Reconciliation is off, or a row could not be read.
BAD = "#9d3427"
GOOD_WASH = "#eef2ea"
BAD_WASH = "#f7ecea"

DIVIDER = "#d3d0cf"       # flattened from color-mix(#201f1d 16%)
HAIRLINE = "#c9c5c4"

# --- spacing (the mockup's 4.6px base) ----------------------------------
SPACE_1 = 5
SPACE_2 = 9
SPACE_3 = 14
SPACE_4 = 18
SPACE_6 = 28
SPACE_8 = 37

RADIUS_SM = 2
RADIUS_MD = 4
RADIUS_LG = 7

# --- type ---------------------------------------------------------------
#: The mockup asks for Cormorant Garamond and Lora. Neither ships with Windows
#: or with Qt, and an offline desktop tool cannot fetch a webfont, so the
#: families below degrade to what is actually present. Substituting here rather
#: than at paint time keeps every screen consistent when the preferred face is
#: missing.
FONT_HEADING = 'Cormorant Garamond", "Georgia", "Times New Roman'
FONT_BODY = 'Lora", "Georgia", "Segoe UI'
#: Figures must line up vertically in a ledger; a monospace face guarantees it
#: even where the body font has no tabular-figures feature.
FONT_MONO = 'Consolas", "DejaVu Sans Mono", "Courier New'

HEADING_WEIGHT = 600      # bold was retired in the mockup's third review round

SIZE_TITLE = 20
SIZE_HEADING = 15
SIZE_BODY = 12
SIZE_SMALL = 11
SIZE_TINY = 10

# --- component metrics from the mockup's component list -----------------
#: Confidence at or below this is "low" and gets a gold marker and left bar.
LOW_CONFIDENCE = 0.70

#: TxnTable fixed column widths; narration is the one stretch column.
#:
#: Widened from the mockup's 26/46/82/30/1fr/104/104/124/132/54. Those were
#: measured against a browser's proportional face; in Qt with the tabular
#: monospace this design requires, they clip the very figures the screen exists
#: to show -- "72,15,895.72 Dr" became "72,15,895.7…" and a truncated balance
#: is worse than useless on a reconciliation screen. The proportions are kept;
#: only the money and date columns grew.
TXN_COLUMN_WIDTHS = (26, 46, 112, 34, 0, 122, 122, 152, 112, 58)
TXN_STRETCH_COLUMN = 4

AUDIT_DRAWER_WIDTH = 520
INLINE_PROMPT_HEIGHT = 36
#: OverrideDialog refuses to submit until the reason is at least this long.
OVERRIDE_REASON_MINIMUM = 12


@dataclass(frozen=True, slots=True)
class RowTint:
    """Left-bar colour and row wash for one transaction row state."""

    bar: str | None = None
    wash: str | None = None
    text: str | None = None


#: Row states, in the order the mockup lists them. `unreadable` is the only one
#: that colours the narration itself -- it means the figures could not be
#: trusted at all, which is a different claim from "we are unsure".
ROW_NORMAL = RowTint()
ROW_LOW_CONFIDENCE = RowTint(bar=ACCENT)
ROW_UNCLASSIFIED = RowTint(bar=BAD)
ROW_UNREADABLE = RowTint(bar=BAD, wash=BAD_WASH, text=BAD)
ROW_SELECTED = RowTint(wash=ACCENT_100)


def qss() -> str:
    """Application-wide stylesheet for the shared chrome."""
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: "{FONT_BODY}";
        font-size: {SIZE_BODY}pt;
    }}
    QLabel[role="title"] {{
        font-family: "{FONT_HEADING}";
        font-size: {SIZE_TITLE}pt;
        font-weight: {HEADING_WEIGHT};
    }}
    QLabel[role="heading"] {{
        font-family: "{FONT_HEADING}";
        font-size: {SIZE_HEADING}pt;
        font-weight: {HEADING_WEIGHT};
    }}
    QLabel[role="muted"] {{ color: {NEUTRAL_600}; font-size: {SIZE_SMALL}pt; }}
    QLabel[role="mono"]  {{ font-family: "{FONT_MONO}"; }}
    QFrame[role="hairline"] {{ background: {HAIRLINE}; border: none; }}
    QPushButton {{
        background: {NEUTRAL_100};
        border: 1px solid {DIVIDER};
        border-radius: {RADIUS_MD}px;
        padding: {SPACE_2}px {SPACE_3}px;
    }}
    QPushButton:hover:enabled {{ border-color: {ACCENT}; }}
    QPushButton:disabled {{ color: {NEUTRAL_500}; background: {NEUTRAL_200}; }}
    QPushButton[role="primary"] {{
        background: {ACCENT}; color: {NEUTRAL_100}; border-color: {ACCENT_600};
    }}
    QPushButton[role="primary"]:disabled {{
        background: {NEUTRAL_300}; color: {NEUTRAL_500}; border-color: {DIVIDER};
    }}
    QTableView {{
        background: {NEUTRAL_100};
        gridline-color: transparent;
        selection-background-color: {ACCENT_100};
        selection-color: {TEXT};
        border: 1px solid {DIVIDER};
    }}
    QHeaderView::section {{
        background: {SURFACE};
        border: none;
        border-bottom: 1px solid {HAIRLINE};
        padding: {SPACE_2}px;
        font-size: {SIZE_SMALL}pt;
        color: {NEUTRAL_700};
    }}
    QLineEdit, QPlainTextEdit {{
        background: {NEUTRAL_100};
        border: 1px solid {DIVIDER};
        border-radius: {RADIUS_SM}px;
        padding: {SPACE_1}px {SPACE_2}px;
    }}
    QLineEdit[confidence="low"] {{ border: 1px solid {ACCENT}; background: {ACCENT_100}; }}
    /* Qt's default progress chunk is a saturated system blue, which is the one
       colour this design must not contain: it reads as a status signal and
       competes with the green/red reserved for the reconciliation verdict. */
    QProgressBar {{
        background: {NEUTRAL_200};
        border: 1px solid {DIVIDER};
        border-radius: {RADIUS_SM}px;
        text-align: center;
        font-size: {SIZE_TINY}pt;
        color: {NEUTRAL_800};
    }}
    QProgressBar::chunk {{ background: {ACCENT_300}; }}
    QListWidget {{ border: none; }}
    QSplitter::handle {{ background: {HAIRLINE}; }}
    QRadioButton {{ padding: {SPACE_1}px 0; }}
    """
