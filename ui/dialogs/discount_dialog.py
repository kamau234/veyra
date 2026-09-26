"""Sale-level discount entry (blueprint 9.6): a fixed KSh amount."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from core.exceptions import ValidationError
from core.money import format_money, to_money
from ui.dialogs.base import FormDialog
from ui.widgets.fields import Field, MoneySpin


class DiscountDialog(FormDialog):
    def __init__(self, parent, *, subtotal, current=None, item_count: int = 0):
        self.subtotal = to_money(subtotal)
        super().__init__(
            parent,
            "Apply Discount",
            f"Subtotal KSh {format_money(self.subtotal)}. Discounts are entered in KSh and "
            "shared across the cart lines pro-rata.",
            confirm_label="Apply Discount",
            width=460,
        )
        self.discount = to_money(current) if current is not None else to_money(0)

        self.spin = MoneySpin()
        self.spin.setMaximum(float(self.subtotal))
        self.spin.set_decimal(self.discount)
        self.add_field(Field("Discount (KSh)", self.spin, required=False))

        row = QHBoxLayout()
        row.setSpacing(8)
        clear = QPushButton("Remove Discount")
        clear.setProperty("variant", "quiet")
        clear.clicked.connect(lambda: self.spin.setValue(0.0))
        half = QPushButton("50% of subtotal")
        half.setProperty("variant", "quiet")
        half.clicked.connect(lambda: self.spin.set_decimal(self.subtotal / 2))
        row.addWidget(clear)
        row.addWidget(half)
        row.addStretch(1)
        host = QWidget()
        host.setLayout(row)
        self.add_widget(host)

        if item_count:
            hint = QLabel(
                f"{item_count} line{'s' if item_count != 1 else ''} in the cart. VAT is charged "
                "on each line after its share of the discount."
            )
            hint.setObjectName("FieldHint")
            hint.setWordWrap(True)
            self.add_widget(hint)

    def on_submit(self) -> None:
        value = self.spin.decimal_value()
        if value < 0:
            raise ValidationError("Discount cannot be negative.", field="Discount (KSh)")
        if value > self.subtotal:
            raise ValidationError(
                f"Discount cannot be greater than the subtotal of KSh {format_money(self.subtotal)}.",
                field="Discount (KSh)",
            )
        self.discount = value

    @staticmethod
    def ask(parent, **kwargs):
        """Return the chosen discount, or ``None`` when cancelled."""
        dialog = DiscountDialog(parent, **kwargs)
        if dialog.exec() and dialog.submitted:
            return dialog.discount
        return None
