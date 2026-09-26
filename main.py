"""VEYRA entry point.

Boots the offline database, installs the saved theme, builds the shell and its
seven pages, and makes sure an unexpected crash is written to the log with a
short reference instead of a traceback (blueprint 16.2).
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import APP_NAME, APP_VERSION
from core.logger import get_logger, log_unexpected
from core.paths import ensure_dirs
from db.init_db import ensure_settings_row, init_database
from services import settings_service
from ui import theme as theme_module
from ui.main_window import MainWindow
from ui.pages import (
    DashboardPage,
    InventoryPage,
    PosPage,
    ProductsPage,
    ReportsPage,
    SalesPage,
    SettingsPage,
)

logger = get_logger("app")

PAGES: tuple[tuple[str, object, str, str], ...] = (
    ("dashboard", DashboardPage, "Dashboard", "Today's sales, stock health and quick actions"),
    ("products", ProductsPage, "Products", "Catalogue, prices, images and imports"),
    ("inventory", InventoryPage, "Inventory", "Stock levels and the movement ledger"),
    ("pos", PosPage, "Point of Sale", "Sell products and complete an invoice"),
    ("sales", SalesPage, "Sales", "Invoice history and receipts"),
    ("reports", ReportsPage, "Reports", "Sales, stock and profit reports with exports"),
    ("settings", SettingsPage, "Settings", "Business profile, VAT, appearance and backups"),
)


def _install_excepthook(app: QApplication) -> None:
    def handle(kind, value, traceback) -> None:  # noqa: ANN001 - sys.excepthook signature
        reference = log_unexpected(logger, "application", value)
        logger.critical("Unhandled exception", exc_info=(kind, value, traceback))
        QMessageBox.critical(
            None,
            f"{APP_NAME} hit an unexpected problem",
            "VEYRA could not finish that action. Nothing was reported as successful.\n\n"
            f"Error reference {reference} - the technical detail is in logs/veyra.log.",
        )

    sys.excepthook = handle
    app.setProperty("veyra_excepthook", handle)


def build_window() -> MainWindow:
    window = MainWindow()
    for key, page_class, title, subtitle in PAGES:
        window.add_page(key, page_class(window), title=title, subtitle=subtitle)
    window.show_page("dashboard")
    return window


def main() -> int:
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    _install_excepthook(app)

    try:
        init_database()
        ensure_settings_row()
        settings = settings_service.get_settings()
        theme_module.apply_theme(app, settings.theme, settings.font_size)
    except Exception as exc:  # noqa: BLE001 - a broken database must be reported clearly
        reference = log_unexpected(logger, "startup", exc)
        QMessageBox.critical(
            None,
            f"{APP_NAME} could not start",
            "The database could not be opened, so VEYRA stopped before showing any data.\n\n"
            f"Error reference {reference} - see logs/veyra.log for the detail. "
            "Restoring a recent backup from Settings may fix this.",
        )
        return 1

    logger.info("Starting %s %s", APP_NAME, APP_VERSION)
    window = build_window()
    window.show()
    status = app.exec()
    logger.info("%s closed with status %s", APP_NAME, status)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
