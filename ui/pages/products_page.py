"""Products page: catalogue table with search, filters, CRUD, import."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.constants import SORT_OPTIONS, StockStatus
from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from core.money import format_money
from services import product_service
from ui.dialogs.base import ConfirmDialog
from ui.dialogs.import_dialog import ImportDialog
from ui.dialogs.product_dialog import ProductDialog
from ui.widgets.badge import StatusBadge
from ui.widgets.banner import Banner
from ui.widgets.fields import Combo, SearchInput
from ui.widgets.images import Thumbnail
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.products")

STATUS_FILTERS = ("All", StockStatus.IN_STOCK, StockStatus.LOW_STOCK,
                  StockStatus.OUT_OF_STOCK, "Archived")


def _thumb(product) -> Thumbnail:
    thumb = Thumbnail(34)
    thumb.set_image(product.image_path, product.name)
    return thumb


class ProductsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self._rows: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        layout.addLayout(self._toolbar())

        self.banner = Banner(self)
        layout.addWidget(self.banner)

        self.summary = QLabel("")
        self.summary.setObjectName("MetricLabel")
        layout.addWidget(self.summary)

        self.table = DataTable([
            Column("", "center", 52),
            Column("Code", "left", 110),
            Column("Product", stretch=True),
            Column("Category", "left", 140),
            Column("Unit", "left", 80),
            Column("Cost", "right", 110),
            Column("Selling", "right", 110),
            Column("Stock", "right", 80),
            Column("Status", "center", 110),
        ])
        self.table.set_empty_state(
            "No products have been added yet. Download the Excel template or add a "
            "product manually.",
            title="Your catalogue is empty",
            action_label="Add Product",
            callback=self.open_add_dialog,
        )
        self.table.row_double_clicked.connect(lambda _row: self.edit_selected())
        layout.addWidget(self.table, stretch=1)

        layout.addLayout(self._actions())

    # ---------------------------------------------------------------- layout

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.search = SearchInput("Search code or name...")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search)

        self.category_filter = Combo()
        self.category_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.category_filter)

        self.status_filter = Combo(list(STATUS_FILTERS))
        self.status_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.status_filter)

        self.sort_filter = Combo(list(SORT_OPTIONS))
        self.sort_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.sort_filter)

        row.addStretch(1)

        template = QPushButton("Template")
        template.setProperty("variant", "quiet")
        template.setToolTip("Download the official VEYRA import workbook")
        template.clicked.connect(self._download_template)
        import_button = QPushButton("Import")
        import_button.setProperty("variant", "quiet")
        import_button.clicked.connect(self.start_import)
        add = QPushButton("Add Product")
        add.setProperty("variant", "primary")
        add.clicked.connect(self.open_add_dialog)
        row.addWidget(template)
        row.addWidget(import_button)
        row.addWidget(add)
        return row

    def _actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.edit_button = QPushButton("Edit")
        self.edit_button.clicked.connect(self.edit_selected)
        self.archive_button = QPushButton("Archive")
        self.archive_button.setProperty("variant", "quiet")
        self.archive_button.clicked.connect(self.toggle_archive)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setProperty("variant", "danger")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.edit_button, self.archive_button, self.delete_button):
            button.setEnabled(False)
            row.addWidget(button)
        row.addStretch(1)
        hint = QLabel("Double-click a row to edit. Products with history are archived, "
                      "never deleted.")
        hint.setObjectName("FieldHint")
        row.addWidget(hint)
        self.table.itemSelectionChanged.connect(self._sync_actions)
        return row

    def _sync_actions(self) -> None:
        product = self.selected_product()
        enabled = product is not None
        self.edit_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled)
        self.archive_button.setEnabled(enabled)
        if product is not None:
            self.archive_button.setText("Restore" if not product.is_active else "Archive")

    # ------------------------------------------------------------------ data

    def selected_product(self):
        row = self.table.selected_row()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def refresh(self) -> None:
        categories = product_service.list_categories()
        current = self.category_filter.currentText()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All Categories")
        for category in categories:
            self.category_filter.addItem(category.name, category.id)
        index = self.category_filter.findText(current)
        self.category_filter.setCurrentIndex(max(index, 0))
        self.category_filter.blockSignals(False)

        category_id = self.category_filter.currentData() or None
        try:
            self._rows = product_service.list_products(
                search=self.search.text().strip() or None,
                category_id=category_id,
                status=self.status_filter.currentText(),
                sort=self.sort_filter.currentText(),
                include_inactive=self.status_filter.currentText() == "Archived",
            )
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            self._rows = []
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "products list", exc)
            self.banner.show_message(f"The catalogue could not be loaded. Reference {reference}.",
                                     "danger")
            self._rows = []

        self.table.set_rows([
            [
                _thumb(product),
                product.code,
                product.name,
                product.category_name or "Uncategorised",
                product.unit,
                format_money(product.cost_price),
                format_money(product.selling_price),
                f"{product.stock_quantity:,}",
                StatusBadge("Archived" if not product.is_active else product.stock_status,
                            "neutral" if not product.is_active else None),
            ]
            for product in self._rows
        ])

        stats = product_service.catalogue_stats()
        self.summary.setText(
            f"{stats['products']} products, {stats['categories']} categories, "
            f"{stats['archived']} archived."
        )
        self._sync_actions()

    # --------------------------------------------------------------- actions

    def open_add_dialog(self) -> None:
        dialog = ProductDialog(self, categories=product_service.category_names())
        if dialog.exec() and dialog.submitted:
            self.refresh()
            self.window_ref.notify(dialog.result_message)

    def edit_selected(self) -> None:
        product = self.selected_product()
        if product is None:
            return
        dialog = ProductDialog(self, product=product,
                               categories=product_service.category_names())
        if dialog.exec() and dialog.submitted:
            self.refresh()
            self.window_ref.notify(dialog.result_message)

    def toggle_archive(self) -> None:
        product = self.selected_product()
        if product is None:
            return
        target = not product.is_active
        verb = "Restore" if target else "Archive"
        if not ConfirmDialog.ask(
            self,
            f"{verb} {product.name}?",
            "Archived products are hidden from the POS and from new sales, but their "
            "history stays intact."
            if not target
            else "The product returns to the POS and the catalogue.",
            confirm_label=verb,
            variant="primary" if target else "danger",
        ):
            return
        try:
            message = product_service.set_active(product.id, target)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        self.refresh()
        self.window_ref.notify(message)

    def delete_selected(self) -> None:
        product = self.selected_product()
        if product is None:
            return
        if not ConfirmDialog.ask(
            self,
            f"Delete {product.name}?",
            "Products with sales or stock history are archived instead of deleted so "
            "reports and receipts stay correct.",
            confirm_label="Delete",
            variant="danger",
        ):
            return
        try:
            _outcome, message = product_service.delete_product(product.id)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        self.refresh()
        self.window_ref.notify(message, "warning" if "archived" in message else "success")

    def start_import(self) -> None:
        dialog = ImportDialog(self)
        dialog.exec()
        if dialog.summary is not None:
            self.refresh()
            self.window_ref.notify(dialog.summary.message)

    def _download_template(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        from imports.excel_template import generate_template

        path, _ = QFileDialog.getSaveFileName(
            self, "Save the import template", "VEYRA_Product_Import_Template.xlsx",
            "Excel workbooks (*.xlsx)",
        )
        if not path:
            return
        try:
            written = generate_template(path)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        self.window_ref.notify(f"Template saved to {written.name}.")

    # ------------------------------------------------------- shell callbacks

    def focus_product(self, product_id: int) -> None:
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.refresh()
        for row, product in enumerate(self._rows):
            if product.id == product_id:
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 1))
                return
        self.banner.show_message("That product is not in the current filter.", "warning")

    def focus_category(self, category_id: int) -> None:
        self.refresh()
        index = self.category_filter.findData(category_id)
        if index >= 0:
            self.category_filter.setCurrentIndex(index)
