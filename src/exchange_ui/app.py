"""Start the desktop app: ``exchange-app`` or ``python -m exchange_ui``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from exchange.errors import ExchangeError
from exchange.paths import default_db_path
from exchange_ui import theme


def make_app(argv: list[str]) -> QApplication:
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Exchange")
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setFont(theme.ui_font())
    app.setStyleSheet(theme.STYLE)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exchange-app", description="Exchange desktop app")
    parser.add_argument("--db", type=Path, default=None, help=f"library database (default: {default_db_path()})")
    args = parser.parse_args(argv)
    app = make_app(sys.argv[:1])

    from exchange_ui.main_window import MainWindow
    from exchange_ui.service import LibraryService

    try:
        service = LibraryService(args.db or default_db_path())
    except ExchangeError as exc:
        QMessageBox.critical(None, "Exchange", f"Exchange could not start:\n\n{exc}")
        return 2
    window = MainWindow(service)
    window.show()
    try:
        return app.exec()
    finally:
        service.close()
