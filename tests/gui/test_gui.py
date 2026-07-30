"""GUI tests, run headless with QT_QPA_PLATFORM=offscreen.

These check behaviour a reviewer depends on rather than pixels: that a row's
recorded state reaches the right decoration, that export stays shut while the
statement does not reconcile, and that an override cannot be waved through
without a reason. Appearance is verified separately by rendering the screens
with ``tools/shoot.py`` and looking at them.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from statementbridge.balance.chain import ChainReport, apply_directions  # noqa: E402
from statementbridge.balance.repair import settle  # noqa: E402
from statementbridge.gui import tokens  # noqa: E402
from statementbridge.gui.models.categories import (  # noqa: E402
    CATEGORIES, build_rail, resolve_key,
)
from statementbridge.gui.models.txn_model import (  # noqa: E402
    BarColourRole, COL_BALANCE, COL_CREDIT, COL_DEBIT, COL_NARRATION,
    COLUMN_COUNT, TxnTableModel,
)
from statementbridge.gui.screens.review import ReviewScreen, suggest_token  # noqa: E402
from statementbridge.gui.screens.reconcile import ReconcileScreen  # noqa: E402
from statementbridge.gui.screens.shells import ExportScreen  # noqa: E402
from statementbridge.gui.widgets.common import ConfidenceMarker  # noqa: E402
from statementbridge.gui.widgets.override import OverrideDialog  # noqa: E402
from statementbridge.parse.frame import ParseResult, RowState, Txn  # noqa: E402
from statementbridge.store.audit import AuditStore  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def make_rows() -> list[Txn]:
    rows: list[Txn] = []
    running = Decimal("100000.00")
    for index, move in enumerate(["15400.00", "-8750.00", "22000.00", "-5000.00"]):
        running += Decimal(move)
        rows.append(Txn(
            page_no=1 + index // 2, source_row=index,
            narration=f"NEFT TO REDCLIFFE LIFE TECH {index}",
            date=date(2025, 4, 2 + index), printed_amount=abs(Decimal(move)),
            balance=running, ocr_confidence=90,
        ))
    apply_directions(rows, Decimal("100000.00"))
    return rows


# --- table model ---------------------------------------------------------

def test_model_shape_and_amounts(qapp):
    model = TxnTableModel(make_rows())
    assert model.rowCount() == 4
    assert model.columnCount() == COLUMN_COUNT
    assert model.index(0, COL_CREDIT).data() == "15,400.00"
    assert model.index(1, COL_DEBIT).data() == "8,750.00"
    # Dr/Cr on balances only, per the design's one formatter rule.
    assert model.index(0, COL_BALANCE).data().endswith(" Cr")
    # The empty side of a row stays blank rather than showing 0.00.
    assert model.index(0, COL_DEBIT).data() == ""


def test_unresolved_row_is_marked_red_not_merely_flagged(qapp):
    rows = make_rows()
    rows[2].row_state = RowState.UNRESOLVED
    model = TxnTableModel(rows)
    assert model.index(2, 0).data(BarColourRole) == tokens.BAD


def test_unclassified_rows_are_red_until_categorised(qapp):
    model = TxnTableModel(make_rows())
    assert model.index(0, 0).data(BarColourRole) == tokens.BAD
    model.set_category(0, "NEFT_OUT")
    assert model.index(0, 0).data(BarColourRole) != tokens.BAD


def test_low_confidence_row_is_gold(qapp):
    rows = make_rows()
    rows[1].ocr_confidence = 55          # below the 0.70 threshold
    model = TxnTableModel(rows)
    model.set_category(1, "C")
    assert model.index(1, 0).data(BarColourRole) == tokens.ACCENT


def test_category_counts_feed_the_rail(qapp):
    model = TxnTableModel(make_rows())
    model.set_category(0, "NEFT_OUT")
    counts = model.category_counts()
    assert counts["NEFT_OUT"][0] == 1
    assert counts["UNCL"][0] == 3
    # Every category stays on the rail, including the empty ones.
    assert len(build_rail(counts)) == len(CATEGORIES)


# --- keyboard model ------------------------------------------------------

def test_one_key_covers_both_halves_of_a_split_pair():
    assert resolve_key("T", is_credit=True) == "T1"
    assert resolve_key("T", is_credit=False) == "T2"
    assert resolve_key("U", is_credit=True) == "U1"
    assert resolve_key("N", is_credit=False) == "N2"
    assert resolve_key("C", is_credit=False) == "C"
    assert resolve_key("~", is_credit=True) is None


def test_every_category_is_reachable_from_a_key():
    """A code with no key would be unreachable without the mouse."""
    assert all(category.key for category in CATEGORIES)


# --- review --------------------------------------------------------------

def test_rule_token_is_the_counterparty_not_the_reference():
    assert suggest_token("NEFT TO: REDCLIFFE LIFE TECH PUNBNG2025050203") == "REDCLIFFE"
    assert suggest_token("BY CASH") == "CASH"
    assert suggest_token("") == ""


def test_assigning_a_category_offers_a_rule_when_it_would_repeat(qapp):
    screen = ReviewScreen()
    screen.set_rows(make_rows(), bank="Tripura Gramin")
    screen.assign(0, "NEFT_OUT")
    # All four narrations share REDCLIFFE, so a rule is worth offering.
    # isHidden() rather than isVisible(): a widget whose window has never been
    # shown reports invisible regardless of its own state.
    assert not screen.prompt.isHidden()


def test_applying_a_rule_categorises_every_matching_row(qapp):
    screen = ReviewScreen()
    screen.set_rows(make_rows(), bank="Tripura Gramin")
    seen: list[tuple[str, str, int]] = []
    screen.ruleCreated.connect(lambda *args: seen.append(args))
    screen.assign(0, "NEFT_OUT")
    screen._apply_rule("REDCLIFFE", "NEFT_OUT")
    assert seen and seen[-1][2] == 4
    assert screen.model.category_counts()["NEFT_OUT"][0] == 4


def test_a_one_off_correction_does_not_offer_a_rule(qapp):
    rows = make_rows()
    rows[0].narration = "ANNUAL LOCKER FEE"
    screen = ReviewScreen()
    screen.set_rows(rows, bank="Tripura Gramin")
    screen.assign(0, "C")
    assert screen.prompt.isHidden()


# --- reconciliation and export gating -----------------------------------

def reconciled_report() -> ChainReport:
    rows = make_rows()
    report, _ = settle(rows, Decimal("100000.00"), closing=Decimal("123650.00"))
    return report


def test_export_is_blocked_until_reconciliation_passes(qapp):
    screen = ExportScreen()
    screen.set_state(reconciled=False, variance=Decimal("-1912.40"))
    assert not screen.blocker.isHidden()
    assert "1,912.40" in screen.blocker.text()


def test_override_unblocks_but_says_so(qapp):
    screen = ExportScreen()
    screen.set_state(
        reconciled=False, variance=Decimal("-1912.40"), overridden=True
    )
    assert "overridden" in screen.blocker.text().lower()


def test_reconcile_screen_shows_suspects_and_enables_override(qapp):
    rows = make_rows()
    rows[1].balance = Decimal("106660.00")
    rows[1].printed_amount = Decimal("9999.00")
    report, diagnoses = settle(rows, Decimal("100000.00"), closing=Decimal("123650.00"))
    screen = ReconcileScreen()
    screen.set_job(report, diagnoses, ParseResult(rows=rows, page_count=2))
    assert not report.reconciled
    assert screen.override_button.isEnabled()


def test_override_button_is_dead_on_a_clean_statement(qapp):
    rows = make_rows()
    report, diagnoses = settle(rows, Decimal("100000.00"), closing=Decimal("123650.00"))
    screen = ReconcileScreen()
    screen.set_job(report, diagnoses, ParseResult(rows=rows, page_count=2))
    assert report.reconciled
    assert not screen.override_button.isEnabled()


# --- override dialog -----------------------------------------------------

def test_override_refuses_a_token_reason(qapp):
    dialog = OverrideDialog(Decimal("-1912.40"))
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.reason.setPlainText("typo")
    assert not ok.isEnabled()
    dialog.reason.setPlainText("Page 14 illegible; confirmed with the branch.")
    assert ok.isEnabled()


def test_override_writes_exactly_one_audit_line_with_the_variance():
    store = AuditStore(":memory:")
    store.append_override(
        actor="Sujata D.", job_id=None, variance=Decimal("-1912.40"),
        reason="Page 14 illegible; confirmed with the branch.",
    )
    lines = store.lines()
    assert len(lines) == 1
    assert lines[0].severity == "override"
    assert "1,912.40" in lines[0].detail
    assert "confirmed with the branch" in lines[0].detail


def test_audit_log_offers_no_way_to_remove_a_line():
    """The immutability promise is enforced here, not only in the UI."""
    store = AuditStore(":memory:")
    forbidden = [name for name in dir(store)
                 if any(word in name.lower() for word in ("delete", "remove", "purge"))]
    assert forbidden == []


# --- confidence marker ---------------------------------------------------

@pytest.mark.parametrize(
    "confidence, expected",
    [(0.99, "confirmed"), (0.85, "medium"), (0.70, "medium"), (0.69, "low"), (0.2, "low")],
)
def test_confidence_states(qapp, confidence, expected):
    assert ConfidenceMarker(confidence).state == expected
