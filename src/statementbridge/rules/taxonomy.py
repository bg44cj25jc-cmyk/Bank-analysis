"""The category taxonomy, and the Tally ledger each category posts to.

The codes are not invented here. They are transcribed from the ``Category
Summary`` sheet of the client's own migration workbook (``Ajoy Nag FY2025-26
Tally.xlsx``), including the wording of the descriptions, because the firm
already reads and checks statements against that sheet. A classifier that
renamed the categories would produce output nobody could reconcile against the
work they had done by hand.

Three things are carried alongside each code.

**A ledger template rather than a ledger name.** The workbook's self-transfer
ledger reads ``Ajoy Nag - Own Accounts (Contra)`` -- the account holder's name is
part of it. The holder is known: a human confirms it at the header gate and it
is stored on the job. So the ledger is a template rendered per account, and an
account whose holder was never confirmed renders a template that says so rather
than a name that is wrong.

**A contra flag**, because a contra voucher is a different posting in Tally, not
a different label. Money moving between the client's own bank and cash, or
between two of their own accounts, is not income or expenditure and must not
reach a profit and loss account.

**A direction constraint.** Most categories can only occur one way round: bank
charges are always a debit, salary always a credit. This is not decoration --
:mod:`statementbridge.rules.rule` refuses to build a pack whose rule contradicts
its category's direction, so an inverted rule is caught when the pack is
imported instead of appearing as a credit posted to an expense ledger.

Direction itself always comes from the balance movement, never from the printed
column or from a ``CR``/``DR`` token in the narration -- the convention
:mod:`statementbridge.balance.chain` sets and the reason this pipeline can read
a statement whose columns the OCR could not.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final

from .normalise import display_name


class Direction(str, Enum):
    """Which way money moved, under the pipeline's signed convention."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    #: No constraint (on a category) or no movement at all (on a row).
    EITHER = "EITHER"

    @classmethod
    def of(cls, signed_amount: Decimal) -> "Direction":
        """Read a direction off a signed amount. Credit positive, debit negative."""
        if signed_amount > 0:
            return cls.CREDIT
        if signed_amount < 0:
            return cls.DEBIT
        return cls.EITHER

    def admits(self, actual: "Direction") -> bool:
        """Does a row moving ``actual`` satisfy this constraint?

        ``EITHER`` as a constraint admits anything. ``EITHER`` as an *actual*
        direction means a zero-value row, which no directional rule may claim:
        a row that did not move the balance is not a credit and not a debit, and
        guessing which it was would be exactly the invention this pipeline
        refuses elsewhere.
        """
        return self is Direction.EITHER or self is actual


class Category(str, Enum):
    """The workbook's codes. The value *is* the code the firm reads."""

    OPENING_ADJUSTMENT = "A"
    CLOSING_ADJUSTMENT = "B"
    BANK_CHARGES = "C"
    INTEREST_CREDITED = "D"
    INTEREST_DEBITED = "E"
    SELF_TRANSFER = "F"
    SUBSIDY = "G"
    PENSION = "H"
    INSURANCE_RECEIVED = "I"
    INSURANCE_PAID = "J"
    MUTUAL_FUNDS_RECEIVED = "K"
    MUTUAL_FUNDS_PAID = "L"
    SALARY = "M"
    RENT = "N"
    LOAN_EMI = "O"
    TAX_PAID = "P"
    TAX_REFUND = "Q"
    ATM_WITHDRAWAL = "R"
    CASH_DEPOSIT = "S"
    UPI_IN = "T1"
    UPI_OUT = "T2"
    CHEQUE_DEPOSIT = "U1"
    CHEQUE_PAID = "U2"
    UTILITIES = "V"
    CREDIT_CARD_BILL = "W"
    INVESTMENT_INCOME = "X"
    REVERSAL = "Y"
    TERM_DEPOSIT = "Z"
    NEFT_IN = "NEFT_IN"
    NEFT_OUT = "NEFT_OUT"
    IMPS_IN = "IMPS_IN"
    IMPS_OUT = "IMPS_OUT"
    UNCLASSIFIED = "UNCL"

    @property
    def spec(self) -> "CategorySpec":
        return _SPECS[self]

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def contra(self) -> bool:
        return self.spec.contra

    @property
    def direction(self) -> Direction:
        return self.spec.direction

    def ledger(self, holder: str | None = None) -> str:
        """Render the Tally ledger name for this category on one account."""
        return self.spec.render(holder)


@dataclass(frozen=True, slots=True)
class CategorySpec:
    description: str
    #: ``{holder}`` is substituted with the confirmed account holder.
    ledger_template: str
    contra: bool = False
    direction: Direction = Direction.EITHER

    def render(self, holder: str | None) -> str:
        if "{holder}" not in self.ledger_template:
            return self.ledger_template
        # An unconfirmed holder must read as unknown. Dropping the name silently
        # would produce " - Own Accounts (Contra)", which looks like a ledger.
        return self.ledger_template.format(
            holder=display_name(holder) or "Account Holder"
        )


#: Descriptions are verbatim from the workbook's ``Category Summary`` sheet.
#: Ledger names are the workbook's own wherever it exercised the category; the
#: rest follow its Notes item 8 ("Bank Charges->Indirect Exp; Interest
#: Received->Indirect Inc; Loan Drawdown->Loans(Liability); Self/Cash->Contra;
#: UPI/NEFT/IMPS 3rd-party->Sundry Dr/Cr or Sales/Purchase").
_SPECS: Final[dict[Category, CategorySpec]] = {
    Category.OPENING_ADJUSTMENT: CategorySpec(
        "Opening Balance Adjustment", "Opening Balance Adjustment (Suspense - verify)"
    ),
    Category.CLOSING_ADJUSTMENT: CategorySpec(
        "Closing Balance Adjustment", "Closing Balance Adjustment (Suspense - verify)"
    ),
    Category.BANK_CHARGES: CategorySpec(
        "Bank Charges", "Bank Charges A/c", direction=Direction.DEBIT
    ),
    Category.INTEREST_CREDITED: CategorySpec(
        "Interest Credited", "Interest Received A/c", direction=Direction.CREDIT
    ),
    Category.INTEREST_DEBITED: CategorySpec(
        "Interest Debited", "Interest Paid A/c", direction=Direction.DEBIT
    ),
    Category.SELF_TRANSFER: CategorySpec(
        "Self Transfers (name match)", "{holder} - Own Accounts (Contra)", contra=True
    ),
    Category.SUBSIDY: CategorySpec(
        "Subsidies", "Subsidy Received A/c", direction=Direction.CREDIT
    ),
    Category.PENSION: CategorySpec(
        "Pension Scheme", "Pension Receipts A/c", direction=Direction.CREDIT
    ),
    Category.INSURANCE_RECEIVED: CategorySpec(
        "Insurance Received", "Insurance Claims Received A/c", direction=Direction.CREDIT
    ),
    Category.INSURANCE_PAID: CategorySpec(
        "Insurance Paid", "Insurance Premium A/c", direction=Direction.DEBIT
    ),
    Category.MUTUAL_FUNDS_RECEIVED: CategorySpec(
        "Mutual Funds Received", "Mutual Fund Redemptions A/c", direction=Direction.CREDIT
    ),
    Category.MUTUAL_FUNDS_PAID: CategorySpec(
        "Mutual Funds Paid", "Mutual Fund Investments A/c", direction=Direction.DEBIT
    ),
    Category.SALARY: CategorySpec(
        "Salary / Primary Income", "Salary Received A/c", direction=Direction.CREDIT
    ),
    # Rent is deliberately unconstrained: the firm's clients both pay and
    # receive it, and the workbook's own label does not say which.
    Category.RENT: CategorySpec("Rent", "Rent A/c"),
    Category.LOAN_EMI: CategorySpec(
        "Loan EMIs", "Loan Repayment A/c", direction=Direction.DEBIT
    ),
    Category.TAX_PAID: CategorySpec(
        "Tax Payments", "Taxes Paid A/c", direction=Direction.DEBIT
    ),
    Category.TAX_REFUND: CategorySpec(
        "Tax Refunds", "Tax Refund Received A/c", direction=Direction.CREDIT
    ),
    # Contra, for the same reason S is: an ATM withdrawal moves the client's own
    # money from bank to cash. The workbook flags only F and S because those are
    # the only two its statement exercised (R has a count of zero), not because
    # a withdrawal is something else. Posting it as an expense would overstate
    # expenditure by the whole of the cash drawn.
    Category.ATM_WITHDRAWAL: CategorySpec(
        "ATM Cash Withdrawals", "Cash A/c (Contra)", contra=True, direction=Direction.DEBIT
    ),
    Category.CASH_DEPOSIT: CategorySpec(
        "Cash Deposits", "Cash A/c (Contra)", contra=True, direction=Direction.CREDIT
    ),
    Category.UPI_IN: CategorySpec(
        "UPI Received (3rd party)", "Sundry Receipts / Debtors", direction=Direction.CREDIT
    ),
    Category.UPI_OUT: CategorySpec(
        "UPI Sent (3rd party)", "Sundry Payments / Creditors", direction=Direction.DEBIT
    ),
    Category.CHEQUE_DEPOSIT: CategorySpec(
        "Cheque / Branch Deposit",
        "Cheque/Cash Deposit (Suspense - verify)",
        direction=Direction.CREDIT,
    ),
    Category.CHEQUE_PAID: CategorySpec(
        "Cheque Paid", "Cheque Payments (Suspense - verify)", direction=Direction.DEBIT
    ),
    Category.UTILITIES: CategorySpec(
        "Utility Bills", "Utility Expenses A/c", direction=Direction.DEBIT
    ),
    Category.CREDIT_CARD_BILL: CategorySpec(
        "Credit Card Bill Payments", "Credit Card Payable A/c", direction=Direction.DEBIT
    ),
    Category.INVESTMENT_INCOME: CategorySpec(
        "Investment Income", "Investment Income A/c", direction=Direction.CREDIT
    ),
    # Both ways round: a failed debit is reversed as a credit and a refunded
    # credit as a debit.
    Category.REVERSAL: CategorySpec("Reversals / Refunds", "Reversals / Refunds A/c"),
    Category.TERM_DEPOSIT: CategorySpec("RD / FD", "Term Deposits A/c"),
    Category.NEFT_IN: CategorySpec(
        "NEFT Inward (3rd party)", "Sundry Receipts - NEFT", direction=Direction.CREDIT
    ),
    Category.NEFT_OUT: CategorySpec(
        "NEFT Outward (3rd party)", "Sundry Payments - NEFT", direction=Direction.DEBIT
    ),
    Category.IMPS_IN: CategorySpec(
        "IMPS Inward (3rd party)", "Sundry Receipts - IMPS", direction=Direction.CREDIT
    ),
    Category.IMPS_OUT: CategorySpec(
        "IMPS Outward (3rd party)", "Sundry Payments - IMPS", direction=Direction.DEBIT
    ),
    # The terminus. Nothing matched, and the engine says so rather than posting
    # a guess to a real ledger.
    Category.UNCLASSIFIED: CategorySpec("UNCLASSIFIED", "Suspense A/c (Unclassified)"),
}

#: The workbook's own display order: A..Z, then the transfer rails, then UNCL.
SUMMARY_ORDER: Final[tuple[Category, ...]] = tuple(_SPECS)


def by_code(code: str) -> Category:
    """Look a category up by the code the firm writes, e.g. ``"T1"``."""
    return Category(code.strip().upper())
