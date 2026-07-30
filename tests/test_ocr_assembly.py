"""Row assembly and the digits-only re-read overlay."""

from statementbridge.ocr.columns import overlay
from statementbridge.ocr.engine import OcrLine
from statementbridge.ocr.lines import Word, group_into_rows


def word(text, left, top, width=40, height=20, conf=90.0):
    return Word(text=text, left=left, top=top, width=width, height=height, confidence=conf)


def test_words_cluster_into_rows_by_vertical_position():
    words = [
        word("02-05-2025", 10, 100), word("SELF", 200, 102), word("1,80,000.00", 400, 101),
        word("03-05-2025", 10, 140), word("BY", 200, 141), word("CASH", 260, 139),
    ]
    rows = group_into_rows(words)
    assert len(rows) == 2
    assert rows[0].text == "02-05-2025 SELF 1,80,000.00"
    assert rows[1].text == "03-05-2025 BY CASH"


def test_a_row_split_across_tesseract_lines_is_reunited():
    """The fragments that become phantom transactions if left separate."""
    words = [
        word("13-05-2025", 10, 200),
        word("BY", 300, 202), word("CASH", 360, 201),
        word("4,83,390.00", 900, 203), word("23,03,731.72Dr", 1200, 200),
    ]
    rows = group_into_rows(words)
    assert len(rows) == 1
    assert "4,83,390.00" in rows[0].text and "23,03,731.72Dr" in rows[0].text


def test_words_are_ordered_left_to_right_within_a_row():
    rows = group_into_rows([word("SECOND", 500, 10), word("FIRST", 100, 12)])
    assert rows[0].text == "FIRST SECOND"


def test_overlay_replaces_figures_with_the_digits_only_reading():
    row = OcrLine("02-05-2025 SELF 1,8O,OOO.OO 3O,57,11B.72Dr", 100, 120, 0, 900, 60.0)
    numeric = OcrLine("1,80,000.00 30,57,118.72", 100, 120, 400, 900, 92.0)
    merged = overlay([row], [numeric])[0]
    assert "1,80,000.00" in merged.text
    assert "30,57,118.72" in merged.text
    assert "SELF" in merged.text  # narration is untouched


def test_overlay_leaves_a_row_alone_when_the_counts_disagree():
    """A partial numeric read must never delete a figure the first pass found."""
    row = OcrLine("02-05-2025 SELF 1,80,000.00 30,57,118.72Dr", 100, 120, 0, 900, 60.0)
    numeric = OcrLine("1,80,000.00", 100, 120, 400, 900, 92.0)
    assert overlay([row], [numeric])[0].text == row.text


def test_overlay_ignores_a_non_overlapping_band_row():
    row = OcrLine("02-05-2025 SELF 1,80,000.00 30,57,118.72Dr", 100, 120, 0, 900, 60.0)
    numeric = OcrLine("9,99,999.99 11,11,111.11", 400, 420, 400, 900, 92.0)
    assert overlay([row], [numeric])[0].text == row.text


def test_empty_input_is_handled():
    assert group_into_rows([]) == []
    assert overlay([], []) == []
