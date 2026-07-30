"""Indian amount parsing, OCR repair, and exact Decimal behaviour."""

from decimal import Decimal

import pytest

from statementbridge.money import (
    format_drcr,
    format_indian,
    parse_amount,
    q2,
    signed_from_drcr,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("71,85,895.72", Decimal("7185895.72")),
        ("4,06,40,716.00", Decimal("40640716.00")),
        ("4,25,53,191.50", Decimal("42553191.50")),
        ("90,98,371.22", Decimal("9098371.22")),
        ("1,97,817.10", Decimal("197817.10")),
        ("21,45,89,593.12", Decimal("214589593.12")),
        ("131.24", Decimal("131.24")),
        ("0.00", Decimal("0.00")),
        ("1,234.56", Decimal("1234.56")),
    ],
)
def test_parses_indian_grouping(raw, expected):
    parsed = parse_amount(raw)
    assert parsed.value == expected
    assert parsed.grouping_ok


def test_comma_read_as_period_still_resolves():
    """A period misread for the paise comma cannot change the value.

    The final integer group in Indian notation is always three digits, so a
    separator followed by exactly two digits can only be the decimal point --
    whichever character the OCR emitted.
    """
    assert parse_amount("15.400,00").value == Decimal("15400.00")
    assert parse_amount("15,400.00").value == Decimal("15400.00")
    assert parse_amount("1,50,000,00").value == Decimal("150000.00")


def test_ocr_letter_confusions_are_repaired_and_reported():
    parsed = parse_amount("1S,4OO.OO")
    assert parsed.value == Decimal("15400.00")
    assert parsed.repairs  # the repair is never silent
    assert parsed.suspect


def test_dr_cr_suffix_detached_and_glued():
    detached = parse_amount("71,85,895.72 Dr")
    assert detached.value == Decimal("7185895.72")
    assert detached.sign_hint == "DR"

    glued = parse_amount("1,97,817.10CR")  # SBI prints it welded to the figure
    assert glued.value == Decimal("197817.10")
    assert glued.sign_hint == "CR"


def test_irregular_grouping_is_flagged_not_rejected():
    parsed = parse_amount("1,2345,678.00")
    assert parsed.ok                 # still usable
    assert not parsed.grouping_ok    # but the chain should distrust it
    assert parsed.suspect


def test_missing_decimal_point_is_flagged():
    parsed = parse_amount("15400")
    assert parsed.value == Decimal("15400.00")
    assert not parsed.has_paise
    assert parsed.suspect


def test_unreadable_input_returns_no_value():
    for raw in ("", "   ", "----", None):
        assert parse_amount(raw).value is None


@pytest.mark.parametrize(
    "value, expected",
    [
        (Decimal("9098371.22"), "90,98,371.22"),
        (Decimal("214589593.12"), "21,45,89,593.12"),
        (Decimal("131.24"), "131.24"),
        (Decimal("0"), "0.00"),
        (Decimal("1234.5"), "1,234.50"),
        (Decimal("100000"), "1,00,000.00"),
    ],
)
def test_formats_with_lakh_grouping(value, expected):
    assert format_indian(value) == expected


def test_round_trips_through_format_and_parse():
    for value in ("7185895.72", "42553191.50", "214391776.02", "197817.10"):
        original = Decimal(value)
        assert parse_amount(format_indian(original)).value == original


def test_dr_cr_presentation_is_derived_from_sign():
    assert format_drcr(Decimal("-9098371.22")) == "90,98,371.22 Dr"
    assert format_drcr(Decimal("197817.10")) == "1,97,817.10 Cr"
    assert signed_from_drcr(Decimal("7185895.72"), "Dr") == Decimal("-7185895.72")
    assert signed_from_drcr(Decimal("7185895.72"), "Cr") == Decimal("7185895.72")


def test_arithmetic_is_exact_where_float_would_drift():
    """The client's sample workbook shows 3240.71999999997 and a 2.8e-11 variance."""
    opening = Decimal("131.24")
    credits = Decimal("290529.87")
    debits = Decimal("287420.39")
    closing = q2(opening + credits - debits)
    assert closing == Decimal("3240.72")
    assert q2(closing - Decimal("3240.72")) == Decimal("0.00")


def test_gramin_cash_credit_identity_holds_exactly():
    """71,85,895.72 Dr + 4,25,53,191.50 - 4,06,40,716.00 = 90,98,371.22 Dr."""
    opening = signed_from_drcr(parse_amount("71,85,895.72").value, "Dr")
    debits = parse_amount("4,25,53,191.50").value
    credits = parse_amount("4,06,40,716.00").value
    closing = q2(opening - debits + credits)
    assert format_drcr(closing) == "90,98,371.22 Dr"
