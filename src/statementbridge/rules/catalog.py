"""The category set, as data.

Taken from the client's own workbook rather than invented: the codes, their
order and their wording are exactly what ``Ajoy Nag FY2025-26 Tally.xlsx``
carries, and the Tally ledgers are the ones the firm actually posted to where
that statement had examples. The suggested groups come from the workbook's own
migration note 8.

Two things about this list are load-bearing.

**It is complete and ordered.** The summary sheet prints every category even
when it is empty -- twenty-three of the thirty-three read ``0`` on that
statement -- because a reader has to be able to see that Rent really was nil
rather than wonder whether Rent was considered. Export iterates this tuple, not
the categories that happen to have rows.

**It is not the rules.** A category is a destination; which transactions reach
it is decided in ``rules.engine`` and, increasingly, by what the firm corrects.
Keeping the two apart is what lets a clerk's correction add a rule without
anybody editing a Tally ledger name.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Where a transaction goes when no rule claims it. Never a guess.
UNCLASSIFIED: Final[str] = "UNCL"

#: Ledger names may carry this, filled from the confirmed account header.
HOLDER_TOKEN: Final[str] = "{holder}"


@dataclass(frozen=True, slots=True)
class Category:
    code: str
    label: str
    #: Tally ledger to post to. May contain :data:`HOLDER_TOKEN`.
    ledger: str
    #: Standard Tally group the ledger belongs under.
    group: str
    #: True where Tally wants a *contra* voucher rather than receipt/payment --
    #: money moving between the client's own bank and cash, not to a third
    #: party. The workbook flags exactly F and S; see the note on R below.
    contra: bool = False
    #: Set where this row's ledger was read off the client's workbook rather
    #: than chosen here. Those are the ones known to match the firm's practice.
    observed: bool = False


CATEGORIES: Final[tuple[Category, ...]] = (
    Category("A", "Opening Balance Adjustment", "Suspense A/c", "Suspense A/c"),
    Category("B", "Closing Balance Adjustment", "Suspense A/c", "Suspense A/c"),
    Category("C", "Bank Charges", "Bank Charges A/c", "Indirect Expenses", observed=True),
    Category("D", "Interest Credited", "Interest Received A/c", "Indirect Incomes", observed=True),
    Category("E", "Interest Debited", "Interest Paid A/c", "Indirect Expenses"),
    # The holder's own accounts. Contra, and named after them.
    Category("F", "Self Transfers (name match)", f"{HOLDER_TOKEN} - Own Accounts (Contra)",
             "Bank Accounts", contra=True, observed=True),
    Category("G", "Subsidies", "Subsidy Received A/c", "Indirect Incomes"),
    Category("H", "Pension Scheme", "Pension A/c", "Indirect Incomes"),
    Category("I", "Insurance Received", "Insurance Claims Received A/c", "Indirect Incomes"),
    Category("J", "Insurance Paid", "Insurance Premium A/c", "Indirect Expenses"),
    Category("K", "Mutual Funds Received", "Mutual Fund Redemption A/c", "Investments"),
    Category("L", "Mutual Funds Paid", "Mutual Fund Investment A/c", "Investments"),
    Category("M", "Salary / Primary Income", "Salary Received A/c", "Direct Incomes"),
    Category("N", "Rent", "Rent A/c", "Indirect Expenses"),
    Category("O", "Loan EMIs", "Loan A/c", "Loans (Liability)"),
    Category("P", "Tax Payments", "Duties & Taxes", "Duties & Taxes"),
    Category("Q", "Tax Refunds", "Income Tax Refund A/c", "Indirect Incomes"),
    # Arguably a contra too -- an ATM withdrawal moves bank to cash exactly as a
    # cash deposit moves cash to bank. It is left False because the client's
    # workbook flags only F and S, and that statement had no R rows to settle
    # it. Worth confirming with the firm before the first statement that has one.
    Category("R", "ATM Cash Withdrawals", "Cash A/c", "Cash-in-Hand"),
    Category("S", "Cash Deposits", "Cash A/c (Contra)", "Cash-in-Hand",
             contra=True, observed=True),
    Category("T1", "UPI Received (3rd party)", "Sundry Receipts / Debtors",
             "Sundry Debtors", observed=True),
    Category("T2", "UPI Sent (3rd party)", "Sundry Payments / Creditors",
             "Sundry Creditors", observed=True),
    # The client's ledger for these says "Suspense - verify", which is the
    # honest reading: a bare reference and a branch name identify nothing.
    Category("U1", "Cheque / Branch Deposit", "Cheque/Cash Deposit (Suspense - verify)",
             "Suspense A/c", observed=True),
    Category("U2", "Cheque Paid", "Cheque Payments A/c", "Sundry Creditors"),
    Category("V", "Utility Bills", "Utility Expenses A/c", "Indirect Expenses"),
    Category("W", "Credit Card Bill Payments", "Credit Card A/c", "Current Liabilities"),
    Category("X", "Investment Income", "Investment Income A/c", "Indirect Incomes"),
    Category("Y", "Reversals / Refunds", "Reversals & Refunds A/c", "Indirect Incomes"),
    Category("Z", "RD / FD", "Fixed Deposit A/c", "Investments"),
    # The workbook posts NEFT inward to "Sundry Receipts - PhonePe Aggregator",
    # which is that client's payment processor rather than a property of NEFT.
    # The generic ledger is here; the specialisation belongs to the firm as a
    # learned per-client rule.
    Category("NEFT_IN", "NEFT Inward (3rd party)", "Sundry Receipts - NEFT", "Sundry Debtors"),
    Category("NEFT_OUT", "NEFT Outward (3rd party)", "Sundry Payments - NEFT", "Sundry Creditors"),
    Category("IMPS_IN", "IMPS Inward (3rd party)", "Sundry Receipts - IMPS",
             "Sundry Debtors", observed=True),
    Category("IMPS_OUT", "IMPS Outward (3rd party)", "Sundry Payments - IMPS",
             "Sundry Creditors", observed=True),
    Category(UNCLASSIFIED, "UNCLASSIFIED", "Suspense A/c", "Suspense A/c"),
)

BY_CODE: Final[dict[str, Category]] = {item.code: item for item in CATEGORIES}

#: Codes that post as contra vouchers.
CONTRA_CODES: Final[frozenset[str]] = frozenset(
    item.code for item in CATEGORIES if item.contra
)


def get(code: str) -> Category:
    try:
        return BY_CODE[code]
    except KeyError:
        raise KeyError(
            f"unknown category {code!r}; known: {', '.join(BY_CODE)}"
        ) from None


def ledger_for(code: str, holder: str | None = None) -> str:
    """The Tally ledger for a category, with the holder's name filled in.

    Falls back to a neutral phrase rather than leaving a literal ``{holder}``
    in an exported workbook when the account header was never confirmed.
    """
    category = get(code)
    if HOLDER_TOKEN not in category.ledger:
        return category.ledger
    return category.ledger.replace(HOLDER_TOKEN, (holder or "Account Holder").strip())
