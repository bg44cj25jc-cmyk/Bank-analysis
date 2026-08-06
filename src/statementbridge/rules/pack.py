"""The default rule pack: the vocabulary Indian bank narrations actually use.

Order is the priority -- the first matching rule wins -- so the pack reads from
the most specific claim to the most general, in seven bands:

1. **the account holder's own name**, which outranks everything. A transfer
   between two of the client's own accounts is a contra voucher, and it stays
   one however it was sent. The workbook makes the same call: its
   ``WTHDRL LOAN EMI … -AJOY NAG DRAWDOWN`` is tagged a self-transfer and not a
   loan EMI, because what the money *is* matters more than the rail it took;
2. **reversals**, ahead of the rails deliberately. A reversed UPI payment
   classified as an ordinary receipt would leave both the payment and its
   reversal sitting in the sundry ledger, overstating turnover by twice the
   amount. It is the reversal that is the fact about the money;
3. **charges and interest**, which are the bank's own entries;
4. **cash**, in both directions, both contra;
5. **the accounting vocabulary** -- salary, rent, tax, utilities, insurance,
   investments, loans;
6. **cheques**, including the narration that is only an instrument number and a
   branch;
7. **the rails last** -- UPI, NEFT, IMPS -- because they say how the money moved
   and almost nothing about what it was for. A rail rule is the weakest true
   statement the engine can make, so nothing else should ever lose to one.

Two absences are deliberate.

**No rule matches ``CR`` or ``DR``.** Direction comes from the balance movement,
which every neighbouring row and every printed page total checks. The token is
one more thing a 150 DPI recogniser can drop, and when it does the balance is
still right.

**RTGS is a code of our own** rather than a reuse of NEFT. The client's sheet has
no RTGS row because their savings account never used the rail; a current account
uses it constantly. Labelling a wire transfer as a different rail, to keep the
two sheets identical, would have bought that tidiness with a quiet error.
"""

from __future__ import annotations

from typing import Final

from .rule import Pack, Rule, build
from .taxonomy import Category as C
from .taxonomy import Direction

CREDIT: Final = Direction.CREDIT
DEBIT: Final = Direction.DEBIT
EITHER: Final = Direction.EITHER

#: The ledger the workbook gives PhonePe's NEFT settlements, which are business
#: receipts rather than anonymous sundry credits.
_PHONEPE_LEDGER: Final = "Sundry Receipts - PhonePe Aggregator"


_RULES: Final[tuple[Rule, ...]] = (
    # --- 1. the client's own money -----------------------------------------
    Rule(
        id="self.holder-name",
        category=C.SELF_TRANSFER,
        predicate="holder_name",
        review=True,
        why="the account holder's own name appears; contra, and worth a look "
            "in case the name belongs to a merchant or a loan account",
    ),
    # There is deliberately no rule on the bare word ``SELF``. It reads like a
    # self-transfer marker and is not one: the commonest narration carrying it
    # is ``CASH DEP-SELF-…``, a cash deposit the account holder made in person,
    # which the workbook tags S and not F. Both are contra, so the error would
    # survive the reconciliation and land in the wrong ledger anyway. The
    # holder's name is the signal that means what it says.

    # --- 2. reversals, ahead of the rails ----------------------------------
    Rule(id="reversal.rev", category=C.REVERSAL, words=("rev",),
         why="a reversal is the fact about the money, not the rail it rode"),
    Rule(id="reversal.reversal", category=C.REVERSAL, words=("reversal",)),
    Rule(id="reversal.reversed", category=C.REVERSAL, words=("reversed",)),
    Rule(id="reversal.refund", category=C.REVERSAL, words=("refund",)),
    Rule(id="reversal.returned", category=C.REVERSAL, words=("returned",)),

    # --- 3. the bank's own entries -----------------------------------------
    # Government tax identifiers first: these are payments to the state, not
    # the GST the bank charges on its own fees.
    Rule(id="tax.cbdt", category=C.TAX_PAID, words=("cbdt",), direction=DEBIT),
    Rule(id="tax.itns", category=C.TAX_PAID, words=("itns",), direction=DEBIT),
    Rule(id="tax.gstn", category=C.TAX_PAID, words=("gstn",), direction=DEBIT),
    Rule(id="tax.tds", category=C.TAX_PAID, words=("tds",), direction=DEBIT),
    Rule(id="tax.advance", category=C.TAX_PAID, words=("advance", "tax"), direction=DEBIT),
    Rule(id="tax.refund", category=C.TAX_REFUND, words=("refund", "tax"), direction=CREDIT),

    # Interest before charges, because "INTEREST CHARGED ON CC" is interest and
    # the fuzzy matcher reaches ``CHARGED`` from ``charge``. Interest is the
    # more specific claim, so it is the one that has to be tested first.
    Rule(id="interest.credited", category=C.INTEREST_CREDITED, words=("interest",),
         direction=CREDIT),
    Rule(id="interest.debited", category=C.INTEREST_DEBITED, words=("interest",),
         direction=DEBIT),
    Rule(id="interest.collected", category=C.INTEREST_DEBITED, words=("int", "coll"),
         direction=DEBIT, why="interest collected, as a cash-credit ledger prints it"),

    Rule(id="charges.gst", category=C.BANK_CHARGES, words=("gst",), direction=DEBIT,
         why="GST printed on a bank statement is the tax on the bank's own fee"),
    Rule(id="charges.charges", category=C.BANK_CHARGES, words=("charges",), direction=DEBIT),
    Rule(id="charges.charge", category=C.BANK_CHARGES, words=("charge",), direction=DEBIT),
    Rule(id="charges.chrg", category=C.BANK_CHARGES, words=("chrg",), direction=DEBIT),
    Rule(id="charges.fees", category=C.BANK_CHARGES, words=("fees",), direction=DEBIT),
    Rule(id="charges.fee", category=C.BANK_CHARGES, words=("fee",), direction=DEBIT),
    Rule(id="charges.commission", category=C.BANK_CHARGES, words=("commission",),
         direction=DEBIT),
    Rule(id="charges.penalty", category=C.BANK_CHARGES, words=("penalty",), direction=DEBIT),
    Rule(id="charges.sms", category=C.BANK_CHARGES, words=("sms", "alert"), direction=DEBIT),
    Rule(id="charges.min-balance", category=C.BANK_CHARGES, words=("min", "bal"),
         direction=DEBIT),
    Rule(id="charges.amb", category=C.BANK_CHARGES, words=("amb",), direction=DEBIT,
         why="average monthly balance shortfall"),

    # --- 4. cash, contra in both directions --------------------------------
    Rule(id="cash.deposit", category=C.CASH_DEPOSIT, words=("cash", "dep"),
         direction=CREDIT),
    Rule(id="cash.deposit-long", category=C.CASH_DEPOSIT, words=("cash", "deposit"),
         direction=CREDIT),
    Rule(id="cash.cdm", category=C.CASH_DEPOSIT, words=("cdm",), direction=CREDIT,
         why="cash deposit machine"),
    Rule(id="atm.atm", category=C.ATM_WITHDRAWAL, words=("atm",), direction=DEBIT),
    Rule(id="atm.nwd", category=C.ATM_WITHDRAWAL, words=("nwd",), direction=DEBIT,
         why="national withdrawal, the switch's own abbreviation"),
    Rule(id="atm.cash-withdrawal", category=C.ATM_WITHDRAWAL, words=("cash", "wdl"),
         direction=DEBIT),
    Rule(id="atm.cash-withdrawal-long", category=C.ATM_WITHDRAWAL,
         words=("cash", "withdrawal"), direction=DEBIT),

    # --- 5. the accounting vocabulary --------------------------------------
    Rule(id="salary.salary", category=C.SALARY, words=("salary",), direction=CREDIT),
    Rule(id="salary.sal", category=C.SALARY, words=("sal",), direction=CREDIT,
         why="the abbreviation alone; the direction says the rest, so the "
             "printed CR that usually follows it is not needed"),

    Rule(id="rent.rent", category=C.RENT, words=("rent",)),

    Rule(id="loan.emi", category=C.LOAN_EMI, words=("emi",), direction=DEBIT),
    Rule(id="loan.repayment", category=C.LOAN_EMI, words=("loan", "repay"),
         direction=DEBIT),
    Rule(id="loan.instalment", category=C.LOAN_EMI, words=("loan", "instalment"),
         direction=DEBIT),

    Rule(id="utility.electricity", category=C.UTILITIES, words=("electricity",),
         direction=DEBIT),
    Rule(id="utility.bill", category=C.UTILITIES, words=("bill", "pay"), direction=DEBIT),
    Rule(id="utility.broadband", category=C.UTILITIES, words=("broadband",),
         direction=DEBIT),
    Rule(id="utility.recharge", category=C.UTILITIES, words=("recharge",), direction=DEBIT),

    Rule(id="insurance.claim", category=C.INSURANCE_RECEIVED, words=("insurance", "claim"),
         direction=CREDIT),
    Rule(id="insurance.premium", category=C.INSURANCE_PAID, words=("premium",),
         direction=DEBIT),
    Rule(id="insurance.insurance", category=C.INSURANCE_PAID, words=("insurance",),
         direction=DEBIT),
    Rule(id="insurance.lic", category=C.INSURANCE_PAID, words=("lic",), direction=DEBIT),

    Rule(id="mf.redemption", category=C.MUTUAL_FUNDS_RECEIVED, words=("redemption",),
         direction=CREDIT),
    Rule(id="mf.sip", category=C.MUTUAL_FUNDS_PAID, words=("sip",), direction=DEBIT),
    Rule(id="mf.mutual-fund", category=C.MUTUAL_FUNDS_PAID, words=("mutual", "fund"),
         direction=DEBIT),

    Rule(id="card.credit-card", category=C.CREDIT_CARD_BILL, words=("credit", "card"),
         direction=DEBIT),
    Rule(id="card.cc-payment", category=C.CREDIT_CARD_BILL, words=("cc", "pmt"),
         direction=DEBIT),

    Rule(id="subsidy.subsidy", category=C.SUBSIDY, words=("subsidy",), direction=CREDIT),
    Rule(id="subsidy.dbt", category=C.SUBSIDY, words=("dbt",), direction=CREDIT,
         why="direct benefit transfer"),
    Rule(id="pension.pension", category=C.PENSION, words=("pension",), direction=CREDIT),
    Rule(id="income.dividend", category=C.INVESTMENT_INCOME, words=("dividend",),
         direction=CREDIT),

    # Spelled out, never as the bare ``FD`` and ``RD`` abbreviations. Those are
    # two characters, so they must match exactly, and canonicalisation maps
    # ``3RD`` onto ``rd`` -- an ordinal in an address would open a term deposit.
    Rule(id="deposit.term", category=C.TERM_DEPOSIT, words=("term", "deposit")),
    Rule(id="deposit.recurring", category=C.TERM_DEPOSIT, words=("recurring", "deposit")),
    Rule(id="deposit.fixed", category=C.TERM_DEPOSIT, words=("fixed", "deposit")),

    # --- 6. cheques ---------------------------------------------------------
    Rule(id="cheque.in", category=C.CHEQUE_DEPOSIT, words=("chq",), direction=CREDIT),
    Rule(id="cheque.in-long", category=C.CHEQUE_DEPOSIT, words=("cheque",),
         direction=CREDIT),
    Rule(id="cheque.clearing-in", category=C.CHEQUE_DEPOSIT, words=("clg",),
         direction=CREDIT),
    Rule(id="cheque.out", category=C.CHEQUE_PAID, words=("chq",), direction=DEBIT),
    Rule(id="cheque.out-long", category=C.CHEQUE_PAID, words=("cheque",), direction=DEBIT),
    Rule(id="cheque.clearing-out", category=C.CHEQUE_PAID, words=("clg",), direction=DEBIT),
    Rule(
        id="cheque.bare-number",
        category=C.CHEQUE_DEPOSIT,
        predicate="bare_cheque_number",
        direction=CREDIT,
        review=True,
        why="an instrument number and a branch, with nothing saying what it was "
            "for; the workbook's own Notes ask for these to be verified",
    ),

    # --- 7. the rails, last -------------------------------------------------
    # The aggregator, on either rail it settles over. The workbook gives its
    # NEFT settlements a ledger of their own and leaves the IMPS ones on the
    # generic rail ledger; that is an inconsistency in the sheet rather than a
    # distinction, and its own Notes item 7 reads them as one thing ("NEFT/IMPS
    # inward are mostly PhonePe aggregator settlements -> business receipts").
    # The same payer settling over a different rail is the same payer.
    Rule(id="neft.phonepe", category=C.NEFT_IN, words=("neft", "phonepe"),
         direction=CREDIT, ledger=_PHONEPE_LEDGER,
         why="aggregator settlement: a business receipt, not an anonymous credit"),
    Rule(id="imps.phonepe", category=C.IMPS_IN, words=("imps", "phonepe"),
         direction=CREDIT, ledger=_PHONEPE_LEDGER,
         why="the same aggregator over the other rail"),
    Rule(id="upi.in", category=C.UPI_IN, words=("upi",), direction=CREDIT),
    Rule(id="upi.out", category=C.UPI_OUT, words=("upi",), direction=DEBIT),
    Rule(id="neft.in", category=C.NEFT_IN, words=("neft",), direction=CREDIT),
    Rule(id="neft.out", category=C.NEFT_OUT, words=("neft",), direction=DEBIT),
    Rule(id="rtgs.in", category=C.RTGS_IN, words=("rtgs",), direction=CREDIT),
    Rule(id="rtgs.out", category=C.RTGS_OUT, words=("rtgs",), direction=DEBIT),
    Rule(id="imps.in", category=C.IMPS_IN, words=("imps",), direction=CREDIT),
    Rule(id="imps.out", category=C.IMPS_OUT, words=("imps",), direction=DEBIT),
)


DEFAULT_PACK: Final[Pack] = build("default", _RULES)
