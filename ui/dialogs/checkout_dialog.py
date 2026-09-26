"""Complete Sale confirmation (blueprint 9.8): summary, optional note, confirm."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from core.money import format_money, format_rate
from ui.dialogs.base import FormDialog
from ui.widgets.card import MetricRow
from ui.widgets.fields import TextArea


class CheckoutDialog(FormDialog):
    def __init__(self, parent, *, priced, invoice_number: str, vat_label: str = "VAT"):
        super().__init__(
            parent,
            f"Complete Sale {invoice_number}",
            "Confirming writes the invoice, snapshots every price and deducts stock in a "
            "single transaction. Nothing is saved if any step fails.",
            confirm_label="Complete Sale",
            width=480,
        )
        self.priced = priced
        self.note = ""

        count = QLabel(
            f"{priced.item_count} product{'s' if priced.item_count != 1 else ''} - "
            f"{priced.total_quantity} unit{'s' if priced.total_quantity != 1 else ''}"
        )
        count.setObjectName("CardSubtitle")
        self.add_widget(count)

        self.add_widget(MetricRow("Subtotal", format_money(priced.subtotal)))
        if priced.vat_enabled and priced.vat_rate > 0:
            self.add_widget(
                MetricRow(f"{vat_label} ({format_rate(priced.vat_rate)}%)", format_money(priced.vat))
            )
        if priced.discount > 0:
            self.add_widget(MetricRow("Discount", f"-{format_money(priced.discount)}"))
        self.add_widget(MetricRow("Total", format_money(priced.total), strong=True))

        self.note_input = TextArea("Optional note printed on the receipt...", rows=2)
        self.add_widget(self.note_input)

    def on_submit(self) -> None:
        self.note = self.note_input.toPlainText().strip()

    @staticmethod
    def ask(parent, **kwargs):
        dialog = CheckoutDialog(parent, **kwargs)
        if dialog.exec() and dialog.submitted:
            return dialog
        return None
