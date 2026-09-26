"""The application shell: dark sidebar, header, page stack and toasts.

Blueprint 3.1/3.2: the sidebar is persistent, the active section has a strong
state, and the header carries the page title, the global search (products,
categories, invoice numbers only) and a compact owner affordance.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.config import APP_NAME, APP_VERSION
from core.logger import get_logger
from services import reporting_service, settings_service
from services.settings_service import SettingsSnapshot
from ui import theme as theme_module
from ui.widgets.fields import SearchInput
from ui.widgets.images import avatar_pixmap
from ui.widgets.toast import ToastHost

logger = get_logger("ui.shell")

SIDEBAR_WIDTH = 224

NAV_ITEMS: tuple[tuple[str, str], ...] = (
    ("dashboard", "Dashboard"),
    ("products", "Products"),
    ("inventory", "Inventory"),
    ("pos", "POS"),
    ("sales", "Sales"),
    ("reports", "Reports"),
    ("settings", "Settings"),
)


class MainWindow(QMainWindow):
    """Hosts every page and owns navigation, search and notifications."""

    page_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - Business Inventory & Sales")
        self.setMinimumSize(1180, 740)
        self.resize(1360, 840)

        self.settings: SettingsSnapshot = settings_service.get_settings()
        self._pages: dict[str, QWidget] = {}
        self._titles: dict[str, tuple[str, str]] = {}
        self._nav_buttons: dict[str, QPushButton] = {}

        root = QWidget(self)
        root.setObjectName("AppRoot")
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_header())
        self._refresh_owner()

        self.stack = QStackedWidget()
        content.addWidget(self.stack)
        root_layout.addLayout(content, stretch=1)

        self.toasts = ToastHost(self)

        self.apply_settings_theme()

    # ------------------------------------------------------------------ shell

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 14)
        layout.setSpacing(4)

        brand = QLabel(APP_NAME)
        brand.setObjectName("BrandTitle")
        layout.addWidget(brand)
        subtitle = QLabel("Inventory & Sales")
        subtitle.setObjectName("BrandSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(14)

        section = QLabel("MENU")
        section.setObjectName("SidebarSection")
        layout.addWidget(section)

        for key, label in NAV_ITEMS:
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, page=key: self.show_page(page))
            self._nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self._owner_avatar = QLabel()
        self._owner_avatar.setFixedSize(38, 38)
        self._owner_name = QLabel()
        self._owner_name.setObjectName("OwnerName")
        self._owner_role = QLabel("Owner")
        self._owner_role.setObjectName("OwnerRole")

        owner_row = QHBoxLayout()
        owner_row.setSpacing(10)
        owner_row.addWidget(self._owner_avatar)
        owner_text = QVBoxLayout()
        owner_text.setSpacing(1)
        owner_text.addWidget(self._owner_name)
        owner_text.addWidget(self._owner_role)
        owner_row.addLayout(owner_text, stretch=1)
        layout.addLayout(owner_row)

        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("BrandSubtitle")
        layout.addWidget(version)
        return sidebar
    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(74)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 10, 24, 10)
        layout.setSpacing(14)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.page_title = QLabel()
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("PageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        layout.addLayout(titles, stretch=1)

        self.date_label = QLabel(datetime.now().strftime("%a, %d %b %Y"))
        self.date_label.setObjectName("PageSubtitle")
        layout.addWidget(self.date_label)

        self.search = SearchInput("Search products, categories, invoices...")
        self.search.setFixedWidth(300)
        self.search.returnPressed.connect(self._run_global_search)
        layout.addWidget(self.search)

        self.owner_chip = QPushButton()
        self.owner_chip.setFlat(True)
        self.owner_chip.setProperty("variant", "ghost")
        self.owner_chip.setCursor(Qt.PointingHandCursor)
        self.owner_chip.setToolTip("Open Settings")
        self.owner_chip.clicked.connect(lambda: self.show_page("settings"))
        layout.addWidget(self.owner_chip)

        return header

    # ------------------------------------------------------------------ pages

    def add_page(self, key: str, widget: QWidget, *, title: str, subtitle: str = "") -> None:
        self._pages[key] = widget
        self._titles[key] = (title, subtitle)
        self.stack.addWidget(widget)

    def show_page(self, key: str) -> None:
        widget = self._pages.get(key)
        if widget is None:
            logger.warning("Unknown page requested: %s", key)
            return
        self.stack.setCurrentWidget(widget)
        for nav_key, button in self._nav_buttons.items():
            button.setChecked(nav_key == key)
        title, subtitle = self._titles.get(key, ("", ""))
        self.set_header(title, subtitle)
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            refresh()
        self.page_changed.emit(key)

    def set_header(self, title: str, subtitle: str = "") -> None:
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self.page_subtitle.setVisible(bool(subtitle))

    def current_page(self) -> str:
        for key, widget in self._pages.items():
            if widget is self.stack.currentWidget():
                return key
        return ""

    def page(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    # ------------------------------------------------------------------ theme

    def apply_settings_theme(self) -> None:
        from PySide6.QtWidgets import QApplication

        theme_module.apply_theme(
            QApplication.instance(), self.settings.theme, self.settings.font_size
        )

    def reload_settings(self) -> None:
        """Called by Settings after a save so the shell follows the profile."""
        self.settings = settings_service.get_settings()
        self.apply_settings_theme()
        self._refresh_owner()

    def _refresh_owner(self) -> None:
        name = self.settings.owner_name or self.settings.business_name
        self._owner_name.setText(name)
        self._owner_avatar.setPixmap(
            avatar_pixmap(self.settings.profile_image, name or "V", 38)
        )
        self.owner_chip.setText(name)

    # ------------------------------------------------------------------ misc

    def notify(self, message: str, kind: str = "success") -> None:
        self.toasts.show(message, kind)

    def _run_global_search(self) -> None:
        term = self.search.text().strip()
        if len(term) < 2:
            return
        try:
            results = reporting_service.global_search(term)
        except Exception:  # noqa: BLE001 - search must never break the shell
            logger.exception("Global search failed for %r", term)
            self.notify("Search is unavailable right now.", "warning")
            return

        menu = QMenu(self)
        found = False
        for group, title, handler in (
            ("products", "Products", self.open_product),
            ("categories", "Categories", self.open_category),
            ("invoices", "Invoices", self.open_invoice),
        ):
            entries = results[group]
            if not entries:
                continue
            found = True
            section = QAction(title.upper(), menu)
            section.setDisabled(True)
            menu.addAction(section)
            for entry in entries:
                action = QAction(f"{entry['label']}  -  {entry['detail']}", menu)
                action.triggered.connect(
                    lambda _=False, target=handler, entry_id=entry["id"]: target(entry_id)
                )
                menu.addAction(action)
        if not found:
            menu.addAction(f"No products, categories or invoices match '{term}'.")
            menu.actions()[-1].setDisabled(True)
        menu.exec(self.search.mapToGlobal(self.search.rect().bottomLeft()))

    def open_product(self, product_id: int) -> None:
        self.show_page("products")
        focus = getattr(self._pages["products"], "focus_product", None)
        if callable(focus):
            focus(product_id)

    def open_category(self, category_id: int) -> None:
        self.show_page("products")
        focus = getattr(self._pages["products"], "focus_category", None)
        if callable(focus):
            focus(category_id)

    def open_invoice(self, sale_id: int) -> None:
        self.show_page("sales")
        focus = getattr(self._pages["sales"], "focus_sale", None)
        if callable(focus):
            focus(sale_id)

    def resizeEvent(self, event):  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self.toasts.resize(self.centralWidget().size())
