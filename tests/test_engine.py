"""The default pack, run over the narrations it was written for.

Every narration here is copied from the ``Ledger`` sheet of the client's
migration workbook, and the expected category is the one a person assigned it.
That is what makes these tests worth something: the failures they catch are the
ones that would have shown up as a wrong Tally posting, not as a wrong string.
"""

from __future__ import annotations

from decimal import Decimal

from statementbridge.rules.engine import (
    Classification,
    classify,
    classify_narration,
    needing_review,
    unclassified,
)
from statementbridge.rules.pack import DEFAULT_PACK
from statementbridge.rules.rule import Context
from statementbridge.rules.taxonomy import Category

CREDIT = Decimal("1000.00")
DEBIT = Decimal("-1000.00")


def decide(text: str, amount: Decimal, holder: str | None = None) -> Classification:
    return classify_narration(
        text, amount, context=Context.for_holder(holder), holder=holder
    )


def category_of(text: str, amount: Decimal, holder: str | None = None) -> Category:
    return decide(text, amount, holder).category


# --- the rails ------------------------------------------------------------


def test_the_same_rail_splits_by_direction():
    """UPI credit and UPI debit are different ledgers, and only the sign says so."""
    assert category_of("UPI/CR/BISHAL NAG/AXL", CREDIT) is Category.UPI_IN
    assert category_of("UPI/DR/BISHAL NAG/YBL", DEBIT) is Category.UPI_OUT
    assert category_of("NEFT CR-UTIB0001506-SOME PAYER", CREDIT) is Category.NEFT_IN
    assert category_of("NEFT DR-UTIB0001506-SOME PAYEE", DEBIT) is Category.NEFT_OUT
    assert category_of("IMPS-532116454511-BISHAL NAG-UCBA0002520", DEBIT) is Category.IMPS_OUT
    assert category_of("IMPS-605004744473-PHONEPELIMITED-UTIB0003567", CREDIT) is Category.IMPS_IN


def test_direction_is_read_from_the_movement_not_from_the_printed_marker():
    """The narration says CR; the balance says the money left. The balance wins."""
    assert category_of("UPI/CR/BISHAL NAG/AXL", DEBIT) is Category.UPI_OUT


def test_a_multi_line_sbi_style_narration_still_finds_its_rail():
    assert category_of("IMPS OUTWARD PAYMENT - SB 522", DEBIT) is Category.IMPS_OUT


def test_the_aggregator_gets_its_own_ledger_without_leaving_its_category():
    """PhonePe's NEFT settlements are business receipts, not anonymous credits."""
    decision = decide("NEFT CR-UTIB0001506-PHONEPE LIMITED", CREDIT)
    assert decision.category is Category.NEFT_IN
    assert decision.ledger == "Sundry Receipts - PhonePe Aggregator"


def test_the_aggregator_override_does_not_leak_onto_other_rails():
    """``UPI/CR/PHONEPE/…`` is an ordinary UPI receipt in the workbook."""
    decision = decide("UPI/CR/PHONEPE/AXIS/PHONEPE.PAYOUTS", CREDIT)
    assert decision.category is Category.UPI_IN
    assert decision.ledger == "Sundry Receipts / Debtors"


# --- what outranks a rail -------------------------------------------------


def test_the_holder_s_own_name_beats_the_rail_that_carried_it():
    holder = "MR. AJOY NAG"
    assert category_of("UPI/DR/AJOY NAG/PUNB", DEBIT, holder) is Category.SELF_TRANSFER
    assert category_of("UPI/CR/AJOY NAG/PTYE", CREDIT, holder) is Category.SELF_TRANSFER
    assert category_of("OBO INITIATED: 90001511966165 AJOY NAG", CREDIT, holder) is (
        Category.SELF_TRANSFER
    )


def test_the_holder_s_own_name_beats_the_loan_vocabulary_too():
    """The workbook tags this a self-transfer, not an EMI: it is a drawdown."""
    text = "WTHDRL LOAN EMI 90001511966165 -AJOY NAG DRAWDOWN"
    assert category_of(text, DEBIT, "MR. AJOY NAG") is Category.SELF_TRANSFER
    # Without the holder to match against, the same line is an ordinary EMI.
    assert category_of(text, DEBIT, holder=None) is Category.LOAN_EMI


def test_a_third_party_sharing_a_surname_is_not_a_self_transfer():
    assert category_of("UPI/DR/BISHAL NAG/YBL", DEBIT, "MR. AJOY NAG") is Category.UPI_OUT


def test_a_self_transfer_is_flagged_for_confirmation_not_merely_labelled():
    """A contra voucher leaves the P&L entirely, so a wrong one is expensive."""
    decision = decide("UPI/DR/AJOY NAG/PUNB", DEBIT, "MR. AJOY NAG")
    assert decision.contra
    assert decision.needs_review
    # The header shouts a title; the ledger the firm keeps does neither.
    assert decision.ledger == "Ajoy Nag - Own Accounts (Contra)"


def test_a_reversal_outranks_the_rail_so_it_is_not_counted_as_turnover():
    """Both the payment and its reversal in sundry would double the turnover."""
    assert category_of("UPI/REV/BISHAL NAG/YBL", CREDIT) is Category.REVERSAL


# --- the bank's own entries ------------------------------------------------


def test_charges_and_the_gst_on_them():
    assert category_of("GST 1820-GST", DEBIT) is Category.BANK_CHARGES
    assert category_of("EEB MBL PF CHARGES", DEBIT) is Category.BANK_CHARGES
    assert category_of(
        "DEBIT CARD ANNUAL FEES EXCLUSIVE OF GST - XX4276", DEBIT
    ) is Category.BANK_CHARGES


def test_interest_splits_by_direction():
    assert category_of("CASA CREDIT INTEREST CAPITALIZED", CREDIT) is (
        Category.INTEREST_CREDITED
    )
    assert category_of("INTEREST CHARGED ON CC", DEBIT) is Category.INTEREST_DEBITED


def test_a_tax_payment_is_not_the_gst_the_bank_charges_on_its_fee():
    assert category_of("CBDT TAX PAYMENT 280", DEBIT) is Category.TAX_PAID
    assert category_of("GSTN PAYMENT", DEBIT) is Category.TAX_PAID
    assert category_of("GST", DEBIT) is Category.BANK_CHARGES


# --- cash, both ways, both contra -----------------------------------------


def test_a_cash_deposit_made_in_person_is_a_cash_deposit_not_a_self_transfer():
    """``SELF`` here means "at the counter, by me", not "to my other account"."""
    decision = decide("CASH DEP-SELF-CASH DHARMANAGAR", CREDIT, "MR. AJOY NAG")
    assert decision.category is Category.CASH_DEPOSIT
    assert decision.contra
    assert decision.ledger == "Cash A/c (Contra)"


def test_an_atm_withdrawal_is_contra_in_the_other_direction():
    decision = decide("ATM WDL 4276 DHARMANAGAR", DEBIT)
    assert decision.category is Category.ATM_WITHDRAWAL
    assert decision.contra


# --- cheques and shapes ----------------------------------------------------


def test_a_bare_instrument_number_and_a_branch_is_a_branch_deposit():
    decision = decide("184693 DHARMANAGAR", CREDIT)
    assert decision.category is Category.CHEQUE_DEPOSIT
    assert decision.needs_review
    assert decision.ledger == "Cheque/Cash Deposit (Suspense - verify)"


# --- refusing to guess -----------------------------------------------------


def test_nothing_matched_means_unclassified_and_not_a_nearby_guess():
    decision = decide("SOME NARRATION NOBODY HAS SEEN BEFORE", CREDIT)
    assert decision.category is Category.UNCLASSIFIED
    assert decision.rule_id is None
    assert decision.needs_review
    assert not decision.classified


def test_rtgs_is_left_unclassified_rather_than_labelled_neft():
    """The taxonomy has no RTGS code, and the nearest one would be a lie."""
    assert category_of("RTGS CR-HDFC0000123-SOME PAYER", CREDIT) is Category.UNCLASSIFIED


def test_a_row_that_did_not_move_the_balance_claims_no_direction():
    assert category_of("UPI/CR/BISHAL NAG/AXL", Decimal("0.00")) is Category.UNCLASSIFIED


# --- over a whole statement ------------------------------------------------


class FakeRow:
    """Minimal row: the engine asks for a narration and a signed amount."""

    def __init__(self, narration: str, signed: str) -> None:
        self.narration = narration
        amount = Decimal(signed)
        self.credit = amount if amount > 0 else Decimal("0.00")
        self.debit = -amount if amount < 0 else Decimal("0.00")

    @property
    def signed_amount(self) -> Decimal:
        return self.credit - self.debit


STATEMENT = [
    FakeRow("CASA CREDIT INTEREST CAPITALIZED", "1.00"),
    FakeRow("UPI/CR/BISHAL NAG/AXL", "100.00"),
    FakeRow("UPI/DR/BIDYUT DAS/BDBL", "-250.00"),
    FakeRow("GST 1818-GST", "-337.50"),
    FakeRow("SOMETHING ENTIRELY NEW", "-10.00"),
]


def test_classification_is_one_decision_per_row_in_row_order():
    decisions = classify(STATEMENT, holder="MR. AJOY NAG")
    assert len(decisions) == len(STATEMENT)
    assert [decision.category for decision in decisions] == [
        Category.INTEREST_CREDITED,
        Category.UPI_IN,
        Category.UPI_OUT,
        Category.BANK_CHARGES,
        Category.UNCLASSIFIED,
    ]


def test_the_unmatched_row_is_counted_and_flagged():
    decisions = classify(STATEMENT, holder="MR. AJOY NAG")
    assert unclassified(decisions) == 1
    assert needing_review(decisions) == 1


def test_every_rule_in_the_default_pack_has_a_distinct_id_and_a_reachable_category():
    ids = [rule.id for rule in DEFAULT_PACK]
    assert len(ids) == len(set(ids))
    for rule in DEFAULT_PACK:
        assert rule.category.direction.admits(rule.direction)
