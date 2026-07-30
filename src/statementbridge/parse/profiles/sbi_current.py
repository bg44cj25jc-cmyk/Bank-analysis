"""State Bank of India — Current account statement (bordered, shaded table).

Unlike the Gramin ledger this page is a ruled table on a shaded background, so
it needs local thresholding and rule removal rather than dot-matrix closing.
The balance carries a ``CR`` suffix welded to the figure.
"""

from __future__ import annotations

from ..rowkind import RowKind
from .base import BankProfile, register

SBI_CURRENT = register(
    BankProfile(
        key="sbi_current",
        name="State Bank of India — Current account",
        is_overdraft=False,
        extra_patterns=(
            (RowKind.HEADER_REPEAT, "state bank of india", "HEADER"),
            (RowKind.HEADER_REPEAT, "account statement", "HEADER"),
            (RowKind.HEADER_REPEAT, "txn date", "COLUMN_HEADER"),
            (RowKind.HEADER_REPEAT, "value date", "COLUMN_HEADER"),
            (RowKind.HEADER_REPEAT, "cheque no", "COLUMN_HEADER"),
            (RowKind.HEADER_REPEAT, "page no", "HEADER"),
            (RowKind.OPENING, "brought forward", "BF_BALANCE"),
        ),
        account_no_pattern=r"Account\s*(?:Number|No)\s*[:;]?\s*(\d{10,20})",
        holder_pattern=r"(?:M/S|MR|MRS|MS)[.\s]+([A-Z][A-Z\s&.]{4,40})",
    )
)
