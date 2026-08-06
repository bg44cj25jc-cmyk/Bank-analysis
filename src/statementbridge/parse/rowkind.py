"""Classify every assembled line before it is allowed near the frame.

The traps in these statements are not exotic, but they are fatal: a single
``Page Total Credit :`` line admitted as a transaction doubles a page, and a
repeated mid-file header can inject a bogus balance that derails the chain.

Matching is *not* done with exact regexes. On a 150 DPI dot-matrix scan
``Page Total Credit`` plausibly comes back as ``Paqe Tota1 Credit``, and an
exact pattern would wave it straight through into the transaction frame. So
each line is first canonicalised -- the glyph classes that dot-matrix OCR
actually confuses are collapsed onto one representative -- and matched in that
space, with a fuzzy ratio as a second chance for heavier damage.

Canonicalisation is what makes this robust rather than merely lenient:
``Paqe Tota1 Credit`` and ``Page Total Credit`` both reduce to the identical
string ``pagetotalcredlt``, so the match is exact even though the OCR was not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, Sequence

from rapidfuzz import fuzz

from ..money import parse_amount
from .frame import Anchor


class RowKind(str, Enum):
    TRANSACTION = "TRANSACTION"
    PAGE_TOTAL = "PAGE_TOTAL"
    HEADER_REPEAT = "HEADER_REPEAT"
    SEPARATOR = "SEPARATOR"
    LIMITS_TABLE = "LIMITS_TABLE"
    OPENING = "OPENING"
    BLANK_FILLER = "BLANK_FILLER"
    CARRY_FORWARD = "CARRY_FORWARD"

    @property
    def is_transaction(self) -> bool:
        return self is RowKind.TRANSACTION


#: Glyphs that low-DPI and dot-matrix OCR interchange, collapsed onto a single
#: representative so both the observed text and the reference pattern land on
#: the same canonical string.
#:
#: Public because :mod:`statementbridge.rules.normalise` matches narrations in
#: the same space. Two copies of this table would drift apart, and the one that
#: drifted would fail silently -- a rule that simply stops matching looks
#: exactly like a transaction that was never there.
CANON_MAP: Final[dict[str, str]] = {
    "0": "o", "1": "l", "i": "l", "|": "l", "!": "l",
    "2": "z", "5": "s", "6": "g", "9": "g", "q": "g",
    "8": "b",
}

_NON_ALPHA: Final[re.Pattern[str]] = re.compile(r"[^a-z]")
_SEPARATOR_CHARS: Final[re.Pattern[str]] = re.compile(r"[.\-_=*~+·:\s]")
#: Trailing money-ish token, tolerant of the letters OCR substitutes for digits.
_TRAILING_NUMBER: Final[re.Pattern[str]] = re.compile(
    r"([\dOolISsBbZzGgqQ][\dOolISsBbZzGgqQ.,]{2,})\s*(DR|CR)?\.?\s*$", re.IGNORECASE
)

_FUZZY_THRESHOLD: Final[int] = 88


def canon(text: str) -> str:
    """Reduce a line to the alphabet-only form used for trap matching."""
    lowered = text.lower()
    mapped = "".join(CANON_MAP.get(char, char) for char in lowered)
    return _NON_ALPHA.sub("", mapped)


#: (kind, phrase, label). Order is significant -- the first hit wins, so the
#: specific anchors are listed ahead of the generic header text they contain.
_PATTERNS: Final[tuple[tuple[RowKind, str, str], ...]] = (
    (RowKind.PAGE_TOTAL, "page total credit", "PAGE_TOTAL_CREDIT"),
    (RowKind.PAGE_TOTAL, "page total debit", "PAGE_TOTAL_DEBIT"),
    (RowKind.PAGE_TOTAL, "total credit for the page", "PAGE_TOTAL_CREDIT"),
    (RowKind.PAGE_TOTAL, "total debit for the page", "PAGE_TOTAL_DEBIT"),

    (RowKind.OPENING, "brought forward", "BF_BALANCE"),
    (RowKind.OPENING, "bf balance", "BF_BALANCE"),
    (RowKind.OPENING, "b f balance", "BF_BALANCE"),
    (RowKind.OPENING, "opening balance", "OPENING_BALANCE"),

    (RowKind.CARRY_FORWARD, "carried forward", "CF_BALANCE"),
    (RowKind.CARRY_FORWARD, "carry forward", "CF_BALANCE"),
    (RowKind.CARRY_FORWARD, "cf balance", "CF_BALANCE"),
    (RowKind.CARRY_FORWARD, "closing balance", "CLOSING_BALANCE"),

    (RowKind.LIMITS_TABLE, "draw power", "LIMITS"),
    (RowKind.LIMITS_TABLE, "drawing power", "LIMITS"),
    (RowKind.LIMITS_TABLE, "int rate", "LIMITS"),
    (RowKind.LIMITS_TABLE, "interest rate", "LIMITS"),
    (RowKind.LIMITS_TABLE, "sanction limit", "LIMITS"),

    (RowKind.SEPARATOR, "order by gl date", "SORT_NOTE"),
    (RowKind.SEPARATOR, "order by gl", "SORT_NOTE"),
    (RowKind.SEPARATOR, "continued", "CONTINUATION_NOTE"),

    # Distinctive header phrases only. Generic single words such as "balance",
    # "deposit" or "particulars" are deliberately NOT listed: a narration like
    # "CASH DEPOSIT" or "MIN BALANCE CHARGES" would match them and a real
    # transaction would be dropped. Column-header rows are instead detected
    # structurally, by _looks_like_column_header below.
    (RowKind.HEADER_REPEAT, "service outlet", "HEADER"),
    (RowKind.HEADER_REPEAT, "peg review date", "HEADER"),
    (RowKind.HEADER_REPEAT, "account number", "HEADER"),
    (RowKind.HEADER_REPEAT, "statement of account", "HEADER"),
    (RowKind.HEADER_REPEAT, "printed on", "HEADER"),
)

#: Tokens that appear in a column-header row. No single one is conclusive --
#: the test is that several occur together on a line carrying no money figure.
_HEADER_TOKENS: Final[tuple[str, ...]] = tuple(
    canon(token)
    for token in (
        "date", "value date", "particulars", "description", "narration",
        "instrument", "chq no", "cheque", "ref no", "withdrawal", "deposit",
        "debit", "credit", "balance", "branch", "account no", "sl no",
    )
)
_HEADER_TOKEN_MINIMUM: Final[int] = 3

#: Any money figure at all -- a header row has none.
_HAS_MONEY: Final[re.Pattern[str]] = re.compile(r"\d[\d,]*\.\d{2}")

_CANON_PATTERNS: Final[tuple[tuple[RowKind, str, str], ...]] = tuple(
    (kind, canon(phrase), label) for kind, phrase, label in _PATTERNS
)


@dataclass(slots=True)
class LineClass:
    kind: RowKind
    label: str = ""
    anchor: Anchor | None = None
    reason: str = ""


def classify_line(
    text: str,
    *,
    page_no: int = 0,
    source_row: int = 0,
    extra_patterns: Sequence[tuple[RowKind, str, str]] = (),
) -> LineClass:
    """Type one assembled line.

    ``extra_patterns`` lets a bank profile contribute layout-specific traps
    without touching this module.
    """
    if not text or not text.strip():
        return LineClass(RowKind.BLANK_FILLER, "EMPTY", reason="blank")

    stripped = text.strip()
    canonical = canon(stripped)

    # A rule line, a row of dots, or a shaded filler leaves almost no letters.
    if len(canonical) < 3:
        residue = _SEPARATOR_CHARS.sub("", stripped)
        if not residue:
            return LineClass(RowKind.SEPARATOR, "RULE", reason="separator glyphs only")
        if not canonical:
            return LineClass(RowKind.BLANK_FILLER, "NO_TEXT", reason="no alphabetic content")

    candidates = tuple(
        (kind, canon(phrase), label) for kind, phrase, label in extra_patterns
    ) + _CANON_PATTERNS

    for kind, phrase, label in candidates:
        if phrase and phrase in canonical:
            return _build(kind, label, stripped, page_no, source_row, "canonical match")

    if _looks_like_column_header(canonical, stripped):
        return LineClass(
            RowKind.HEADER_REPEAT, "COLUMN_HEADER", reason="header tokens, no money"
        )

    # Heavier damage: fall back to a fuzzy comparison, still in canonical space.
    for kind, phrase, label in candidates:
        if len(phrase) < 8:
            continue  # short phrases fuzzy-match far too readily
        if fuzz.partial_ratio(phrase, canonical) >= _FUZZY_THRESHOLD:
            return _build(kind, label, stripped, page_no, source_row, "fuzzy match")

    return LineClass(RowKind.TRANSACTION, "TXN")


def _looks_like_column_header(canonical: str, text: str) -> bool:
    """Detect a repeated column-header row structurally rather than by phrase.

    A header row stacks several column names and carries no money figure. Any
    one of those names can legitimately appear in a narration, so the signal is
    the combination, never a single token.
    """
    if _HAS_MONEY.search(text):
        return False
    hits = sum(1 for token in _HEADER_TOKENS if token and token in canonical)
    return hits >= _HEADER_TOKEN_MINIMUM


def _build(
    kind: RowKind, label: str, text: str, page_no: int, source_row: int, reason: str
) -> LineClass:
    anchor = None
    if kind in (RowKind.PAGE_TOTAL, RowKind.OPENING, RowKind.CARRY_FORWARD):
        anchor = _extract_anchor(label, text, page_no, source_row)
    return LineClass(kind, label, anchor=anchor, reason=reason)


def _extract_anchor(label: str, text: str, page_no: int, source_row: int) -> Anchor:
    """Pull the figure off an anchor line so it can verify the chain."""
    value: Decimal | None = None
    marker: str | None = None
    match = _TRAILING_NUMBER.search(text)
    if match:
        parsed = parse_amount(match.group(1))
        value = parsed.value
        marker = (match.group(2) or parsed.sign_hint or "").upper() or None
    return Anchor(
        kind=label,
        page_no=page_no,
        source_row=source_row,
        value=value,
        marker=marker,
        raw=text,
    )
