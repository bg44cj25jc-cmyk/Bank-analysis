"""Ruled-table row banding and column role inference."""

import numpy as np
import pytest

from statementbridge.ocr import table
from statementbridge.ocr.lines import Word


def ruled_page(width=800, height=400, rule_ys=(50, 150, 250, 350)):
    """A white page with full-width horizontal rules, as the SBI scans have."""
    page = np.full((height, width), 255, dtype=np.uint8)
    for y in rule_ys:
        page[y : y + 3, :] = 0
    return page


def word(text, left, top, width=60, height=18):
    return Word(text=text, left=left, top=top, width=width, height=height, confidence=90.0)


def test_horizontal_rules_become_row_bands():
    grid = table.detect_grid(ruled_page())
    assert grid.usable
    assert len(grid.rows) == 3  # four rules delimit three bands


def test_a_page_without_rules_yields_no_grid():
    blank = np.full((400, 800), 255, dtype=np.uint8)
    assert not table.detect_grid(blank).usable


def test_row_band_reunites_a_transaction_split_over_three_printed_lines():
    """The SBI failure mode: dates, amounts and reference on separate lines.

    Read as three lines these are three fragments, two of which look like
    transactions carrying stray figures. Read as one band they are one row.
    """
    grid = table.detect_grid(ruled_page())
    words = [
        word("DEP", 100, 70), word("TFR", 160, 70),
        word("25,000.00", 500, 95), word("3,98,237.08CR", 640, 95),
        word("30-08-2025", 60, 120), word("UPI/CR/524275/VICTOR", 220, 120),
    ]
    lines = table.rows_to_lines(words, grid)
    assert len(lines) == 1
    text = lines[0].text
    assert "25,000.00" in text and "3,98,237.08CR" in text and "30-08-2025" in text


def test_words_within_a_band_keep_printed_line_order_then_left_to_right():
    grid = table.detect_grid(ruled_page())
    words = [
        word("AMOUNT", 500, 95), word("FIRST", 100, 70), word("LINE", 170, 70),
    ]
    assert table.rows_to_lines(words, grid)[0].text == "FIRST LINE AMOUNT"


def test_words_outside_every_band_are_dropped():
    grid = table.detect_grid(ruled_page())
    lines = table.rows_to_lines([word("MARGINALIA", 10, 5)], grid)
    assert lines == []


def test_empty_bands_are_omitted():
    grid = table.detect_grid(ruled_page())
    lines = table.rows_to_lines([word("ONLY", 100, 70)], grid)
    assert len(lines) == 1


# --- column roles, inferred from content not headings --------------------

def test_column_roles_come_from_cell_contents():
    matrix = [
        ["01-04-2025", "01-04-2025", "UPI CREDIT", "5241", "15,400.00", "1,15,400.00"],
        ["02-04-2025", "02-04-2025", "CASH DEPOSIT", "5242", "8,750.00", "1,24,150.00"],
        ["03-04-2025", "03-04-2025", "NEFT SUPPLIER", "5243", "22,000.00", "1,02,150.00"],
        ["04-04-2025", "04-04-2025", "BANK CHARGES", "5244", "118.00", "1,02,032.00"],
    ]
    roles = table.classify_columns(matrix)
    assert roles.date == 0
    assert roles.value_date == 1
    assert roles.description == 2
    assert roles.money == [4, 5]
    assert roles.balance == 5
    assert roles.usable


def test_column_roles_survive_a_misread_heading():
    """"Debit" scans as "Bebit" and "Date" as "Oate" often enough to matter."""
    matrix = [
        ["Oate", "Value Oate", "Descriptlon", "Ref", "Bebit", "8alance"],
        ["01-04-2025", "01-04-2025", "UPI CREDIT", "5241", "15,400.00", "1,15,400.00"],
        ["02-04-2025", "02-04-2025", "CASH DEPOSIT", "5242", "8,750.00", "1,24,150.00"],
        ["03-04-2025", "03-04-2025", "NEFT SUPPLIER", "5243", "22,000.00", "1,02,150.00"],
    ]
    roles = table.classify_columns(matrix)
    assert roles.date == 0 and roles.balance == 5


def test_column_roles_are_unusable_when_there_is_nothing_to_go_on():
    assert not table.classify_columns([]).usable
    assert not table.classify_columns([["a", "b"], ["c", "d"]]).usable
