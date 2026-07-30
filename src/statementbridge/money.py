"""Decimal-only money handling for Indian bank statements.

Every figure in this application is a :class:`decimal.Decimal` quantised to two
places. Floats are never used anywhere in the pipeline: the acceptance bar is a
paisa-exact reconciliation, and binary floating point cannot represent 0.01
exactly. The client's existing sample workbook shows exactly this failure mode
(a closing balance of ``3240.71999999997`` and a reconciliation variance of
``-2.77e-11``); with Decimal both come out exact.

The parser here is deliberately forgiving of OCR damage but never silently
creative: anything it had to repair, or anything that does not fit the Indian
lakh grouping, is reported on the result so the balance engine and the review
screen can weigh it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Final

TWO_PLACES: Final[Decimal] = Decimal("0.01")
ZERO: Final[Decimal] = Decimal("0.00")

#: Character confusions produced by dot-matrix and low-DPI scans. Applied only
#: inside a field already known to be numeric, and only after any Dr/Cr suffix
#: has been stripped -- otherwise the "D" of "Dr" would itself be rewritten.
OCR_DIGIT_CONFUSIONS: Final[dict[str, str]] = {
    "O": "0", "o": "0", "Q": "0",
    "l": "1", "I": "1", "i": "1", "|": "1", "]": "1", "[": "1",
    "S": "5", "s": "5", "$": "5",
    "B": "8",
    "Z": "2", "z": "2",
    "G": "6", "b": "6",
    "g": "9", "q": "9",
}

#: Indian lakh grouping for the integer part: 2,2,...,3 from the right.
#: e.g. 4,06,40,716 and 12,34,567 and 1,234 and 131 all pass.
_INDIAN_GROUPING: Final[re.Pattern[str]] = re.compile(
    r"^(\d{1,3}|\d{1,2}(?:,\d{2})*,\d{3})$"
)

#: A separator followed by exactly two digits at end-of-string. Because the
#: final integer group in Indian notation is always three digits, a two-digit
#: tail can only ever be the paise -- which resolves comma-vs-period ambiguity
#: regardless of which character the OCR actually emitted.
_DECIMAL_TAIL: Final[re.Pattern[str]] = re.compile(r"[.,](\d{2})$")

#: A separator plus exactly two digits, anywhere. The last one in a field marks
#: where the paise end and any trailing OCR debris begins.
_PAISE_GROUP: Final[re.Pattern[str]] = re.compile(r"[.,]\d{2}")

#: Digits as the dot-matrix scans render them. Letters are admitted inside a
#: money token because "30,57,118.72" comes back as "30,57,11B.72", and a
#: digits-only pattern would match the "30,57,11" prefix and silently report a
#: balance a thousand times too small.
_MONEY_DIGIT: Final[str] = r"[\dOoIlSsBbZzGgQq]"

#: A money figure mid-line. The lookbehind stops a match beginning part-way
#: through a reference number: without it "PUNBHG...071760 36,199.06" matches
#: from the "760" and yields 7,60,36,199.06.
MONEY_TOKEN: Final[re.Pattern[str]] = re.compile(
    rf"(?<![0-9A-Za-z]){_MONEY_DIGIT}{{1,3}}"
    rf"(?:[,\s]{{1,2}}{_MONEY_DIGIT}{{2,3}})*[.,]{_MONEY_DIGIT}{{2}}"
)

#: The same shape without the space tolerance, used to re-cut a token whose
#: spaces turned out to be a false join rather than a misread comma.
_MONEY_TOKEN_STRICT: Final[re.Pattern[str]] = re.compile(
    rf"(?<![0-9A-Za-z]){_MONEY_DIGIT}{{1,3}}"
    rf"(?:,{_MONEY_DIGIT}{{2,3}})*[.,]{_MONEY_DIGIT}{{2}}"
)


def find_money_tokens(text: str) -> list[tuple[str, int, int]]:
    """Locate every money figure in a line, as (token, start, end).

    A space inside a number is genuinely ambiguous on these scans: it is either
    a misread comma ("1, 80,000.00") or the gap between a reference number and
    the amount that follows it ("...071760 36,199.06"). Indian grouping settles
    it -- the first reading validates as 2,2,3 and the second does not -- so the
    token is accepted only if it forms a legal number, and re-cut if not.
    """
    found: list[tuple[str, int, int]] = []
    for match in MONEY_TOKEN.finditer(text):
        token, start, end = match.group(0), match.start(), match.end()
        if " " in token and not parse_amount(token).grouping_ok:
            tail = list(_MONEY_TOKEN_STRICT.finditer(token))
            if not tail:
                continue
            last = tail[-1]
            token = last.group(0)
            start, end = start + last.start(), start + last.end()
        found.append((token, start, end))
    return found

_CURRENCY_NOISE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)(?:rs\.?|inr|₹)\s*", re.IGNORECASE
)
_DRCR_SUFFIX: Final[re.Pattern[str]] = re.compile(
    r"\s*\b(dr|cr)\b\.?\s*$", re.IGNORECASE
)
#: SBI glues the marker straight onto the figure: "1,97,817.10CR".
_DRCR_GLUED: Final[re.Pattern[str]] = re.compile(r"(?<=\d)\s*(DR|CR)\.?\s*$", re.IGNORECASE)


def q2(value: Decimal | int | str) -> Decimal:
    """Quantise to two decimal places. The only rounding in the codebase."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO_PLACES)


@dataclass(slots=True)
class ParsedAmount:
    """Outcome of reading one numeric field off a statement line."""

    raw: str
    value: Decimal | None = None
    sign_hint: str | None = None          # "DR" | "CR" | None
    repairs: tuple[str, ...] = ()
    grouping_ok: bool = True
    has_paise: bool = True
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None

    @property
    def suspect(self) -> bool:
        """True when the read succeeded but something about it smells.

        A suspect amount is still usable -- the balance chain will cross-check
        it -- but it lowers the row's confidence and makes it a prime candidate
        when the repair engine has to choose which field to distrust.
        """
        return bool(self.repairs) or not self.grouping_ok or not self.has_paise


def parse_amount(raw: str | None, *, repair_ocr: bool = True) -> ParsedAmount:
    """Read an Indian-format money figure out of a (possibly mangled) string."""
    if raw is None:
        return ParsedAmount(raw="", note="empty")
    text = raw.strip()
    if not text:
        return ParsedAmount(raw=raw, note="empty")

    result = ParsedAmount(raw=raw)
    work = _CURRENCY_NOISE.sub(" ", text).strip()

    # Dr/Cr must come off before digit repair, glued form first.
    for pattern in (_DRCR_GLUED, _DRCR_SUFFIX):
        match = pattern.search(work)
        if match:
            result.sign_hint = match.group(1).upper()
            work = work[: match.start()].strip()
            break

    work = work.replace(" ", "")
    # A leading/trailing minus is a legitimate sign, not a separator.
    negative = work.startswith("-") or work.endswith("-")
    work = work.strip("-")

    # Whatever survives after the paise is a mangled Dr/Cr marker, not digits.
    # On the Gramin dot-matrix scans "Dr" comes back as "0r", "De", "b" or
    # "0" among others, and the leading glyph is a digit. Trimming only the
    # letters would leave that digit welded to the figure -- ".720r" would
    # become ".720" and read as a hundredfold error -- so the cut is made at
    # the paise instead, which is unambiguous.
    tail_marker = ""
    matches = list(_PAISE_GROUP.finditer(work))
    if matches:
        last = matches[-1]
        remainder = work[last.end():]
        if remainder and not remainder.isdigit():
            tail_marker = remainder
            work = work[: last.end()]
    if tail_marker and result.sign_hint is None:
        # Only claim a direction when the marker is still legible. A guess here
        # would be worse than nothing: the balance chain derives direction from
        # the delta and does not need this.
        head = tail_marker[0].upper()
        if head == "C":
            result.sign_hint = "CR"
        elif head == "D":
            result.sign_hint = "DR"

    if repair_ocr:
        repaired, notes = _repair_digits(work)
        if notes:
            work, result.repairs = repaired, notes

    if not work or not re.fullmatch(r"[\d.,]+", work):
        result.note = "no numeric content"
        return result

    # Split the paise off, then strip every remaining separator.
    tail = _DECIMAL_TAIL.search(work)
    if tail:
        integer_part, paise = work[: tail.start()], tail.group(1)
    else:
        integer_part, paise = work, "00"
        result.has_paise = False
        result.note = "no decimal point in source"

    integer_digits = integer_part.replace(",", "").replace(".", "")
    if not integer_digits:
        integer_digits = "0"

    # Grouping is validated on the original text: a group that breaks the
    # 2,2,3 rule means a separator was inserted, dropped or misread.
    if "," in integer_part or "." in integer_part:
        normalised_groups = integer_part.replace(".", ",")
        result.grouping_ok = bool(_INDIAN_GROUPING.match(normalised_groups))
        if not result.grouping_ok:
            result.note = (result.note + "; " if result.note else "") + "irregular grouping"

    try:
        value = Decimal(f"{integer_digits}.{paise}")
    except InvalidOperation:
        result.note = "undecodable"
        return result

    result.value = q2(-value if negative else value)
    return result


def _repair_digits(text: str) -> tuple[str, tuple[str, ...]]:
    """Map known OCR letter/digit confusions inside a numeric field."""
    out: list[str] = []
    notes: list[str] = []
    for char in text:
        replacement = OCR_DIGIT_CONFUSIONS.get(char)
        if replacement is not None:
            out.append(replacement)
            notes.append(f"{char}->{replacement}")
        else:
            out.append(char)
    return "".join(out), tuple(notes)


def format_indian(value: Decimal, *, blank_zero: bool = False) -> str:
    """Format with lakh grouping and exactly two decimals: ``90,98,371.22``."""
    value = q2(value)
    if blank_zero and value == 0:
        return ""
    sign = "-" if value < 0 else ""
    digits = f"{abs(value):.2f}"
    integer_part, paise = digits.split(".")
    if len(integer_part) > 3:
        head, last3 = integer_part[:-3], integer_part[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        integer_part = ",".join(groups + [last3])
    return f"{sign}{integer_part}.{paise}"


def format_drcr(signed: Decimal) -> str:
    """Render a signed balance the way the statement prints it.

    Internally the pipeline carries one uniform convention -- credit positive,
    debit negative -- so an overdraft or cash-credit account crossing zero
    needs no special handling. The Dr/Cr marker is purely presentational and is
    applied here, at the edge.
    """
    signed = q2(signed)
    if signed == 0:
        return f"{format_indian(ZERO)} Cr"
    marker = "Cr" if signed > 0 else "Dr"
    return f"{format_indian(abs(signed))} {marker}"


def signed_from_drcr(magnitude: Decimal, marker: str | None) -> Decimal:
    """Convert a printed magnitude plus Dr/Cr marker into the signed model."""
    magnitude = q2(abs(magnitude))
    if marker and marker.upper().startswith("D"):
        return -magnitude
    return magnitude
