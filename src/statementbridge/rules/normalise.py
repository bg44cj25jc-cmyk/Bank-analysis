"""Reducing a narration to the words a rule can be written against.

``parse.rowkind.canon`` already solves the OCR half of this problem, and its
glyph table is reused here rather than copied. But ``canon`` cannot be used
directly on a narration, because it maps digits onto letters and *then* deletes
every non-letter. Applied to::

    IMPS-532116454511-BISHAL NAG-UCBA0002520

that yields ``lmpsszzllgssgslsblshalnagucbaooozszo`` -- a reference number
dissolved into the words, where any short rule token can find a spurious match.
The reference is not noise to be tolerated; it is noise to be removed, and it
can be, because it is structurally distinct from a word.

So a narration is split on punctuation and each token is judged, in this order:

* all digits -- kept separately as a number, however long. Cheque numbers matter
  (a bare cheque number and a branch name is a recognisable kind of credit), but
  a digit run is never a word, and canonicalising ``1820`` into ``lbzo`` would
  put four letters of pure noise where a rule might match them. How long a
  number has to be to be a cheque number rather than a UTR is a judgement about
  banking, so it is made by the structural predicate that cares, not here;
* mixed, mostly digits, and six characters or longer -- a reference, an IFSC, a
  masked card number. Dropped. Only *mostly* digits, because on a dot-matrix
  scan ``PAYMENT`` comes back as ``PAYM3NT`` and a rule that deleted every token
  containing a digit would delete the word it needed;
* anything else -- a word, canonicalised for OCR damage.

The result is that ``UPI/CR/BISHAL NAG/AXL`` and a scanned copy of it both
reduce to the same five words, which is what lets a rule read as "UPI, inward"
and still work at 150 DPI.

**Direction is not taken from the narration.** The ``CR`` and ``DR`` tokens are
kept as words, but no rule in the default pack matches on them: direction comes
from the balance movement, which is checked against every neighbouring row,
while the token is one more thing the recogniser can lose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..parse.rowkind import CANON_MAP

#: Narrations are punctuated with anything: ``UPI/CR/…``, ``IMPS-…-…``,
#: ``EEB MBL PF CHARGES``, ``OBO INITIATED: …``.
_SPLIT: Final[re.Pattern[str]] = re.compile(r"[^0-9A-Za-z]+")
_DIGITS: Final[re.Pattern[str]] = re.compile(r"\d")
_NON_ALPHA: Final[re.Pattern[str]] = re.compile(r"[^a-z]")

#: Shortest token that can be a reference rather than a word. Below this,
#: ``XX42`` and ``SB522`` are as likely to be meaningful as not.
_REFERENCE_MINIMUM: Final[int] = 6


def _is_reference(token: str) -> bool:
    """A transaction reference, not a word: long, and more digits than letters.

    Only reached for mixed tokens; a pure digit run is a number, not a
    reference, whatever its length.
    """
    if len(token) < _REFERENCE_MINIMUM:
        return False
    return len(_DIGITS.findall(token)) * 2 > len(token)


def canon_word(token: str) -> str:
    """Collapse one token onto the OCR-canonical alphabet of ``parse.rowkind``."""
    lowered = token.lower()
    mapped = "".join(CANON_MAP.get(char, char) for char in lowered)
    return _NON_ALPHA.sub("", mapped)


@dataclass(frozen=True, slots=True)
class Narration:
    """One narration, ready to be matched."""

    raw: str
    #: Canonicalised alphabetic tokens, in the order they were printed.
    words: tuple[str, ...] = ()
    #: Pure-digit tokens exactly as printed: cheque numbers, short codes.
    numbers: tuple[str, ...] = ()
    #: Tokens dropped as references. Kept so a rule author can see what was
    #: discarded rather than wonder why a pattern never fires.
    references: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """The words as one string, for fuzzy comparison."""
        return " ".join(self.words)

    def has(self, word: str) -> bool:
        """Is this exact canonical word present?"""
        return word in self.words


def narration(raw: str) -> Narration:
    """Split and canonicalise a narration."""
    words: list[str] = []
    numbers: list[str] = []
    references: list[str] = []

    for token in _SPLIT.split(raw or ""):
        if not token:
            continue
        if token.isdigit():
            numbers.append(token)
        elif _is_reference(token):
            references.append(token)
        else:
            canonical = canon_word(token)
            if canonical:
                words.append(canonical)

    return Narration(
        raw=raw or "",
        words=tuple(words),
        numbers=tuple(numbers),
        references=tuple(references),
    )


#: Titles that precede a name on an Indian bank statement and are not part of
#: it. ``MR. AJOY NAG`` and ``AJOY NAG`` must match each other, or self-transfer
#: detection fails on every account whose header was typed politely.
_HONORIFICS: Final[frozenset[str]] = frozenset(
    canon_word(title)
    for title in ("mr", "mrs", "ms", "miss", "shri", "smt", "sri", "dr", "m/s", "messrs")
)


#: A leading title, as a header actually prints one. Matched on the raw string
#: rather than on tokens because ``M/S`` splits into two single letters.
_HONORIFIC_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"^\s*(m/s|messrs|mrs|mr|ms|miss|shri|smt|sri|dr)\.?\s+", re.IGNORECASE
)


def display_name(holder: str | None) -> str:
    """A holder's name as it should read on a ledger, not as the header shouts it.

    A header gives ``MR. AJOY NAG``; the ledger the firm actually keeps is
    ``Ajoy Nag - Own Accounts``. The title is dropped and an all-capitals name is
    title-cased -- but only an all-capitals one, because a name that already
    carries deliberate casing (``ABC Enterprises Pvt Ltd``) is better left alone
    than retyped.
    """
    if not holder or not holder.strip():
        return ""
    cleaned = _HONORIFIC_PREFIX.sub("", holder.strip(), count=1).strip()
    return cleaned.title() if cleaned.isupper() else cleaned


def name_words(holder: str | None) -> tuple[str, ...]:
    """The canonical words of an account holder's name, honorifics removed.

    Single-letter initials go too: ``A NAG`` would otherwise match any narration
    containing a stray ``a``.
    """
    if not holder:
        return ()
    return tuple(
        word
        for word in narration(holder).words
        if word not in _HONORIFICS and len(word) > 1
    )
