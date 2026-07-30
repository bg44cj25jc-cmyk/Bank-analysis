"""Tripura Gramin Bank — cash-credit ledger (dot-matrix).

Trap phrases are taken from what Tesseract actually returns on the fixture, not
from how the page reads to a human. The classifier canonicalises confusable
glyphs before matching, so the clean spelling is what belongs here even though
the scan yields "Service QutLet", "TRIPURA GRAKIN BANK" and "Customer Account
Lecger Report".
"""

from __future__ import annotations

from ..rowkind import RowKind
from .base import BankProfile, register

GRAMIN_CC = register(
    BankProfile(
        key="gramin_cc",
        name="Tripura Gramin Bank — Cash Credit ledger",
        # The printed balance is a debit figure that grows on debit and can
        # cross into credit mid-statement. Only the opening sign depends on
        # this; every later direction comes from the balance delta.
        is_overdraft=True,
        extra_patterns=(
            (RowKind.HEADER_REPEAT, "tripura gramin bank", "HEADER"),
            (RowKind.HEADER_REPEAT, "customer account ledger report", "HEADER"),
            (RowKind.HEADER_REPEAT, "gl sub head code", "HEADER"),
            (RowKind.HEADER_REPEAT, "service outlet", "HEADER"),
            (RowKind.HEADER_REPEAT, "peg review date", "HEADER"),
            (RowKind.HEADER_REPEAT, "account no", "HEADER"),
            (RowKind.HEADER_REPEAT, "entry user id", "COLUMN_HEADER"),
            (RowKind.HEADER_REPEAT, "verified user id", "COLUMN_HEADER"),
            (RowKind.HEADER_REPEAT, "transaction debit amount", "COLUMN_HEADER"),
            (RowKind.HEADER_REPEAT, "transaction credit amount", "COLUMN_HEADER"),
            (RowKind.SEPARATOR, "order by gl date", "SORT_NOTE"),
        ),
        account_no_pattern=r"Account\s*No\s*[:;]\s*(\d{10,20})",
        holder_pattern=r"Account\s*No\s*[:;]\s*\d{10,20}\s+(?:M\W*S|IKR|MR)?\s*([A-Z][A-Z\s&.]{4,40})",
    )
)
