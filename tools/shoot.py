"""Render every screen to PNG so the result can be looked at, not assumed.

Run headless:  QT_QPA_PLATFORM=offscreen python tools/shoot.py [outdir]

The Phase 1 preprocessing decisions were made by measuring rather than
guessing; the same applies to a user interface, and on a machine with no
display the only way to see it is to grab it.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from statementbridge.balance.chain import apply_directions  # noqa: E402
from statementbridge.balance.repair import settle  # noqa: E402
from statementbridge.gui import tokens  # noqa: E402
from statementbridge.gui.main_window import MainWindow  # noqa: E402
from statementbridge.gui.widgets.override import OverrideDialog  # noqa: E402
from statementbridge.parse.frame import Anchor, ParseResult, RowState, Txn  # noqa: E402
from statementbridge.store.audit import AuditStore  # noqa: E402

NARRATIONS = [
    "NEFT TO: REDCLIFFE LIFE TECH PR LT", "Charges for NEFT", "BY CASH",
    "NEFT TO: REDCLIFFE LIFE TECH PR LT", "POPULAR MEDICAL AGENCY", "SELF",
    "TR FR DIPANJAN PAUL", "MEDICARE", "NABIN DRUG CENTRE",
    "NEFT TO: KIRAN ENT", "BY CASH", "KANAK MEDICAL AGENCY",
]
MOVES = ["-30000.00", "-6.00", "900000.00", "-16663.60", "-293713.00",
         "-180000.00", "203000.00", "-146660.63", "-16550.00", "-22258.00",
         "483390.00", "-63579.00"]
OPENING = Decimal("-7185895.72")


def demo_job() -> tuple[ParseResult, object, list]:
    rows: list[Txn] = []
    running = OPENING
    for index, (narration, move) in enumerate(zip(NARRATIONS, MOVES)):
        running += Decimal(move)
        rows.append(Txn(
            page_no=1 + index // 5, source_row=index, narration=narration,
            date=date(2025, 5, 2 + index), printed_amount=abs(Decimal(move)),
            balance=running, ocr_confidence=88 if index % 3 else 61,
        ))
    apply_directions(rows, OPENING)
    # One row the chain could not settle, as the real fixtures produce.
    rows[4].balance = Decimal("-9200000.00")
    rows[4].printed_amount = Decimal("999999.00")
    report, diagnoses = settle(rows, OPENING)
    result = ParseResult(rows=rows, page_count=24, anchors=[
        Anchor("PAGE_TOTAL_CREDIT", 1, 0, Decimal("1503399.00")),
        Anchor("PAGE_TOTAL_DEBIT", 1, 0, Decimal("1322473.00")),
    ])
    return result, report, diagnoses


def main(outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(tokens.qss())

    window = MainWindow(AuditStore(":memory:"))
    window.resize(1600, 940)
    result, report, diagnoses = demo_job()

    window._jobs = [{
        "client": "NEW PAUL MEDICOS", "bank": "Tripura Gramin", "account": "8101250809801",
        "type": "Cash Credit", "fy": "2025-26", "source": "scanned",
        "status": "Needs review", "progress": 100,
        "txns": len(result.rows), "flagged": 2, "id": 1,
    }, {
        "client": "M/S BIPUL PETROLEUM", "bank": "SBI Churaibari", "account": "44283681635",
        "type": "Current", "fy": "2025-26", "source": "scanned",
        "status": "Queued", "progress": 0, "txns": "—", "flagged": "—", "id": 2,
    }]
    window.queue.set_jobs(window._jobs)
    window.queue.set_footer(
        "148 learned rules are active. They apply to every new statement you drop."
    )

    subtitle = "NEW PAUL MEDICOS · A/c 8101250809801 · Cash Credit · FY 2025-26"
    window.review.set_rows(result.rows, bank="Tripura Gramin", subtitle=subtitle)
    window.reconcile.set_job(report, diagnoses, result, subtitle=subtitle)
    window.export.set_state(
        reconciled=report.reconciled, variance=report.variance,
        unresolved=report.unresolved, subtitle=subtitle,
    )
    window.review.table.selectRow(0)
    window.review.assign(0, "NEFT_OUT")
    window.store.append(actor="Sujata D.", action="JOB_PARSED",
                        detail=f"{len(result.rows)} rows, 2 unresolved")
    window.drawer.refresh()

    shots = {
        "queue": 0, "review": 1, "reconcile": 2, "export": 3, "accuracy": 4,
    }
    for name, index in shots.items():
        window.nav.setCurrentRow(index)
        window.stack.setCurrentIndex(index)
        window.grab().save(str(outdir / f"{name}.png"))
        print(f"  wrote {name}.png")

    window.drawer.show()
    window.nav.setCurrentRow(2)
    window.stack.setCurrentIndex(2)
    window.grab().save(str(outdir / "audit_drawer.png"))
    print("  wrote audit_drawer.png")

    dialog = OverrideDialog(report.variance or Decimal("-19125.40"))
    dialog.resize(560, 380)
    dialog.reason.setPlainText(
        "Page 14 is illegible where the printer skipped; confirmed against the "
        "branch's own statement copy by CA Suhag."
    )
    dialog.grab().save(str(outdir / "override.png"))
    print("  wrote override.png")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/sb_shots")
    raise SystemExit(main(target))
