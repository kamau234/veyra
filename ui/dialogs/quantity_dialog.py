"""Quantity picker used by the POS grid (blueprint 9.4)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from core.exceptions import ValidationError
from ui.dialogs.base import FormDialog
from ui.widgets.fields import IntSpin


class QuantityDialog(FormDialog):
    """Ask how many of one product to add, capped by available stock."""

    def __init__(
        self,
        parent,
        *,
        product_name: str,
        unit: str,
        available_stock: int,
        current: int = 0,
        price: str = "",
    ):
        subtitle = f"Available stock: {available_stock:,} {unit}"
        if current:
            subtitle += f" - {current} already in the cart"
        super().__init__(parent, product_name, subtitle, confirm_label="Add to Cart", width=420)

        self.quantity = current or 1
        self.spin = IntSpin(maximum=max(available_stock, 1))
        self.spin.setMinimum(1)
        self.spin.setValue(max(self.quantity, 1))
        self.spin.setFixedWidth(110)

        minus = QPushButton("-")
        minus.setFixedSize(34, 34)
        minus.clicked.connect(self.spin.stepDown)
        plus = QPushButton("+")
        plus.setFixedSize(34, 34)
        plus.clicked.connect(self.spin.stepUp)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(minus)
        row.addWidget(self.spin)
        row.addWidget(plus)
        row.addStretch(1)
        host = QWidget()
        host.setLayout(row)
        self.add_widget(host)

        if price:
            hint = QLabel(f"Unit price {price}. The cart recalculates as the quantity changes.")
            hint.setObjectName("FieldHint")
            hint.setWordWrap(True)
            self.add_widget(hint)

    def on_submit(self) -> None:
        value = self.spin.value()
        if value <= 0:
            raise ValidationError("Quantity must be greater than zero.", field="Quantity")
        self.quantity = value

    @staticmethod
    def ask(parent, **kwargs) -> int | None:
        """Return the chosen quantity, or ``None`` when cancelled."""
        dialog = QuantityDialog(parent, **kwargs)
        if dialog.exec() and dialog.submitted:
            return dialog.quantity
        return None
