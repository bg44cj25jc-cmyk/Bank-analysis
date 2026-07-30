"""Per-bank layout description.

The parsers are generic; everything bank-specific lives here as data. The firm
will onboard many more banks than the two in the fixtures, and each one should
be a new profile rather than a new branch in the extraction code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..rowkind import RowKind


@dataclass(frozen=True, slots=True)
class BankProfile:
    key: str
    name: str

    #: True when the statement is a ruled table whose rows may span several
    #: printed lines. Such a page is read by row band rather than by text line;
    #: see ocr/table.py. False means a dot-matrix ledger, one line per row.
    ruled_table: bool = False

    #: True for cash-credit and overdraft accounts, where the printed balance is
    #: a debit figure that grows on debit. Only used to seed the opening sign:
    #: every subsequent direction comes from the balance delta, so a wrong guess
    #: here cannot silently flip individual transactions.
    is_overdraft: bool = False

    #: Layout-specific trap lines, contributed to the shared row classifier.
    extra_patterns: tuple[tuple[RowKind, str, str], ...] = ()

    #: Money figures on a settled transaction line: the amount and the running
    #: balance. Banks that print both a debit and a credit column still show
    #: only one of them populated per row.
    money_tokens_expected: int = 2

    #: Regexes for pulling account identity out of the header block.
    account_no_pattern: str | None = None
    holder_pattern: str | None = None

    def patterns(self) -> Sequence[tuple[RowKind, str, str]]:
        return self.extra_patterns


_REGISTRY: dict[str, BankProfile] = {}


def register(profile: BankProfile) -> BankProfile:
    _REGISTRY[profile.key] = profile
    return profile


def get_profile(key: str) -> BankProfile:
    if key not in _REGISTRY:
        raise KeyError(f"unknown bank profile {key!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[key]


def all_profiles() -> list[BankProfile]:
    return list(_REGISTRY.values())


def detect_profile(text: str) -> BankProfile | None:
    """Identify the bank from the first page's text, if we recognise it."""
    from ..rowkind import canon

    canonical = canon(text)
    best: tuple[int, BankProfile] | None = None
    for profile in _REGISTRY.values():
        score = sum(
            1 for _, phrase, _ in profile.extra_patterns if canon(phrase) in canonical
        )
        if score and (best is None or score > best[0]):
            best = (score, profile)
    return best[1] if best else None
