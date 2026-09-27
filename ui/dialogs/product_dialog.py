"""Add / Edit product dialog with image upload (blueprint 6.3, 6.4)."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.constants import UNITS
from services import image_service, product_service
from services.product_service import ProductInput
from ui.dialogs.base import FormDialog
from ui.widgets.fields import Combo, Field, IntSpin, MoneySpin
from ui.widgets.images import product_pixmap


class ProductDialog(FormDialog):
    """Collects master data; stock is deliberately not editable here."""

    IMAGE_FILTERS = "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*)"

    def __init__(
        self,
        parent: QWidget,
        *,
        product=None,
        categories: list[str] | None = None,
        subcategories: list[str] | None = None,
        brands: list[str] | None = None,
    ):
        self.product = product
        editing = product is not None
        super().__init__(
            parent,
            "Edit Product" if editing else "Add Product",
            "Master data only. Stock changes are recorded in Inventory."
            if editing
            else "Opening stock is written to the movement ledger automatically.",
            confirm_label="Save Product",
        )

        self._pending_image: str | None = None
        self._image_removed = False
        self.result = None
        self.result_message = ""

        self.code = QLineEdit()
        self.code.setPlaceholderText("COF001")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Classic 100g")

        self.category = Combo()
        self.category.setEditable(True)
        self.category.addItems(categories or [])
        self.category.lineEdit().setPlaceholderText("Beverages")

        self.subcategory = Combo()
        self.subcategory.setEditable(True)
        self.subcategory.addItems(subcategories or [])
        self.subcategory.lineEdit().setPlaceholderText("Coffee")

        self.brand = Combo()
        self.brand.setEditable(True)
        self.brand.addItems(brands or [])
        self.brand.lineEdit().setPlaceholderText("Nescafé")

        self.unit = Combo()
        self.unit.addItems(list(UNITS))

        self.cost = MoneySpin()
        self.selling = MoneySpin()
        self.opening_stock = IntSpin()
        self.reorder = IntSpin()
        self.vat = QCheckBox("VAT applies to this product")
        self.vat.setChecked(True)

        self.add_row(
            Field("Product Code", self.code, required=True),
            Field("Product Name", self.name, required=True,
                  hint="The product or line, without the brand if it has its own field."),
        )
        self.add_row(
            Field("Category", self.category, required=True,
                  hint="Broad group, e.g. Beverages. Pick one or type a new name."),
            Field("Subcategory", self.subcategory,
                  hint="Optional. The group inside the category, e.g. Coffee."),
        )
        self.add_row(
            Field("Brand", self.brand,
                  hint="Optional. The manufacturer or brand, e.g. Nescafé."),
            Field("Unit", self.unit),
        )
        self.add_row(
            Field("Cost Price", self.cost, required=True),
            Field("Selling Price", self.selling, required=True),
        )

        if editing:
            self.stock_display = QLabel(f"{product.stock_quantity:,}")
            self.stock_display.setObjectName("MetricValue")
            self.add_row(
                Field("Current Stock", self.stock_display,
                      hint="Record a movement in Inventory to change it."),
                Field("Reorder Level", self.reorder, required=True),
            )
        else:
            self.add_row(
                Field("Opening Stock", self.opening_stock, required=True),
                Field("Reorder Level", self.reorder, required=True),
            )

        self.add_widget(self.vat)
        self.add_widget(self._build_image_row())

        if editing:
            self._load(product)

    # ------------------------------------------------------------------ image

    def _build_image_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(12)

        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(72, 72)
        layout.addWidget(self.thumbnail)

        texts = QVBoxLayout()
        texts.setSpacing(6)
        caption = QLabel("Product image")
        caption.setObjectName("FieldLabel")
        texts.addWidget(caption)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        choose = QPushButton("Choose Image...")
        choose.clicked.connect(self._choose_image)
        remove = QPushButton("Remove")
        remove.setProperty("variant", "quiet")
        remove.clicked.connect(self._remove_image)
        buttons.addWidget(choose)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        texts.addLayout(buttons)
        hint = QLabel("Optional. Stored locally, resized to 300 px.")
        hint.setObjectName("FieldHint")
        texts.addWidget(hint)
        layout.addLayout(texts, stretch=1)
        return row

    def _refresh_thumbnail(self) -> None:
        if self._image_removed:
            stored = None
        elif self._pending_image:
            stored = self._pending_image
        elif self.product is not None:
            stored = self.product.image_path
        else:
            stored = None
        self.thumbnail.setPixmap(product_pixmap(stored, self.name.text() or "?", 72))

    def _choose_image(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, "Choose a product image", "",
                                                self.IMAGE_FILTERS)
        if not source:
            return
        self._pending_image = source
        self._image_removed = False
        self._refresh_thumbnail()

    def _remove_image(self) -> None:
        self._pending_image = None
        self._image_removed = True
        self._refresh_thumbnail()

    # ------------------------------------------------------------------ state

    def _load(self, product) -> None:
        self.code.setText(product.code)
        self.name.setText(product.name)
        self.category.setCurrentText(product.category_name or "")
        self.subcategory.setCurrentText(product.subcategory_name)
        self.brand.setCurrentText(product.brand_name)
        index = self.unit.findText(product.unit or "Piece")
        self.unit.setCurrentIndex(max(index, 0))
        self.cost.set_decimal(product.cost_price)
        self.selling.set_decimal(product.selling_price)
        self.reorder.setValue(product.reorder_level or 0)
        self.vat.setChecked(bool(product.vat_applicable))
        self._refresh_thumbnail()

    def _input(self) -> ProductInput:
        return ProductInput(
            code=self.code.text(),
            name=self.name.text(),
            category=self.category.currentText(),
            subcategory=self.subcategory.currentText(),
            brand=self.brand.currentText(),
            unit=self.unit.currentText(),
            cost_price=self.cost.decimal_value(),
            selling_price=self.selling.decimal_value(),
            stock_quantity=self.opening_stock.value() if self.product is None else 0,
            reorder_level=self.reorder.value(),
            vat_applicable=self.vat.isChecked(),
            image_path=self._pending_image,
        )

    # ----------------------------------------------------------------- submit

    def on_submit(self) -> None:
        data = self._input()
        if self._pending_image:
            stored = image_service.import_image(self._pending_image, kind="products")
            data = replace(data, image_path=stored)

        if self.product is None:
            self.result = product_service.create_product(data)
            self.result_message = f"{self.result.name} added to the catalogue."
        else:
            self.result = product_service.update_product(self.product.id, data)
            if self._image_removed:
                product_service.set_image(self.product.id, None)
            self.result_message = f"{self.result.name} updated."
