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


def _repopulate(combo: Combo, placeholder: str, entries: list[tuple[str, object]]) -> None:
    """Refill a filter combo, keeping the current choice while it still applies."""
    current = combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(placeholder)
    for label, data in entries:
        combo.addItem(label, data)
    combo.setCurrentIndex(max(combo.findText(current), 0))
    combo.blockSignals(False)


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
            Column("Category", "left", 130),
            Column("Subcategory", "left", 130),
            Column("Brand", "left", 110),
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

        self.search = SearchInput("Search code, name, brand...")
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search)

        self.category_filter = Combo()
        self.category_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.category_filter)

        self.subcategory_filter = Combo()
        self.subcategory_filter.setToolTip("Subcategories inside the selected category")
        self.subcategory_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.subcategory_filter)

        self.brand_filter = Combo()
        self.brand_filter.setToolTip("Brands inside the selected category and subcategory")
        self.brand_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.brand_filter)

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

    def _reload_filters(self) -> None:
        """Cascade Category -> Subcategory -> Brand so each list only offers real values."""
        _repopulate(
            self.category_filter,
            "All Categories",
            [(category.name, category.id) for category in product_service.list_categories()],
        )
        category_id = self.category_filter.currentData() or None
        _repopulate(
            self.subcategory_filter,
            "All Subcategories",
            [(name, name) for name in product_service.subcategory_names(category_id=category_id)],
        )
        subcategory = self.subcategory_filter.currentData() or None
        _repopulate(
            self.brand_filter,
            "All Brands",
            [
                (name, name)
                for name in product_service.brand_names(
                    category_id=category_id, subcategory=subcategory
                )
            ],
        )

    def refresh(self) -> None:
        self._reload_filters()

        try:
            self._rows = product_service.list_products(
                search=self.search.text().strip() or None,
                category_id=self.category_filter.currentData() or None,
                subcategory=self.subcategory_filter.currentData() or None,
                brand=self.brand_filter.currentData() or None,
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
                product.subcategory_name or "-",
                product.brand_name or "-",
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
            f"{len(product_service.subcategory_names())} subcategories, "
            f"{len(product_service.brand_names())} brands, "
            f"{stats['archived']} archived."
        )
        self._sync_actions()

    # --------------------------------------------------------------- actions

    def _dialog_kwargs(self) -> dict:
        """Existing hierarchy values, so the dialog suggests rather than retypes."""
        return {
            "categories": product_service.category_names(),
            "subcategories": product_service.subcategory_names(),
            "brands": product_service.brand_names(),
        }

    def open_add_dialog(self) -> None:
        dialog = ProductDialog(self, **self._dialog_kwargs())
        if dialog.exec() and dialog.submitted:
            self.refresh()
            self.window_ref.notify(dialog.result_message)

    def edit_selected(self) -> None:
        product = self.selected_product()
        if product is None:
            return
        dialog = ProductDialog(self, product=product, **self._dialog_kwargs())
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
        self.subcategory_filter.setCurrentIndex(0)
        self.brand_filter.setCurrentIndex(0)
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
