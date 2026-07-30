"""Pull the fields out of one assembled transaction line.

Written against what Tesseract actually returns from the fixtures rather than
what the statements look like to a human. A representative Gramin line:

    02-05-2025 82-05-2025 267632 HEFT TO: KEW RC MEDICAL AGENCY PUNSNG2025
    05020307 66,635.00 23,01,626.72Dr 11931XC 8G951AD

Three things about that shape the extraction:

* The two amount columns (debit and credit) collapse into one token in the OCR
  text, and which column it came from is unrecoverable. That does not matter --
  direction comes from the balance delta, never from column position.
* The running balance is *not* the last token: two user-id columns follow it.
  So fields are located by shape, not by position from the end.
* User ids like ``11931XC`` and instrument numbers like ``267632`` contain long
  digit runs but no decimal point, so a money pattern anchored on the paise
  separates them cleanly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from ..money import MONEY_TOKEN, find_money_tokens, parse_amount
from .frame import Txn

#: Digits as OCR may render them, for fields we already know are numeric.
_DIGITISH: Final[str] = r"[\dOolISsBbZzGgqQ]"

#: A date, tolerating the separators the dot-matrix scans produce ("92-05+2025").
DATE_TOKEN: Final[re.Pattern[str]] = re.compile(
    rf"\b({_DIGITISH}{{2}})\s*[-/+.\s]\s*({_DIGITISH}{{2}})\s*[-/+.\s]\s*({_DIGITISH}{{4}})\b"
)

#: A bare reference number: a run of digits with no decimal point.
INSTRUMENT_TOKEN: Final[re.Pattern[str]] = re.compile(r"\b\d{5,10}\b")

_DIGIT_FIX: Final[dict[int, str]] = str.maketrans(
    {"O": "0", "o": "0", "Q": "0", "l": "1", "I": "1", "i": "1",
     "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2", "G": "6",
     "b": "6", "g": "9", "q": "9"}
)


@dataclass(slots=True)
class LineFields:
    """What one line yielded, before the balance chain has had its say."""

    dates: list[date]
    amounts: list[Decimal]
    raw_money: list[str]
    instrument: str
    narration: str
    balance_marker: str | None = None


def _to_date(groups: tuple[str, str, str]) -> date | None:
    day, month, year = (part.translate(_DIGIT_FIX) for part in groups)
    try:
        value = date(int(year), int(month), int(day))
    except ValueError:
        return None
    # A bank statement dated outside living memory is an OCR artefact, not a
    # transaction -- the Gramin header carries "Peg Review date : 31-12-2099".
    if not (1990 <= value.year <= 2099):
        return None
    return value


def extract_fields(text: str) -> LineFields:
    dates: list[date] = []
    for match in DATE_TOKEN.finditer(text):
        parsed = _to_date(match.groups())
        if parsed is not None:
            dates.append(parsed)

    tokens = find_money_tokens(text)
    raw_money = [token for token, _, _ in tokens]
    amounts: list[Decimal] = []
    marker: str | None = None
    for index, token in enumerate(raw_money):
        parsed = parse_amount(token)
        if parsed.value is not None:
            amounts.append(parsed.value)
            if index == len(raw_money) - 1:
                marker = parsed.sign_hint

    # Everything of interest sits to the left of the first money figure. The
    # columns to the right of the balance are the entry and verifying user ids,
    # which would otherwise be scavenged for an instrument number and dragged
    # into the narration.
    head = text[: tokens[0][1]] if tokens else text

    residue = DATE_TOKEN.sub(" ", head)
    instrument = ""
    instrument_match = INSTRUMENT_TOKEN.search(residue)
    if instrument_match:
        instrument = instrument_match.group(0)
        residue = residue[: instrument_match.start()] + " " + residue[instrument_match.end():]

    narration = re.sub(r"\s{2,}", " ", residue).strip(" :;.-")
    return LineFields(
        dates=dates,
        amounts=amounts,
        raw_money=raw_money,
        instrument=instrument,
        narration=narration,
        balance_marker=marker,
    )


def build_txn(
    text: str, *, page_no: int, source_row: int, is_overdraft: bool = False
) -> Txn | None:
    """Turn a transaction line into a row, or None if it carries no transaction.

    The balance is stored signed under the uniform convention. On an overdraft
    or cash-credit account the printed figure is a debit, so it is negated; the
    printed Dr/Cr marker is used only when it survived OCR legibly enough to be
    trusted, because on these scans it frequently does not.
    """
    fields = extract_fields(text)
    if len(fields.amounts) < 2:
        return None  # no amount-plus-balance pair: not a settled transaction

    *_, printed_amount, printed_balance = fields.amounts

    marker = fields.balance_marker
    if marker == "DR":
        balance = -printed_balance
    elif marker == "CR":
        balance = printed_balance
    else:
        balance = -printed_balance if is_overdraft else printed_balance

    return Txn(
        page_no=page_no,
        source_row=source_row,
        date=fields.dates[0] if fields.dates else None,
        value_date=fields.dates[1] if len(fields.dates) > 1 else None,
        instrument_no=fields.instrument,
        narration=fields.narration,
        balance=balance,
        printed_amount=printed_amount,
        printed_marker=marker,
        raw_amount_text=fields.raw_money[-2] if len(fields.raw_money) >= 2 else "",
        raw_balance_text=fields.raw_money[-1] if fields.raw_money else "",
    )
