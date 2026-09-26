"""Inventory page: stock summary, movement filters and the ledger."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.constants import MovementType, Period, Reason
from core.dates import format_datetime, resolve_period
from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from core.money import format_money
from services import inventory_service
from ui.dialogs.movement_dialog import MovementDialog
from ui.widgets.badge import StatusBadge
from ui.widgets.banner import Banner
from ui.widgets.card import KpiCard
from ui.widgets.fields import Combo, SearchInput
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.inventory")


class InventoryPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ref = window

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
            Column("When", "left", 140),
            Column("Code", "left", 100),
            Column("Product", stretch=True),
            Column("Movement", "left", 110),
            Column("Direction", "center", 90),
            Column("Qty", "right", 70),
            Column("Balance", "right", 80),
            Column("Reason", "left", 120),
            Column("Reference", "left", 120),
            Column("Notes", stretch=True),
        ])
        self.table.set_empty_state(
            "No stock movements match these filters. Record a restock or a sale to "
            "start the ledger.",
            title="The ledger is empty",
            action_label="Record Movement",
            callback=self.open_movement_dialog,
        )
        layout.addWidget(self.table, stretch=1)

    # ---------------------------------------------------------------- layout

    def _summary_cards(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)
        self.kpis = {
            "units": KpiCard("Units on Hand", accent="#2563EB"),
            "value": KpiCard("Stock Value", accent="#2563EB", hint="at cost price"),
            "in_stock": KpiCard("In Stock", accent="#16A34A"),
            "low_stock": KpiCard("Low Stock", accent="#F59E0B"),
            "out_of_stock": KpiCard("Out of Stock", accent="#DC2626"),
        }
        for index, card in enumerate(self.kpis.values()):
            grid.addWidget(card, 0, index)
        return grid

    def _toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.search = SearchInput("Search product, code or reference...")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search)

        self.type_filter = Combo(["All"] + list(MovementType.ALL))
        self.type_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.type_filter)

        self.reason_filter = Combo(["All"] + list(Reason.ALL))
        self.reason_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.reason_filter)

        self.direction_filter = Combo(["All", "in", "out"])
        self.direction_filter.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.direction_filter)

        self.period_filter = Combo(list(Period.ALL))
        self.period_filter.setCurrentText(Period.LAST_30_DAYS)
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
        record = QPushButton("Record Movement")
        record.setProperty("variant", "primary")
        record.clicked.connect(self.open_movement_dialog)
        row.addWidget(record)
        return row

    def _period_changed(self) -> None:
        custom = self.period_filter.currentText() == Period.CUSTOM
        self.start_date.setVisible(custom)
        self.end_date.setVisible(custom)
        self.refresh()

    # ------------------------------------------------------------------ data

    def _range(self):
        start, end = resolve_period(
            self.period_filter.currentText(),
            self.start_date.date().toPython() if self.period_filter.currentText()
            == Period.CUSTOM else None,
            self.end_date.date().toPython() if self.period_filter.currentText()
            == Period.CUSTOM else None,
        )
        return start, end

    def refresh(self) -> None:
        data = inventory_service.summary()
        from ui.theme import current

        theme = current()
        self.kpis["units"].set_value(f"{data.total_units:,}")
        self.kpis["units"].set_hint(f"{data.product_count:,} active products")
        self.kpis["value"].set_value(format_money(data.stock_value))
        self.kpis["in_stock"].set_value(f"{data.in_stock:,}")
        self.kpis["low_stock"].set_value(f"{data.low_stock:,}")
        self.kpis["low_stock"].set_accent(theme.warning if data.low_stock else theme.success)
        self.kpis["out_of_stock"].set_value(f"{data.out_of_stock:,}")
        self.kpis["out_of_stock"].set_accent(
            theme.danger if data.out_of_stock else theme.success
        )

        start, end = self._range()
        try:
            movements = inventory_service.list_movements(
                search=self.search.text().strip() or None,
                movement_type=self.type_filter.currentText(),
                reason=self.reason_filter.currentText(),
                direction=self.direction_filter.currentText(),
                start=start,
                end=end,
            )
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            movements = []
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "inventory ledger", exc)
            self.banner.show_message(f"The ledger could not be loaded. Reference {reference}.",
                                     "danger")
            movements = []

        self.table.set_rows([
            [
                format_datetime(movement.created_at),
                movement.product.code if movement.product else "",
                movement.product.name if movement.product else "(removed product)",
                movement.movement_type,
                StatusBadge(movement.direction.upper(),
                            "success" if movement.direction == "in" else "warning"),
                f"{movement.quantity:,}",
                f"{movement.balance_after:,}",
                movement.reason,
                movement.reference or "",
                movement.notes or "",
            ]
            for movement in movements
        ])

        units_in = sum(m.quantity for m in movements if m.direction == "in")
        units_out = sum(m.quantity for m in movements if m.direction == "out")
        self.period_totals.setText(
            f"{len(movements):,} movements in this period: "
            f"{units_in:,} units in, {units_out:,} units out."
        )

    # --------------------------------------------------------------- actions

    def open_movement_dialog(self, product_id: int | None = None) -> None:
        dialog = MovementDialog(self, product_id=product_id)
        if dialog.exec() and dialog.submitted:
            self.refresh()
            self.window_ref.notify(dialog.result_message)
