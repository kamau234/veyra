"""Stock movement dialog (blueprint 8.3): type, reason, quantity, notes."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QWidget

from core.constants import (
    DIRECTION_BY_TYPE,
    MovementType,
    NOTES_REQUIRED_REASONS,
    REASONS_BY_TYPE,
)
from services import inventory_service, product_service
from ui.dialogs.base import FormDialog
from ui.widgets.fields import Combo, Field, IntSpin, TextArea


class MovementDialog(FormDialog):
    """Records one ledger entry; the service enforces the stock rules."""

    def __init__(self, parent: QWidget, *, product_id: int | None = None):
        super().__init__(
            parent,
            "Record Stock Movement",
            "Every movement is written to the ledger with the balance after it.",
            confirm_label="Record Movement",
            confirm_variant="success",
        )
        self.result_message = ""

        self.products = product_service.list_products(include_inactive=False)
        self.product_combo = Combo()
        for product in self.products:
            self.product_combo.addItem(
                f"{product.code}  -  {product.name}  (stock {product.stock_quantity})",
                product.id,
            )

        self.type_combo = Combo(list(MovementType.ALL))
        self.reason_combo = Combo()
        self.direction_combo = Combo(["in (increase)", "out (decrease)"])
        self.quantity = IntSpin()
        self.quantity.setMinimum(1)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("GRN number, note reference...")
        self.notes = TextArea("Required for corrections.")

        self.add_field(Field("Product", self.product_combo, required=True))
        self.add_row(
            Field("Movement Type", self.type_combo, required=True),
            Field("Direction", self.direction_combo,
                  hint="Only used for adjustments."),
        )
        self.add_row(
            Field("Reason", self.reason_combo, required=True),
            Field("Quantity", self.quantity, required=True),
        )
        self.add_field(Field("Reference", self.reference))
        self.add_field(Field("Notes", self.notes))

        self.preview_label = QLineEdit()
        self.preview_label.setReadOnly(True)
        self.add_field(Field("Resulting Stock", self.preview_label))

        self.type_combo.currentTextChanged.connect(self._sync_reasons)
        self.reason_combo.currentTextChanged.connect(self._sync_preview)
        self.quantity.valueChanged.connect(self._sync_preview)
        self.product_combo.currentIndexChanged.connect(self._sync_preview)
        self.direction_combo.currentIndexChanged.connect(self._sync_preview)
        self.type_combo.currentTextChanged.connect(self._sync_direction)

        if product_id:
            index = self.product_combo.findData(product_id)
            if index >= 0:
                self.product_combo.setCurrentIndex(index)
        self._sync_reasons(self.type_combo.currentText())

    # ------------------------------------------------------------------ sync

    def _sync_reasons(self, movement_type: str) -> None:
        reasons = REASONS_BY_TYPE.get(movement_type, ())
        current = self.reason_combo.currentText()
        self.reason_combo.clear()
        self.reason_combo.addItems(list(reasons))
        index = self.reason_combo.findText(current)
        if index >= 0:
            self.reason_combo.setCurrentIndex(index)
        self._sync_direction(movement_type)

    def _sync_direction(self, movement_type: str) -> None:
        fixed = DIRECTION_BY_TYPE.get(movement_type)
        self.direction_combo.setEnabled(fixed is None)
        if fixed is not None:
            self.direction_combo.setCurrentIndex(0 if fixed == "in" else 1)
        self._sync_preview()

    def _selected_product(self):
        product_id = self.product_combo.currentData()
        return next((p for p in self.products if p.id == product_id), None)

    def _direction(self) -> str | None:
        movement_type = self.type_combo.currentText()
        fixed = DIRECTION_BY_TYPE.get(movement_type)
        if fixed:
            return fixed
        return "in" if self.direction_combo.currentIndex() == 0 else "out"

    def _sync_preview(self) -> None:
        product = self._selected_product()
        if product is None:
            self.preview_label.setText("")
            return
        try:
            resulting = inventory_service.preview_resulting_stock(
                product.stock_quantity,
                self.type_combo.currentText(),
                self.quantity.value(),
                self._direction(),
            )
        except Exception:  # noqa: BLE001 - preview only; submit validates again
            self.preview_label.setText("")
            return
        self.preview_label.setText(
            f"{product.stock_quantity:,}  ->  {resulting:,}"
            + ("   (stock cannot go below zero)" if resulting < 0 else "")
        )

    # ---------------------------------------------------------------- submit

    def on_submit(self) -> None:
        product = self._selected_product()
        if product is None:
            from core.exceptions import ValidationError

            raise ValidationError("Select a product.", field="Product")

        result = inventory_service.record_movement(
            product_id=product.id,
            movement_type=self.type_combo.currentText(),
            reason=self.reason_combo.currentText(),
            quantity=self.quantity.value(),
            direction=self._direction(),
            reference=self.reference.text().strip() or None,
            notes=self.notes.toPlainText().strip() or None,
        )
        self.result_message = result.message
        if self.reason_combo.currentText() in NOTES_REQUIRED_REASONS:
            self.result_message += " The note was saved with the movement."
