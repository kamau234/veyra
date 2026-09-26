"""Dashboard: KPIs, sales and stock charts, alerts, top sellers, activity."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.constants import StockStatus
from core.dates import format_time
from core.money import format_money
from services import reporting_service
from ui.theme import current
from ui.widgets.badge import StatusBadge
from ui.widgets.card import Card, KpiCard
from ui.widgets.charts import DonutChart, LineChart, Slice, stock_status_colors
from ui.widgets.table import Column, DataTable


class DashboardPage(QWidget):
    """Blueprint section 5: the operational home screen."""

    def __init__(self, window):
        super().__init__()
        self.window_ref = window

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        self.kpis: dict[str, KpiCard] = {}
        grid = QGridLayout()
        grid.setSpacing(12)
        for index, (key, label, accent) in enumerate((
            ("today_sales", "Today's Sales", "#2563EB"),
            ("transactions", "Transactions", "#2563EB"),
            ("products", "Products", "#16A34A"),
            ("stock_value", "Stock Value", "#16A34A"),
            ("low_stock", "Low Stock", "#F59E0B"),
            ("out_of_stock", "Out of Stock", "#DC2626"),
        )):
            card = KpiCard(label, accent=accent)
            self.kpis[key] = card
            grid.addWidget(card, index // 3, index % 3)
        layout.addLayout(grid)

        layout.addLayout(self._quick_actions())
        layout.addLayout(self._charts())
        layout.addLayout(self._bottom_row())
        layout.addStretch(1)

        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ---------------------------------------------------------------- layout

    def _quick_actions(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        actions = (
            ("New Sale", "primary", lambda: self.window_ref.show_page("pos")),
            ("Add Product", "quiet", self._add_product),
            ("Record Stock Movement", "quiet", self._record_movement),
            ("Import Products", "quiet", self._import_products),
            ("View Reports", "quiet", lambda: self.window_ref.show_page("reports")),
        )
        for label, variant, handler in actions:
            button = QPushButton(label)
            button.setProperty("variant", variant)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(handler)
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _charts(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        self.sales_card = Card("Sales Overview", "Completed sales, last 7 days")
        self.sales_chart = LineChart()
        self.sales_chart.setMinimumHeight(220)
        self.sales_card.add_widget(self.sales_chart, stretch=1)
        row.addWidget(self.sales_card, stretch=3)

        self.stock_card = Card("Stock Status", "Live catalogue health")
        self.stock_chart = DonutChart()
        self.stock_chart.setMinimumHeight(220)
        self.stock_card.add_widget(self.stock_chart, stretch=1)
        row.addWidget(self.stock_card, stretch=2)
        return row

    def _bottom_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)

        self.low_stock_card = Card("Needs Attention", "Out of stock and low stock first")
        self.low_stock_table = DataTable([
            Column("Product", stretch=True),
            Column("Stock", "right", 70),
            Column("Reorder", "right", 70),
            Column("Status", "center", 110),
        ])
        self.low_stock_table.setMaximumHeight(260)
        self.low_stock_table.set_empty_state(
            "Every product is comfortably in stock.", title="Nothing needs restocking"
        )
        self.low_stock_card.add_widget(self.low_stock_table)
        row.addWidget(self.low_stock_card, stretch=5)

        middle = QVBoxLayout()
        middle.setSpacing(14)
        self.top_card = Card("Top Sellers", "Last 7 days by quantity")
        self.top_table = DataTable([
            Column("Product", stretch=True),
            Column("Qty", "right", 60),
            Column("Revenue", "right", 110),
        ])
        self.top_table.setMaximumHeight(200)
        self.top_table.set_empty_state("Complete a sale in POS to see best sellers here.")
        self.top_card.add_widget(self.top_table)
        middle.addWidget(self.top_card)
        row.addLayout(middle, stretch=5)

        self.activity_card = Card("Recent Activity", "Sales and stock movements")
        self.activity_table = DataTable([
            Column("When", "left", 90),
            Column("Event", stretch=True),
            Column("Amount", "right", 100),
        ])
        self.activity_table.setMaximumHeight(260)
        self.activity_table.set_empty_state("Activity appears here as soon as you sell or move stock.")
        self.activity_card.add_widget(self.activity_table)
        row.addWidget(self.activity_card, stretch=6)
        return row

    # ------------------------------------------------------------- navigation

    def _add_product(self) -> None:
        self.window_ref.show_page("products")
        page = self.window_ref.page("products")
        if page is not None:
            page.open_add_dialog()

    def _record_movement(self) -> None:
        self.window_ref.show_page("inventory")
        page = self.window_ref.page("inventory")
        if page is not None:
            page.open_movement_dialog()

    def _import_products(self) -> None:
        self.window_ref.show_page("products")
        page = self.window_ref.page("products")
        if page is not None:
            page.start_import()

    # ---------------------------------------------------------------- refresh

    def refresh(self) -> None:
        theme = current()
        data = reporting_service.dashboard_data(chart_days=7, limit=5)

        self.kpis["today_sales"].set_value(format_money(data.today_sales))
        self.kpis["today_sales"].set_hint(f"Month to date: {format_money(data.month_sales)}")
        self.kpis["transactions"].set_value(f"{data.transactions:,}")
        self.kpis["transactions"].set_hint("completed today")
        self.kpis["products"].set_value(f"{data.products:,}")
        self.kpis["products"].set_hint(f"{data.total_units:,} units on hand")
        self.kpis["stock_value"].set_value(format_money(data.stock_value))
        self.kpis["stock_value"].set_hint("at cost price")
        self.kpis["low_stock"].set_value(f"{data.low_stock:,}")
        self.kpis["low_stock"].set_accent(theme.warning if data.low_stock else theme.success)
        self.kpis["low_stock"].set_hint("at or below reorder level")
        self.kpis["out_of_stock"].set_value(f"{data.out_of_stock:,}")
        self.kpis["out_of_stock"].set_accent(theme.danger if data.out_of_stock else theme.success)
        self.kpis["out_of_stock"].set_hint("cannot be sold until restocked")

        self.kpis["today_sales"].set_clickable(lambda: self.window_ref.show_page("sales"))
        self.kpis["products"].set_clickable(lambda: self.window_ref.show_page("products"))
        self.kpis["low_stock"].set_clickable(lambda: self.window_ref.show_page("inventory"))
        self.kpis["out_of_stock"].set_clickable(lambda: self.window_ref.show_page("inventory"))

        self.sales_chart.set_data(data.sales_series)
        colors = stock_status_colors()
        slices = [
            Slice(label, data.stock_status.get(label, 0), colors[label])
            for label in StockStatus.ALL
        ]
        self.stock_chart.set_data(slices, center_label="Products")

        self.low_stock_table.set_rows([
            [
                product.name,
                f"{product.stock_quantity:,}",
                f"{product.reorder_level:,}",
                StatusBadge(product.stock_status),
            ]
            for product in data.low_stock_products
        ])
        self.top_table.set_rows([
            [row["name"], f"{row['quantity']:,}", format_money(row["revenue"])]
            for row in data.top_products
        ])
        self.activity_table.set_rows([
            [
                format_time(event["when"]) if _is_today(event["when"])
                else event["when"].strftime("%d %b") if event["when"] else "",
                f"{event['title']}  -  {event['detail']}",
                format_money(event["amount"]) if event["amount"] is not None else "",
            ]
            for event in data.recent_activity
        ])


def _is_today(when) -> bool:
    return bool(when) and when.date() == datetime.now().date()
