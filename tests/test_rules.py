"""The taxonomy, the narration normaliser and the rule format.

The cases here are real narrations, taken from the client's migration workbook
(``Ajoy Nag FY2025-26 Tally.xlsx``) rather than invented, because what makes
narration matching hard is not a shape anyone would think to make up -- it is
the reference numbers, the aggregator names and the ``UPI/DR/MR TAZIM U/YBL``
truncations that real rails actually emit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from statementbridge.rules.normalise import (
    canon_word,
    display_name,
    name_words,
    narration,
)
from statementbridge.rules.rule import Context, Pack, Rule, build
from statementbridge.rules.taxonomy import Category, Direction

# --- the taxonomy ---------------------------------------------------------


#: The workbook's own 33 codes. The firm reads these off its summary sheet, so
#: they are transcribed rather than designed and this set should not move.
WORKBOOK_CODES = {
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N",
    "O", "P", "Q", "R", "S", "T1", "T2", "U1", "U2", "V", "W", "X", "Y",
    "Z", "NEFT_IN", "NEFT_OUT", "IMPS_IN", "IMPS_OUT", "UNCL",
}

#: Ours. A savings account never used the rail; a current account uses it
#: constantly, and the nearest workbook code would have said NEFT.
ADDED_CODES = {"RTGS_IN", "RTGS_OUT"}


def test_every_workbook_code_exists_and_the_additions_are_declared():
    """Nothing may quietly appear in or vanish from the taxonomy.

    Splitting the two sets is the point: a code the firm gave us and a code we
    added are different kinds of thing, and the day someone adds a third it
    should have to be written down here.
    """
    codes = {category.value for category in Category}
    assert codes == WORKBOOK_CODES | ADDED_CODES
    assert WORKBOOK_CODES <= codes, "a code the firm reads has gone missing"


def test_every_category_has_a_ledger_and_a_description():
    for category in Category:
        assert category.description
        assert category.ledger("Ajoy Nag")


def test_the_self_transfer_ledger_carries_the_account_holder():
    assert Category.SELF_TRANSFER.ledger("Ajoy Nag") == "Ajoy Nag - Own Accounts (Contra)"


def test_an_unconfirmed_holder_renders_as_unknown_not_as_blank():
    """A ledger reading " - Own Accounts" would look like a name, not a gap."""
    rendered = Category.SELF_TRANSFER.ledger(None)
    assert not rendered.startswith(" - ")
    assert "Account Holder" in rendered


def test_money_moving_between_the_clients_own_pockets_is_contra():
    """Contra is a different voucher in Tally, not a different label.

    Both directions of the same movement must agree: a cash deposit is bank
    from cash, an ATM withdrawal is cash from bank. Treating the withdrawal as
    an expense would overstate expenditure by the whole of the cash drawn.
    """
    assert Category.CASH_DEPOSIT.contra
    assert Category.ATM_WITHDRAWAL.contra
    assert Category.SELF_TRANSFER.contra
    assert not Category.UPI_OUT.contra
    assert not Category.BANK_CHARGES.contra


def test_directions_are_constrained_where_the_category_can_only_go_one_way():
    assert Category.BANK_CHARGES.direction is Direction.DEBIT
    assert Category.SALARY.direction is Direction.CREDIT
    assert Category.UPI_IN.direction is Direction.CREDIT
    assert Category.UPI_OUT.direction is Direction.DEBIT
    # Both ways round, and deliberately so.
    assert Category.SELF_TRANSFER.direction is Direction.EITHER
    assert Category.REVERSAL.direction is Direction.EITHER


def test_direction_comes_from_the_sign_of_the_movement():
    assert Direction.of(Decimal("100.00")) is Direction.CREDIT
    assert Direction.of(Decimal("-100.00")) is Direction.DEBIT
    assert Direction.of(Decimal("0.00")) is Direction.EITHER


def test_a_row_that_did_not_move_the_balance_satisfies_no_directional_rule():
    """A zero row is not a credit and not a debit, and guessing is inventing."""
    assert not Direction.CREDIT.admits(Direction.EITHER)
    assert not Direction.DEBIT.admits(Direction.EITHER)
    assert Direction.EITHER.admits(Direction.EITHER)


# --- normalisation --------------------------------------------------------


def test_reference_numbers_are_removed_not_dissolved_into_the_words():
    """The whole reason ``canon`` cannot be used on a narration directly."""
    result = narration("IMPS-532116454511-BISHAL NAG-UCBA0002520")
    assert result.words == ("lmps", "blshal", "nag")
    assert result.numbers == ("532116454511",)
    assert result.references == ("UCBA0002520",)


def test_a_word_the_scanner_damaged_is_not_mistaken_for_a_reference():
    """``PAYMENT`` comes back as ``PAYM3NT``; dropping it would lose the rule."""
    result = narration("IMPS OUTWARD PAYM3NT")
    assert "outward" in result.words
    assert result.references == ()


def test_cheque_numbers_survive_as_numbers_rather_than_as_letter_noise():
    result = narration("184693 DHARMANAGAR")
    assert result.numbers == ("184693",)
    assert result.words == ("dharmanagar",)


def test_short_numeric_tokens_never_become_words():
    """``1820`` canonicalises to ``lbzo``, four letters a rule could match."""
    result = narration("GST 1820-GST")
    assert result.words == ("gst", "gst")
    assert result.numbers == ("1820",)


def test_a_upi_narration_reduces_to_its_parts():
    assert narration("UPI/CR/BISHAL NAG/AXL").words == (
        "upl", "cr", "blshal", "nag", "axl",
    )


def test_ocr_damage_and_clean_text_reduce_to_the_same_words():
    """``canon``'s glyph table is what makes the match exact, not merely close."""
    assert narration("GST").words == narration("G5T").words
    assert narration("UPI").words == narration("UP1").words


def test_a_ledger_uses_the_holders_name_not_the_headers_shouting():
    """``MR. AJOY NAG`` on the statement; ``Ajoy Nag`` in the firm's ledger."""
    assert display_name("MR. AJOY NAG") == "Ajoy Nag"
    assert display_name("M/S SUHAGKUTI TRADERS") == "Suhagkuti Traders"
    assert display_name("  Smt. Rina Das  ") == "Rina Das"


def test_a_name_already_cased_deliberately_is_left_alone():
    """Retyping ``ABC Enterprises Pvt Ltd`` would be a change, not a fix."""
    assert display_name("ABC Enterprises Pvt Ltd") == "ABC Enterprises Pvt Ltd"
    assert display_name("Ajoy Nag") == "Ajoy Nag"
    assert display_name(None) == ""
    assert display_name("   ") == ""


def test_honorifics_and_initials_are_not_part_of_a_name():
    assert name_words("MR. AJOY NAG") == ("ajoy", "nag")
    assert name_words("Ajoy Nag") == name_words("MR. AJOY NAG")
    assert name_words("A NAG") == ("nag",)
    assert name_words(None) == ()


# --- the rule format ------------------------------------------------------


CREDIT = Direction.CREDIT
DEBIT = Direction.DEBIT


def match(rule: Rule, text: str, direction: Direction, holder: str | None = None) -> bool:
    return rule.matches(narration(text), direction, Context.for_holder(holder))


def test_a_rule_matches_on_words_in_any_order():
    rule = Rule(id="cash-deposit", category=Category.CASH_DEPOSIT, words=("cash", "dep"),
                direction=CREDIT)
    assert match(rule, "CASH DEP-SELF-CASH DHARMANAGAR", CREDIT)
    assert match(rule, "DEP BY CASH", CREDIT)


def test_a_rule_will_not_claim_a_row_moving_the_wrong_way():
    rule = Rule(id="upi-in", category=Category.UPI_IN, words=("upi",), direction=CREDIT)
    assert match(rule, "UPI/CR/BISHAL NAG/AXL", CREDIT)
    assert not match(rule, "UPI/DR/BISHAL NAG/YBL", DEBIT)


def test_a_rule_that_contradicts_its_category_is_refused_when_it_is_written():
    """A credit posted to an expense ledger looks like a number, not an error."""
    with pytest.raises(ValueError, match="DEBIT-only"):
        Rule(id="wrong", category=Category.BANK_CHARGES, words=("gst",), direction=CREDIT)


def test_a_rule_that_matches_nothing_is_refused():
    with pytest.raises(ValueError, match="matches nothing"):
        Rule(id="empty", category=Category.UNCLASSIFIED)


def test_a_rule_naming_an_unknown_predicate_is_refused():
    with pytest.raises(KeyError, match="unknown structural predicate"):
        Rule(id="bad", category=Category.UNCLASSIFIED, predicate="no_such_test")


def test_short_words_must_match_exactly_but_long_ones_may_be_damaged():
    """``fuzz`` on a three-letter token would find it in half the statement."""
    short = Rule(id="gst", category=Category.BANK_CHARGES, words=("gst",), direction=DEBIT)
    assert not match(short, "GXT CHARGE", DEBIT)

    long = Rule(id="charges", category=Category.BANK_CHARGES, words=("charges",),
                direction=DEBIT)
    assert match(long, "EEB MBL PF CHARGEZ", DEBIT)


def test_the_holder_predicate_needs_every_name_word():
    """One shared surname must not turn a third party into a contra voucher."""
    rule = Rule(id="self", category=Category.SELF_TRANSFER, predicate="holder_name")
    assert match(rule, "UPI/DR/AJOY NAG/PUNB", DEBIT, holder="MR. AJOY NAG")
    assert not match(rule, "UPI/DR/BISHAL NAG/YBL", DEBIT, holder="MR. AJOY NAG")


def test_the_holder_predicate_cannot_fire_without_a_confirmed_holder():
    rule = Rule(id="self", category=Category.SELF_TRANSFER, predicate="holder_name")
    assert not match(rule, "UPI/DR/AJOY NAG/PUNB", DEBIT, holder=None)


def test_the_bare_cheque_predicate_recognises_a_number_and_a_branch():
    rule = Rule(id="branch", category=Category.CHEQUE_DEPOSIT,
                predicate="bare_cheque_number", direction=CREDIT)
    assert match(rule, "184693 DHARMANAGAR", CREDIT)
    # A rail narration carries its own vocabulary and belongs to another rule.
    assert not match(rule, "IMPS-532116454511-BISHAL NAG-UCBA0002520", CREDIT)
    assert not match(rule, "CASH DEP-SELF-CASH DHARMANAGAR", CREDIT)


def test_a_twelve_digit_run_is_a_utr_not_a_cheque_number():
    rule = Rule(id="branch", category=Category.CHEQUE_DEPOSIT,
                predicate="bare_cheque_number", direction=CREDIT)
    assert not match(rule, "532116454511 DHARMANAGAR", CREDIT)


def test_a_rule_may_override_the_categorys_ledger():
    rule = Rule(id="phonepe", category=Category.NEFT_IN, words=("phonepe",),
                direction=CREDIT, ledger="Sundry Receipts - PhonePe Aggregator")
    assert rule.ledger_for("Ajoy Nag") == "Sundry Receipts - PhonePe Aggregator"
    plain = Rule(id="neft", category=Category.NEFT_IN, words=("neft",), direction=CREDIT)
    assert plain.ledger_for("Ajoy Nag") == "Sundry Receipts - NEFT"


# --- packs ----------------------------------------------------------------


def test_the_first_matching_rule_wins_so_order_is_the_priority():
    pack = build("test", [
        Rule(id="specific", category=Category.SELF_TRANSFER, predicate="holder_name"),
        Rule(id="generic", category=Category.UPI_OUT, words=("upi",), direction=DEBIT),
    ])
    found = pack.first_match(
        narration("UPI/DR/AJOY NAG/PUNB"), DEBIT, Context.for_holder("AJOY NAG")
    )
    assert found is not None and found.id == "specific"


def test_a_pack_with_a_duplicated_rule_id_is_refused():
    with pytest.raises(ValueError, match="duplicate rule id"):
        build("test", [
            Rule(id="same", category=Category.UPI_IN, words=("upi",), direction=CREDIT),
            Rule(id="same", category=Category.UPI_OUT, words=("upi",), direction=DEBIT),
        ])


def test_a_pack_that_matches_nothing_returns_nothing_rather_than_guessing():
    pack: Pack = build("test", [
        Rule(id="upi", category=Category.UPI_IN, words=("upi",), direction=CREDIT),
    ])
    assert pack.first_match(narration("SOME MYSTERY LINE"), CREDIT, Context()) is None
