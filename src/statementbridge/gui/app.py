"""Application entry point.

Runs offscreen without complaint when ``QT_QPA_PLATFORM=offscreen`` is set,
which is how the screens are rendered for review on a machine with no display.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ..store.audit import AuditStore
from . import tokens
from .main_window import MainWindow

#: Beside the executable on the client's machine; overridden in tests.
DEFAULT_DB = Path.home() / ".statementbridge" / "statementbridge.db"


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("StatementBridge")
    app.setOrganizationName("SuhagKuti Tax & Legal Services")
    app.setStyleSheet(tokens.qss())
    window = MainWindow(AuditStore(DEFAULT_DB))
    return app, window


def main(argv: list[str] | None = None) -> int:
    app, window = build_app(argv)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
