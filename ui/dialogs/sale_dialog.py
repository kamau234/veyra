"""Sale detail dialog (blueprint 10.3): the immutable record of one invoice."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from core.dates import format_datetime
from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from core.money import format_money, format_rate
from reports.pdf_receipt import export_receipt_pdf
from services.settings_service import get_settings
from ui.widgets.card import MetricRow
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.sales")


class SaleDetailDialog(QDialog):
    """Read-only invoice view with a receipt export action."""

    def __init__(self, parent, sale, *, on_saved=None):
        super().__init__(parent)
        self.sale = sale
        self._on_saved = on_saved
        self.setWindowTitle(f"Invoice {sale.invoice_number}")
        self.setModal(True)
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        heading = QLabel(f"Invoice {sale.invoice_number}")
        heading.setObjectName("CardTitle")
        when = QLabel(
            f"{format_datetime(sale.sale_date)} - {sale.item_count} product"
            f"{'s' if sale.item_count != 1 else ''}, {sale.total_quantity} unit"
            f"{'s' if sale.total_quantity != 1 else ''}"
        )
        when.setObjectName("CardSubtitle")
        layout.addWidget(heading)
        layout.addWidget(when)

        self.table = DataTable([
            Column("Code", "left", 100),
            Column("Product", stretch=True),
            Column("Unit", "left", 70),
            Column("Qty", "right", 60),
            Column("Unit Price", "right", 100),
            Column("Discount", "right", 90),
            Column("VAT", "right", 90),
            Column("Line Total", "right", 110),
        ])
        self.table.set_rows([
            [
                item.product_code_snapshot,
                item.product_name_snapshot,
                item.unit_snapshot,
                f"{item.quantity:,}",
                format_money(item.unit_price),
                format_money(item.discount_allocated),
                format_money(item.vat_amount),
                format_money(item.line_total),
            ]
            for item in sale.items
        ])
        layout.addWidget(self.table, stretch=1)

        vat_label = f"VAT ({format_rate(sale.vat_rate_snapshot)}%)"
        layout.addWidget(MetricRow("Subtotal", format_money(sale.subtotal)))
        layout.addWidget(MetricRow(vat_label, format_money(sale.vat_amount)))
        layout.addWidget(MetricRow("Discount", f"-{format_money(sale.discount)}"))
        layout.addWidget(MetricRow("Total", format_money(sale.total), strong=True))

        note = QLabel(sale.note or "No note recorded.")
        note.setObjectName("FieldHint")
        note.setWordWrap(True)
        layout.addWidget(note)

        footer = QHBoxLayout()
        footer.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        receipt = QPushButton("Save Receipt (PDF)")
        receipt.setProperty("variant", "primary")
        receipt.clicked.connect(self._save_receipt)
        footer.addWidget(close)
        footer.addWidget(receipt)
        layout.addLayout(footer)

    def _save_receipt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save receipt",
            f"{self.sale.invoice_number}.pdf",
            "PDF files (*.pdf)",
        )
        if not path:
            return
        try:
            written = export_receipt_pdf(self.sale, path, settings=get_settings())
        except VeyraError as error:
            self._fail(error.message)
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "receipt export", exc)
            self._fail(f"The receipt could not be written. Reference {reference}.")
            return
        if self._on_saved:
            self._on_saved(f"Receipt saved to {written.name}.")
        else:
            self._info(f"Receipt saved to {written}.")

    def _fail(self, message: str) -> None:
        from ui.dialogs.base import MessageDialog

        MessageDialog.show_message(self, "Receipt not saved", message, kind="danger")

    def _info(self, message: str) -> None:
        from ui.dialogs.base import MessageDialog

        MessageDialog.show_message(self, "Receipt saved", message, kind="success")
