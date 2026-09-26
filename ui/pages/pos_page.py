"""Point of Sale page: product grid on the left, live cart on the right.

Blueprint 9: tiles show name, price and stock; out-of-stock tiles stay visible
but cannot be selected. Totals are always priced by the service layer using the
current VAT settings, never by arithmetic in the widget.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from core.money import ZERO, format_money
from reports.pdf_receipt import export_receipt_pdf
from services import pos_service, product_service, reporting_service, settings_service
from services.pos_service import Cart
from ui.dialogs.base import ConfirmDialog, MessageDialog
from ui.dialogs.checkout_dialog import CheckoutDialog
from ui.dialogs.discount_dialog import DiscountDialog
from ui.dialogs.quantity_dialog import QuantityDialog
from ui.widgets.banner import Banner
from ui.widgets.busy import BusyOverlay
from ui.widgets.card import MetricRow
from ui.widgets.fields import Combo, SearchInput
from ui.widgets.images import Thumbnail
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.pos")

TILE_COLUMNS = 3


class ProductTile(QFrame):
    """One sellable product in the POS grid."""

    clicked = Signal(object)

    def __init__(self, product, parent: QWidget | None = None):
        super().__init__(parent)
        self.product = product
        self.setObjectName("ProductTile")
        self.setFixedHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setProperty("disabled", product.stock_quantity <= 0)
        self.setToolTip(
            "Out of stock - record a stock movement before selling."
            if product.stock_quantity <= 0
            else f"{product.code} - {format_money(product.selling_price)} per {product.unit}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        thumb = Thumbnail(48)
        thumb.set_image(product.image_path, product.name)
        layout.addWidget(thumb)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(product.name)
        name.setObjectName("TileName")
        name.setWordWrap(True)
        price = QLabel(format_money(product.selling_price))
        price.setObjectName("TilePrice")
        stock = QLabel(
            f"{product.stock_quantity:,} {product.unit} in stock"
            if product.stock_quantity > 0
            else "Out of stock"
        )
        stock.setObjectName("TileStock")
        text.addWidget(name)
        text.addWidget(price)
        text.addWidget(stock)
        text.addStretch(1)
        layout.addLayout(text, 1)

        self.setCursor(
            Qt.CursorShape.ForbiddenCursor
            if product.stock_quantity <= 0
            else Qt.CursorShape.PointingHandCursor
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton and self.product.stock_quantity > 0:
            self.clicked.emit(self.product)
        super().mousePressEvent(event)


class PosPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self.cart = Cart()
        self.settings = settings_service.get_settings()
        self._grid_widgets: list[QWidget] = []
        self._products: list = []

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(14)
        root.addWidget(self._build_browser(), stretch=1)
        root.addWidget(self._build_cart_panel())

        self.banner = Banner(self)
        self.banner.setParent(self)
        self._browser_layout.insertWidget(0, self.banner)

        self.busy = BusyOverlay(self)

    # ------------------------------------------------------------- left pane

    def _build_browser(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        self._browser_layout = outer

        header = QLabel("Products")
        header.setObjectName("CardTitle")
        outer.addWidget(header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = SearchInput("Search product or code...")
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self._reload_grid)
        self.search.returnPressed.connect(self._add_first_match)
        toolbar.addWidget(self.search)

        self.category_filter = Combo()
        self.category_filter.currentIndexChanged.connect(self._reload_grid)
        toolbar.addWidget(self.category_filter)
        toolbar.addStretch(1)

        self.grid_summary = QLabel("")
        self.grid_summary.setObjectName("FieldHint")
        toolbar.addWidget(self.grid_summary)
        outer.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(2, 2, 8, 2)
        self.grid.setSpacing(10)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.grid_host)
        outer.addWidget(scroll, stretch=1)
        return panel

    def _populate_grid(self) -> None:
        for widget in self._grid_widgets:
            self.grid.removeWidget(widget)
            widget.deleteLater()
        self._grid_widgets.clear()

        if not self._products:
            empty = QLabel(
                "No products match this search. Clear the filters, or add products first."
            )
            empty.setObjectName("EmptyState")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(empty, 0, 0, 1, TILE_COLUMNS)
            self._grid_widgets.append(empty)
            return

        for index, product in enumerate(self._products):
            tile = ProductTile(product)
            tile.clicked.connect(self._add_product)
            self.grid.addWidget(tile, index // TILE_COLUMNS, index % TILE_COLUMNS)
            self._grid_widgets.append(tile)

    def _reload_grid(self) -> None:
        category_id = self.category_filter.currentData() or None
        try:
            self._products = product_service.pos_products(
                search=self.search.text().strip() or None,
                category_id=category_id,
            )
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            self._products = []
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "pos product grid", exc)
            self.banner.show_message(
                f"Products could not be loaded. Reference {reference}.", "danger"
            )
            self._products = []
        available = sum(1 for product in self._products if product.stock_quantity > 0)
        self.grid_summary.setText(f"{available} of {len(self._products)} products available")
        self._populate_grid()

    # ------------------------------------------------------------ right pane

    def _build_cart_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("CartPanel")
        panel.setFixedWidth(400)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Cart / Order Summary")
        title.setObjectName("CardTitle")
        self.invoice_label = QLabel("")
        self.invoice_label.setObjectName("CardSubtitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.invoice_label)
        layout.addLayout(title_row)

        self.table = DataTable([
            Column("Product", stretch=True),
            Column("Qty", "right", 54),
            Column("Total", "right", 96),
            Column("", "center", 40),
        ])
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.set_empty_state("The cart is empty. Click a product to add it.")
        self.table.row_double_clicked.connect(lambda _row: self.edit_quantity())
        layout.addWidget(self.table, stretch=1)

        self.count_label = QLabel("")
        self.count_label.setObjectName("FieldHint")
        layout.addWidget(self.count_label)

        self.subtotal_row = MetricRow("Subtotal", format_money(ZERO))
        self.vat_row = MetricRow(self.settings.vat_label, format_money(ZERO))
        self.discount_row = MetricRow("Discount", format_money(ZERO))
        self.total_row = MetricRow("TOTAL", format_money(ZERO), strong=True)
        for row in (self.subtotal_row, self.vat_row, self.discount_row, self.total_row):
            layout.addWidget(row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.quantity_button = QPushButton("Quantity")
        self.quantity_button.clicked.connect(self.edit_quantity)
        self.discount_button = QPushButton("Discount")
        self.discount_button.clicked.connect(self.edit_discount)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setProperty("variant", "quiet")
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button = QPushButton("Clear Cart")
        self.clear_button.setProperty("variant", "quiet")
        self.clear_button.clicked.connect(self.clear_cart)
        for button in (self.quantity_button, self.discount_button,
                       self.remove_button, self.clear_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.complete_button = QPushButton("COMPLETE SALE")
        self.complete_button.setProperty("variant", "primary")
        self.complete_button.setMinimumHeight(46)
        self.complete_button.clicked.connect(self.complete_sale)
        layout.addWidget(self.complete_button)
        return panel

    # ------------------------------------------------------------------ cart

    def _selected_product_id(self) -> int | None:
        row = self.table.selected_row()
        if row < 0 or row >= len(self.cart.items):
            return None
        return self.cart.items[row].product_id

    def _add_product(self, product) -> None:
        try:
            self.cart.add(product, 1)
        except VeyraError as error:
            self.banner.show_message(error.message, "warning")
            return
        self.banner.clear()
        self._refresh_cart()

    def _add_first_match(self) -> None:
        available = [product for product in self._products if product.stock_quantity > 0]
        if not available:
            self.banner.show_message("No matching product is in stock.", "warning")
            return
        product = available[0]
        in_cart = self.cart.quantity_of(product.id)
        if in_cart:
            self._prompt_quantity(product, in_cart)
            return
        self._add_product(product)

    def _prompt_quantity(self, product, current: int) -> None:
        chosen = QuantityDialog.ask(
            self,
            product_name=product.name,
            unit=product.unit,
            available_stock=product.stock_quantity,
            current=current,
            price=format_money(product.selling_price),
        )
        if chosen is None:
            return
        try:
            if current:
                self.cart.set_quantity(product.id, chosen)
            else:
                self.cart.add(product, chosen)
        except VeyraError as error:
            self.banner.show_message(error.message, "warning")
            return
        self.banner.clear()
        self._refresh_cart()

    def edit_quantity(self) -> None:
        product_id = self._selected_product_id()
        item = self.cart.get(product_id) if product_id else None
        if item is None:
            self.banner.show_message("Select a cart line first.", "info")
            return
        product = product_service.get_product(item.product_id)
        if product is None:
            self.banner.show_message("That product no longer exists.", "warning")
            self.cart.remove(item.product_id)
            self._refresh_cart()
            return
        self._prompt_quantity(product, item.quantity)

    def remove_selected(self) -> None:
        product_id = self._selected_product_id()
        item = self.cart.get(product_id) if product_id else None
        if item is None:
            self.banner.show_message("Select a cart line first.", "info")
            return
        self.cart.remove(product_id)
        self._refresh_cart()

    def edit_discount(self) -> None:
        if self.cart.is_empty:
            self.banner.show_message("Add a product before applying a discount.", "info")
            return
        priced = self._price()
        if priced is None:
            return
        chosen = DiscountDialog.ask(
            self,
            subtotal=priced.subtotal,
            current=self.cart.discount,
            item_count=priced.item_count,
        )
        if chosen is None:
            return
        try:
            self.cart.set_discount(chosen)
        except VeyraError as error:
            self.banner.show_message(error.message, "warning")
            return
        self.banner.clear()
        self._refresh_cart()

    def clear_cart(self) -> None:
        if self.cart.is_empty:
            return
        if not ConfirmDialog.ask(
            self,
            "Clear the cart?",
            "Every line and the discount will be removed. No sale has been recorded yet.",
            confirm_label="Clear Cart",
            variant="danger",
        ):
            return
        self.cart.clear()
        self.banner.clear()
        self._refresh_cart()

    def _price(self):
        try:
            return pos_service.quote_cart(self.cart)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return None
        except Exception as exc:  # noqa: BLE001
            reference = log_unexpected(logger, "cart pricing", exc)
            self.banner.show_message(
                f"The cart could not be priced. Reference {reference}.", "danger"
            )
            return None

    def _refresh_cart(self) -> None:
        items = self.cart.items
        rows = []
        for item in items:
            remove = QPushButton("×")
            remove.setProperty("variant", "quiet")
            remove.setFixedSize(28, 24)
            remove.setToolTip(f"Remove {item.name}")
            remove.clicked.connect(
                lambda _checked=False, product_id=item.product_id: (
                    self.cart.remove(product_id), self._refresh_cart()
                )
            )
            rows.append([
                item.name,
                f"{item.quantity:,}",
                format_money(item.line_total),
                remove,
            ])
        self.table.set_rows(rows)

        priced = self._price() if items else None
        if priced is None:
            subtotal = vat = discount = total = ZERO
            count = quantity = 0
        else:
            subtotal, vat, discount, total = priced.subtotal, priced.vat, priced.discount, priced.total
            count, quantity = priced.item_count, priced.total_quantity

        self.subtotal_row.set_value(format_money(subtotal))
        self.vat_row.set_label(self.settings.vat_label)
        self.vat_row.set_value(format_money(vat))
        self.discount_row.set_value(f"-{format_money(discount)}" if discount else format_money(ZERO))
        self.total_row.set_value(format_money(total))
        self.count_label.setText(
            f"{count} product{'s' if count != 1 else ''} - {quantity} unit{'s' if quantity != 1 else ''}"
        )

        has_lines = bool(items)
        self.quantity_button.setEnabled(has_lines)
        self.remove_button.setEnabled(has_lines)
        self.discount_button.setEnabled(has_lines)
        self.clear_button.setEnabled(has_lines)
        self.complete_button.setEnabled(has_lines)

    # ---------------------------------------------------------- complete sale

    def complete_sale(self) -> None:
        if self.cart.is_empty:
            self.banner.show_message(
                "The cart is empty. Add at least one product.", "warning"
            )
            return
        priced = self._price()
        if priced is None:
            return
        checkout = CheckoutDialog.ask(
            self,
            priced=priced,
            invoice_number=self._next_invoice(),
            vat_label="VAT",
        )
        if checkout is None:
            return

        self.busy.start("Completing sale...")
        try:
            result = pos_service.complete_sale(self.cart, note=checkout.note)
        except VeyraError as error:
            self.busy.stop()
            self.banner.show_message(error.message, "danger")
            self.window_ref.notify(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "complete sale", exc)
            self.busy.stop()
            message = (
                "Sale could not be completed. No stock was changed. "
                f"Reference {reference}."
            )
            self.banner.show_message(message, "danger")
            self.window_ref.notify(message, "danger")
            return
        self.busy.stop()

        self.banner.clear()
        self.refresh()
        self.window_ref.notify(result.message)
        self._offer_receipt(result)

    def _offer_receipt(self, result) -> None:
        if not ConfirmDialog.ask(
            self,
            "Sale completed",
            f"{result.message}\n\nSave a PDF receipt for this sale?",
            confirm_label="Save Receipt",
            variant="primary",
        ):
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save receipt",
            f"{result.invoice_number}.pdf",
            "PDF files (*.pdf)",
        )
        if not path:
            return
        sale = reporting_service.get_sale(result.sale_id)
        if sale is None:
            MessageDialog.show_message(
                self, "Receipt unavailable",
                "The sale was recorded but could not be re-read for printing.",
                kind="warning",
            )
            return
        try:
            written = export_receipt_pdf(sale, path, settings=self.settings)
        except VeyraError as error:
            MessageDialog.show_message(
                self, "Receipt not saved", error.message, kind="danger"
            )
            return
        except Exception as exc:  # noqa: BLE001
            reference = log_unexpected(logger, "receipt export", exc)
            MessageDialog.show_message(
                self, "Receipt not saved",
                f"The receipt could not be written. Reference {reference}. "
                "The sale itself was saved correctly.",
                kind="danger",
            )
            return
        self.window_ref.notify(f"Receipt saved to {written.name}.")

    def _next_invoice(self) -> str:
        try:
            return pos_service.next_invoice_number()
        except Exception as exc:  # noqa: BLE001 - the label is cosmetic
            log_unexpected(logger, "next invoice number", exc)
            return ""

    # ------------------------------------------------------- shell callbacks

    def refresh(self) -> None:
        self.settings = settings_service.get_settings()
        self._load_categories()
        self._reload_grid()
        self._refresh_cart()
        invoice = self._next_invoice()
        self.invoice_label.setText(f"Sale #{invoice}" if invoice else "")
        self.window_ref.set_header(
            "Point of Sale",
            f"{self.settings.business_name} - {self.settings.vat_label}"
            + (f" - next invoice {invoice}" if invoice else ""),
        )

    def _load_categories(self) -> None:
        current = self.category_filter.currentText()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("All Categories")
        try:
            for category in product_service.list_categories():
                self.category_filter.addItem(category.name, category.id)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
        index = self.category_filter.findText(current)
        self.category_filter.setCurrentIndex(max(index, 0))
        self.category_filter.blockSignals(False)
