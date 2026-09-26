"""Sales page: historical invoices, period totals and the detail view.

Sales are never edited or deleted in Version 1 (blueprint 10.1), so this page
only reads. Amounts shown are the ones stored on the invoice at the time.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.constants import Period
from core.dates import format_datetime, resolve_period
from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from core.money import format_money
from reports.pdf_receipt import export_receipt_pdf
from services import reporting_service, settings_service
from ui.dialogs.sale_dialog import SaleDetailDialog
from ui.widgets.banner import Banner
from ui.widgets.card import KpiCard
from ui.widgets.fields import Combo, SearchInput
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.sales")


class SalesPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self._rows: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        layout.addLayout(self._summary_cards())
        layout.addLayout(self._toolbar())

        self.banner = Banner(self)
        layout.addWidget(self.banner)

        self.period_totals = QLabel("")
        self.period_totals.setObjectName("MetricLabel")
        layout.addWidget(self.period_totals)

        self.table = DataTable([
            Column("Invoice", "left", 130),
            Column("Date / Time", "left", 150),
            Column("Items", "right", 70),
            Column("Units", "right", 70),
            Column("Subtotal", "right", 110),
            Column("VAT", "right", 100),
            Column("Discount", "right", 100),
            Column("Total", "right", 120),
        ])
        self.table.set_empty_state(
            "No sales in this period. Open the POS and complete a sale to see it here.",
            title="Nothing sold yet",
            action_label="Go to POS",
            callback=lambda: self.window_ref.show_page("pos"),
        )
        self.table.row_double_clicked.connect(lambda _row: self.view_selected())
        layout.addWidget(self.table, stretch=1)

        layout.addLayout(self._actions())

    # ---------------------------------------------------------------- layout

    def _summary_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        self.kpis = {
            "today": KpiCard("Today's Sales", accent="#2563EB"),
            "transactions": KpiCard("Today's Transactions", accent="#2563EB"),
            "period": KpiCard("Period Revenue", accent="#16A34A"),
            "period_vat": KpiCard("Period VAT", accent="#F59E0B"),
        }
        for card in self.kpis.values():
            row.addWidget(card)
        return row

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.search = SearchInput("Search invoice number...")
        self.search.setFixedWidth(240)
        self.search.returnPressed.connect(self._search_invoice)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search)

        self.period_filter = Combo(list(Period.ALL))
        self.period_filter.setCurrentText(Period.THIS_MONTH)
        self.period_filter.currentIndexChanged.connect(self._period_changed)
        row.addWidget(self.period_filter)

        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        for editor in (self.start_date, self.end_date):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd MMM yyyy")
            editor.dateChanged.connect(self.refresh)
            editor.hide()
            row.addWidget(editor)

        row.addStretch(1)
        return row

    def _actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.view_button = QPushButton("View Details")
        self.view_button.clicked.connect(self.view_selected)
        self.receipt_button = QPushButton("Save Receipt (PDF)")
        self.receipt_button.setProperty("variant", "quiet")
        self.receipt_button.clicked.connect(self.save_receipt)
        for button in (self.view_button, self.receipt_button):
            button.setEnabled(False)
            row.addWidget(button)
        row.addStretch(1)
        hint = QLabel("Double-click an invoice to open it. Sales are never deleted or edited.")
        hint.setObjectName("FieldHint")
        row.addWidget(hint)
        self.table.itemSelectionChanged.connect(self._sync_actions)
        return row

    def _sync_actions(self) -> None:
        enabled = self.selected_sale() is not None
        self.view_button.setEnabled(enabled)
        self.receipt_button.setEnabled(enabled)

    def _period_changed(self) -> None:
        custom = self.period_filter.currentText() == Period.CUSTOM
        self.start_date.setVisible(custom)
        self.end_date.setVisible(custom)
        self.refresh()

    # ------------------------------------------------------------------ data

    def _range(self):
        custom = self.period_filter.currentText() == Period.CUSTOM
        return resolve_period(
            self.period_filter.currentText(),
            self.start_date.date().toPython() if custom else None,
            self.end_date.date().toPython() if custom else None,
        )

    def selected_sale(self):
        row = self.table.selected_row()
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def refresh(self) -> None:
        today = reporting_service.sales_summary(Period.TODAY)
        self.kpis["today"].set_value(format_money(today["total"]))
        self.kpis["today"].set_hint(f"{today['invoices']} invoice(s), {today['items']} item(s)")
        self.kpis["transactions"].set_value(f"{today['invoices']:,}")

        start, end = self._range()
        try:
            rows, totals, label = reporting_service.list_sales(
                search=self.search.text().strip() or None,
                start=start,
                end=end,
                limit=500,
            )
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            self._rows, totals, label = [], {}, self.period_filter.currentText()
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "sales list", exc)
            self.banner.show_message(
                f"Sales could not be loaded. Reference {reference}.", "danger"
            )
            self._rows, totals, label = [], {}, self.period_filter.currentText()
        else:
            self._rows = rows
            self.banner.clear()

        self.kpis["period"].set_value(format_money(totals.get("total", 0)))
        self.kpis["period"].set_hint(label)
        self.kpis["period_vat"].set_value(format_money(totals.get("vat", 0)))
        self.kpis["period_vat"].set_hint(
            f"discounts {format_money(totals.get('discount', 0))}"
        )

        self.table.set_rows([
            [
                sale.invoice_number,
                format_datetime(sale.sale_date),
                f"{sale.item_count:,}",
                f"{sale.total_quantity:,}",
                format_money(sale.subtotal),
                format_money(sale.vat_amount),
                format_money(sale.discount),
                format_money(sale.total),
            ]
            for sale in self._rows
        ])
        self.period_totals.setText(
            f"{totals.get('invoices', 0):,} invoices - {totals.get('items', 0):,} items sold - "
            f"total {format_money(totals.get('total', 0))} for {label}."
        )
        self._sync_actions()

    # --------------------------------------------------------------- actions

    def view_selected(self) -> None:
        sale = self.selected_sale()
        if sale is None:
            return
        SaleDetailDialog(self, sale, on_saved=self.window_ref.notify).exec()

    def save_receipt(self) -> None:
        sale = self.selected_sale()
        if sale is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save receipt", f"{sale.invoice_number}.pdf", "PDF files (*.pdf)"
        )
        if not path:
            return
        try:
            written = export_receipt_pdf(sale, path, settings=settings_service.get_settings())
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "receipt export", exc)
            self.banner.show_message(
                f"The receipt could not be written. Reference {reference}.", "danger"
            )
            return
        self.window_ref.notify(f"Receipt saved to {written.name}.")

    def _search_invoice(self) -> None:
        """Jump straight to an invoice when the exact number is typed."""
        term = self.search.text().strip()
        if len(term) < 3:
            return
        sale = None
        try:
            sale = reporting_service.find_sale_by_invoice(term)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
        if sale is None:
            return
        SaleDetailDialog(self, sale, on_saved=self.window_ref.notify).exec()

    # ------------------------------------------------------- shell callbacks

    def focus_sale(self, sale_id: int) -> None:
        sale = reporting_service.get_sale(sale_id)
        if sale is None:
            self.banner.show_message("That invoice could not be found.", "warning")
            return
        SaleDetailDialog(self, sale, on_saved=self.window_ref.notify).exec()
