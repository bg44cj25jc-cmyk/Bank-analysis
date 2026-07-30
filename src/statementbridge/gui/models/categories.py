"""The 33 category codes, and the rail model that counts them.

The set and its order come from the brief, not from what happens to appear in a
statement. Zero-count categories stay visible and drop to neutral rather than
disappearing, so the rail reads the same way on every job and a reviewer builds
muscle memory for where a code sits.

Keyboard hints follow the mockup's insight: direction is already known from
which money column a row sits in, so one letter covers both halves of a split
pair -- ``T`` on a credit row means T1 (UPI received) and on a debit row T2
(UPI sent). That collapses 33 codes onto 26 keys without ambiguity.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ...money import ZERO


@dataclass(frozen=True, slots=True)
class Category:
    code: str
    name: str
    key: str = ""
    #: True where one letter serves a received/paid pair, resolved by the row's
    #: own direction.
    split: bool = False
    group: str = "A-Z"


#: A–Z in the order the brief lists them, then the payment rails.
#:
#: This comes to 39 codes, where the mockup says 33 and the client's existing
#: Ajoy Nag workbook shows 33 rows. The difference is real and the brief is
#: followed here: it asks for RTGS Inward/Outward, POS Debit-card and Internal
#: Transfer, none of which the old workbook carries because that client had no
#: such rows, and it splits N (Rent received/paid) and Z (RD/FD creation and
#: maturity), which the workbook leaves merged. Direction resolves both splits
#: from the money column, exactly as it does for T and U, so the 26-key model
#: is unaffected. Worth confirming before the Excel writer is built, since the
#: Category Summary sheet must show every code even at zero.
CATEGORIES: tuple[Category, ...] = (
    Category("A", "Opening Balance Adjustment", "A"),
    Category("B", "Closing Balance Adjustment", "B"),
    Category("C", "Bank Charges", "C"),
    Category("D", "Interest Credited", "D"),
    Category("E", "Interest Debited", "E"),
    Category("F", "Self Transfers", "F"),
    Category("G", "Subsidies", "G"),
    Category("H", "Pension Scheme", "H"),
    Category("I", "Insurance Received", "I"),
    Category("J", "Insurance Paid", "J"),
    Category("K", "Mutual Funds Received", "K"),
    Category("L", "Mutual Funds Paid", "L"),
    Category("M", "Salary / Primary Income", "M"),
    Category("N1", "Rent Received", "N", split=True),
    Category("N2", "Rent Paid", "N", split=True),
    Category("O", "Loan EMIs", "O"),
    Category("P", "Tax Payments", "P"),
    Category("Q", "Tax Refunds", "Q"),
    Category("R", "ATM Cash Withdrawals", "R"),
    Category("S", "Cash Deposits", "S"),
    Category("T1", "UPI Received", "T", split=True),
    Category("T2", "UPI Sent", "T", split=True),
    Category("U1", "Cheque Received", "U", split=True),
    Category("U2", "Cheque Paid", "U", split=True),
    Category("V", "Utility Bills", "V"),
    Category("W", "Credit Card Bill Payments", "W"),
    Category("X", "Investment Income", "X"),
    Category("Y", "Reversals / Refunds", "Y"),
    Category("Z1", "RD / FD Maturity", "Z", split=True),
    Category("Z2", "RD / FD Creation", "Z", split=True),
    Category("NEFT_IN", "NEFT Inward", "1", group="Rails"),
    Category("NEFT_OUT", "NEFT Outward", "1", group="Rails"),
    Category("IMPS_IN", "IMPS Inward", "2", group="Rails"),
    Category("IMPS_OUT", "IMPS Outward", "2", group="Rails"),
    Category("RTGS_IN", "RTGS Inward", "3", group="Rails"),
    Category("RTGS_OUT", "RTGS Outward", "3", group="Rails"),
    Category("POS", "POS Debit-card", "4", group="Rails"),
    Category("INTERNAL", "Internal Transfer", "5", group="Rails"),
    Category("UNCL", "UNCLASSIFIED", "0", group="Needs attention"),
)

BY_CODE: dict[str, Category] = {category.code: category for category in CATEGORIES}


def resolve_key(key: str, *, is_credit: bool) -> str | None:
    """Map a keystroke to a category code, using the row's direction.

    ``T`` on a credit row is T1; on a debit row it is T2. The same trick
    resolves U, N, Z and every rail pair, which is what keeps the whole set
    reachable from 26 letters.
    """
    key = key.upper()
    matches = [category for category in CATEGORIES if category.key == key]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].code
    suffix_in = ("1", "_IN")
    for category in matches:
        inbound = category.code.endswith(suffix_in) or category.code.endswith("1")
        if inbound == is_credit:
            return category.code
    return matches[0].code


@dataclass(slots=True)
class RailEntry:
    category: Category
    count: int = 0
    total: Decimal = ZERO

    @property
    def is_empty(self) -> bool:
        return self.count == 0


#: Rail order: what needs a human first, then the alphabet, then the rails.
GROUP_ORDER: tuple[str, ...] = ("Needs attention", "A-Z", "Rails")


def build_rail(counts: dict[str, tuple[int, Decimal]]) -> list[RailEntry]:
    """One entry per category, in rail order, including the empty ones.

    Grouped needs-attention first: an unclassified row is the only thing on
    this screen that actually blocks a job, so it should not sit at the bottom
    of a 39-item list behind categories that happen to start with A.
    """
    entries: list[RailEntry] = []
    for group in GROUP_ORDER:
        for category in CATEGORIES:
            if category.group != group:
                continue
            count, total = counts.get(category.code, (0, ZERO))
            entries.append(RailEntry(category=category, count=count, total=total))
    return entries
