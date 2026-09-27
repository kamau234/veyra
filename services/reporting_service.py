"""Analytics, sales history and every report in the Reports module.

Reports return a ``ReportResult`` — columns plus row dictionaries — so the UI
can render a table and the exporters can write CSV/XLSX/PDF from the same data
without duplicating query logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from core.constants import Period, StockStatus
from core.dates import format_datetime, format_range, resolve_period
from core.money import ZERO, to_money
from db.session import session_scope
from models import Sale
from repositories.product_repository import ProductRepository
from repositories.sale_repository import SaleRepository
from repositories.stock_repository import StockRepository

# ---------------------------------------------------------------- result types


@dataclass(frozen=True)
class ReportColumn:
    key: str
    label: str
    kind: str = "text"  # text | money | int | datetime | date
    align: str = "left"

    def format(self, value) -> str:
        if value is None or value == "":
            return ""
        if self.kind == "money":
            return f"{to_money(value):,.2f}"
        if self.kind == "int":
            return f"{int(value):,d}"
        if self.kind == "datetime":
            return format_datetime(value) if isinstance(value, datetime) else str(value)
        if self.kind == "date":
            return value.strftime("%d %b %Y") if isinstance(value, date) else str(value)
        return str(value)


@dataclass(frozen=True)
class ReportResult:
    title: str
    columns: list[ReportColumn]
    rows: list[dict] = field(default_factory=list)
    totals: dict | None = None
    period_label: str = ""
    subtitle: str = ""
    generated_at: datetime = field(default_factory=datetime.now)
    notes: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class DashboardData:
    today_sales: Decimal
    transactions: int
    products: int
    stock_value: Decimal
    low_stock: int
    out_of_stock: int
    sales_series: list[tuple[date, Decimal]]
    stock_status: dict[str, int]
    top_products: list[dict]
    low_stock_products: list
    recent_activity: list[dict]
    total_units: int
    month_sales: Decimal


# ------------------------------------------------------------------ dashboard


def dashboard_data(*, chart_days: int = 7, limit: int = 5) -> DashboardData:
    """Everything the dashboard renders, calculated from transactional data."""
    with session_scope() as session:
        sales = SaleRepository(session)
        products = ProductRepository(session)
        movements = StockRepository(session)

        today_start, today_end = resolve_period(Period.TODAY)
        today = sales.totals(start=today_start, end=today_end)
        month_start, month_end = resolve_period(Period.THIS_MONTH)
        month = sales.totals(start=month_start, end=month_end)

        chart_start, chart_end = resolve_period(Period.LAST_7_DAYS)
        if chart_days != 7:
            from core.dates import last_days_range

            chart_start, chart_end = last_days_range(chart_days)
        series = sales.daily_series(start=chart_start, end=chart_end)

        counts = products.status_counts()
        activity = _recent_activity(sales, movements, limit=8)

        return DashboardData(
            today_sales=today["total"],
            transactions=today["invoices"],
            products=products.count(),
            stock_value=products.stock_value(),
            low_stock=counts[StockStatus.LOW_STOCK],
            out_of_stock=counts[StockStatus.OUT_OF_STOCK],
            sales_series=[(day, values["total"]) for day, values in series.items()],
            stock_status=counts,
            top_products=sales.top_products(start=chart_start, end=chart_end, limit=limit),
            low_stock_products=products.attention_list(limit=limit),
            recent_activity=activity,
            total_units=products.total_units(),
            month_sales=month["total"],
        )


def _recent_activity(sales: SaleRepository, movements: StockRepository, *, limit: int) -> list[dict]:
    """Recent sales and stock movements merged, newest first."""
    events: list[dict] = []
    for sale in sales.recent(limit=limit):
        events.append(
            {
                "kind": "sale",
                "title": f"Sale {sale.invoice_number}",
                "detail": f"{sale.item_count} line{'s' if sale.item_count != 1 else ''}",
                "amount": to_money(sale.total),
                "when": sale.sale_date,
            }
        )
    for movement in movements.recent(limit=limit):
        sign = "+" if movement.direction == "in" else "-"
        events.append(
            {
                "kind": "movement",
                "title": f"{movement.reason}: {movement.product.name}",
                "detail": f"{sign}{movement.quantity} ({movement.movement_type})",
                "amount": None,
                "when": movement.created_at,
            }
        )
    events.sort(key=lambda event: event["when"] or datetime.min, reverse=True)
    return events[:limit]


# ------------------------------------------------------------- sales history


def list_sales(
    *,
    search: str | None = None,
    period: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
) -> tuple[list[Sale], dict, str]:
    """Sales list plus period totals and a human-readable period label."""
    range_start, range_end = resolve_period(period, start, end)
    with session_scope() as session:
        sales = SaleRepository(session)
        rows = sales.list_sales(
            search=search, start=range_start, end=range_end, limit=limit
        )
        totals = sales.totals(start=range_start, end=range_end)
    return rows, totals, format_range(range_start, range_end)


def get_sale(sale_id: int) -> Sale | None:
    with session_scope() as session:
        return SaleRepository(session).get(sale_id)


def find_sale_by_invoice(invoice_number: str) -> Sale | None:
    with session_scope() as session:
        return SaleRepository(session).get_by_invoice(invoice_number)


def sales_summary(period: str | None = None, start=None, end=None) -> dict:
    range_start, range_end = resolve_period(period, start, end)
    with session_scope() as session:
        return SaleRepository(session).totals(start=range_start, end=range_end)


# ------------------------------------------------------------------- reports

SALES_COLUMNS = [
    ReportColumn("date", "Date", "date"),
    ReportColumn("invoices", "Invoices", "int", "right"),
    ReportColumn("items", "Items Sold", "int", "right"),
    ReportColumn("subtotal", "Subtotal", "money", "right"),
    ReportColumn("vat", "VAT", "money", "right"),
    ReportColumn("discount", "Discount", "money", "right"),
    ReportColumn("total", "Total", "money", "right"),
]

PRODUCT_SALES_COLUMNS = [
    ReportColumn("code", "Code"),
    ReportColumn("name", "Product"),
    ReportColumn("quantity", "Qty Sold", "int", "right"),
    ReportColumn("revenue", "Revenue", "money", "right"),
    ReportColumn("estimated_cost", "Estimated Cost", "money", "right"),
    ReportColumn("gross_profit", "Gross Profit", "money", "right"),
    ReportColumn("margin", "Margin %", "money", "right"),
]

INVENTORY_COLUMNS = [
    ReportColumn("code", "Code"),
    ReportColumn("name", "Product"),
    ReportColumn("category", "Category"),
    ReportColumn("subcategory", "Subcategory"),
    ReportColumn("brand", "Brand"),
    ReportColumn("cost_price", "Cost Price", "money", "right"),
    ReportColumn("selling_price", "Selling Price", "money", "right"),
    ReportColumn("stock_quantity", "Stock", "int", "right"),
    ReportColumn("reorder_level", "Reorder", "int", "right"),
    ReportColumn("stock_value", "Stock Value", "money", "right"),
    ReportColumn("status", "Status"),
]

MOVEMENT_COLUMNS = [
    ReportColumn("created_at", "Date", "datetime"),
    ReportColumn("code", "Code"),
    ReportColumn("product", "Product"),
    ReportColumn("movement_type", "Movement"),
    ReportColumn("direction", "Direction"),
    ReportColumn("quantity", "Qty", "int", "right"),
    ReportColumn("balance_after", "Balance", "int", "right"),
    ReportColumn("reason", "Reason"),
    ReportColumn("reference", "Reference"),
    ReportColumn("notes", "Notes"),
]

LOW_STOCK_COLUMNS = [
    ReportColumn("code", "Code"),
    ReportColumn("name", "Product"),
    ReportColumn("category", "Category"),
    ReportColumn("stock_quantity", "Current Stock", "int", "right"),
    ReportColumn("reorder_level", "Reorder Level", "int", "right"),
    ReportColumn("status", "Status"),
]

PROFIT_COLUMNS = [
    ReportColumn("code", "Code"),
    ReportColumn("name", "Product"),
    ReportColumn("quantity", "Qty Sold", "int", "right"),
    ReportColumn("revenue", "Sales Revenue (excl. VAT)", "money", "right"),
    ReportColumn("estimated_cost", "Estimated Cost", "money", "right"),
    ReportColumn("gross_profit", "Estimated Gross Profit", "money", "right"),
    ReportColumn("margin", "Margin %", "money", "right"),
]

GROSS_PROFIT_NOTE = (
    "Estimated gross profit = sales revenue (line totals, excluding VAT) less estimated "
    "cost, where estimated cost = quantity x the product cost price captured at the time "
    "of sale. This is a retail margin measure, not an accounting profit statement."
)


def _period_label(period, start, end) -> tuple[datetime, datetime, str]:
    range_start, range_end = resolve_period(period, start, end)
    return range_start, range_end, format_range(range_start, range_end)


def sales_report(period=Period.THIS_MONTH, start=None, end=None) -> ReportResult:
    range_start, range_end, label = _period_label(period, start, end)
    with session_scope() as session:
        sales = SaleRepository(session)
        rows = sales.daily_totals(start=range_start, end=range_end)
        totals = sales.totals(start=range_start, end=range_end)

    return ReportResult(
        title="Sales Report",
        columns=SALES_COLUMNS,
        rows=rows,
        totals={
            "date": None,
            "invoices": totals["invoices"],
            "items": totals["items"],
            "subtotal": totals["subtotal"],
            "vat": totals["vat"],
            "discount": totals["discount"],
            "total": totals["total"],
        },
        period_label=label,
        subtitle="Daily sales performance (days without sales are omitted)",
    )


def product_sales_report(period=Period.THIS_MONTH, start=None, end=None) -> ReportResult:
    range_start, range_end, label = _period_label(period, start, end)
    with session_scope() as session:
        rows = SaleRepository(session).product_sales(start=range_start, end=range_end)

    for row in rows:
        row["margin"] = _margin(row["gross_profit"], row["revenue"])

    totals = {
        "quantity": sum(row["quantity"] for row in rows),
        "revenue": sum((row["revenue"] for row in rows), ZERO),
        "estimated_cost": sum((row["estimated_cost"] for row in rows), ZERO),
        "gross_profit": sum((row["gross_profit"] for row in rows), ZERO),
    }
    totals["margin"] = _margin(totals["gross_profit"], totals["revenue"])

    return ReportResult(
        title="Product Sales Report",
        columns=PRODUCT_SALES_COLUMNS,
        rows=rows,
        totals=totals,
        period_label=label,
        subtitle="Quantity sold, revenue and estimated margin per product",
        notes=[GROSS_PROFIT_NOTE],
    )


def _margin(profit: Decimal, revenue: Decimal) -> Decimal:
    if not revenue:
        return ZERO
    return to_money(profit * Decimal(100) / revenue)


def inventory_report(*, include_inactive: bool = False) -> ReportResult:
    with session_scope() as session:
        products = ProductRepository(session).list_products(
            sort="Name (A-Z)", include_inactive=include_inactive
        )
        rows = [
            {
                "code": product.code,
                "name": product.name,
                "category": product.category_name,
                "subcategory": product.subcategory_name,
                "brand": product.brand_name,
                "cost_price": to_money(product.cost_price),
                "selling_price": to_money(product.selling_price),
                "stock_quantity": product.stock_quantity,
                "reorder_level": product.reorder_level,
                "stock_value": to_money(product.stock_value),
                "status": product.stock_status if product.is_active else "Archived",
            }
            for product in products
        ]

    totals = {
        "stock_quantity": sum(row["stock_quantity"] for row in rows),
        "stock_value": sum((row["stock_value"] for row in rows), ZERO),
    }
    return ReportResult(
        title="Inventory Report",
        columns=INVENTORY_COLUMNS,
        rows=rows,
        totals=totals,
        period_label="Current stock",
        subtitle="Stock on hand valued at cost price",
    )


def stock_movement_report(period=Period.THIS_MONTH, start=None, end=None, **filters) -> ReportResult:
    range_start, range_end, label = _period_label(period, start, end)
    with session_scope() as session:
        movements = StockRepository(session).list_movements(
            start=range_start, end=range_end, **filters
        )
        rows = [
            {
                "created_at": movement.created_at,
                "code": movement.product.code if movement.product else "",
                "product": movement.product.name if movement.product else "(deleted product)",
                "movement_type": movement.movement_type,
                "direction": "In" if movement.direction == "in" else "Out",
                "quantity": movement.quantity,
                "balance_after": movement.balance_after,
                "reason": movement.reason,
                "reference": movement.reference or "",
                "notes": movement.notes or "",
            }
            for movement in movements
        ]
        totals = StockRepository(session).totals(start=range_start, end=range_end)

    return ReportResult(
        title="Stock Movement Report",
        columns=MOVEMENT_COLUMNS,
        rows=rows,
        totals={"quantity": totals["in"] - totals["out"], "movements": totals["movements"]},
        period_label=label,
        subtitle=f"Units in: {totals['in']:,}   Units out: {totals['out']:,}",
    )


def low_stock_report() -> ReportResult:
    with session_scope() as session:
        products = ProductRepository(session).attention_list()
        rows = [
            {
                "code": product.code,
                "name": product.name,
                "category": product.category_name,
                "stock_quantity": product.stock_quantity,
                "reorder_level": product.reorder_level,
                "status": product.stock_status,
            }
            for product in products
        ]

    return ReportResult(
        title="Low Stock Report",
        columns=LOW_STOCK_COLUMNS,
        rows=rows,
        totals={"stock_quantity": sum(row["stock_quantity"] for row in rows)},
        period_label="Current stock",
        subtitle="Products at or below their reorder level",
    )


def gross_profit_report(period=Period.THIS_MONTH, start=None, end=None) -> ReportResult:
    range_start, range_end, label = _period_label(period, start, end)
    with session_scope() as session:
        rows = SaleRepository(session).product_sales(start=range_start, end=range_end)
        totals = SaleRepository(session).totals(start=range_start, end=range_end)

    for row in rows:
        row["margin"] = _margin(row["gross_profit"], row["revenue"])

    total_profit = sum((row["gross_profit"] for row in rows), ZERO)
    total_revenue = sum((row["revenue"] for row in rows), ZERO)

    return ReportResult(
        title="Estimated Gross Profit Report",
        columns=PROFIT_COLUMNS,
        rows=rows,
        totals={
            "quantity": sum(row["quantity"] for row in rows),
            "revenue": total_revenue,
            "estimated_cost": sum((row["estimated_cost"] for row in rows), ZERO),
            "gross_profit": total_profit,
            "margin": _margin(total_profit, total_revenue),
        },
        period_label=label,
        subtitle=(
            f"Sales collected (incl. VAT): KSh {totals['total']:,.2f}   |   "
            f"VAT collected: KSh {totals['vat']:,.2f}   |   "
            f"Discounts given: KSh {totals['discount']:,.2f}"
        ),
        notes=[GROSS_PROFIT_NOTE],
    )


REPORTS = {
    "Sales Report": sales_report,
    "Product Sales Report": product_sales_report,
    "Inventory Report": inventory_report,
    "Stock Movement Report": stock_movement_report,
    "Low Stock Report": low_stock_report,
    "Estimated Gross Profit Report": gross_profit_report,
}

REPORT_NAMES = tuple(REPORTS)


def run_report(name: str, period=Period.THIS_MONTH, start=None, end=None) -> ReportResult:
    if name not in REPORTS:
        raise ValueError(f"Unknown report: {name!r}")
    builder = REPORTS[name]
    if name == "Inventory Report" or name == "Low Stock Report":
        return builder()
    return builder(period, start, end)


# ------------------------------------------------------------------- search


def global_search(term: str, *, limit: int = 8) -> dict[str, list[dict]]:
    """Header search across products, categories and invoice numbers (blueprint 3.2)."""
    cleaned = " ".join(str(term or "").split())
    results: dict[str, list[dict]] = {"products": [], "categories": [], "invoices": []}
    if not cleaned:
        return results

    with session_scope() as session:
        for product in ProductRepository(session).list_products(search=cleaned)[:limit]:
            results["products"].append(
                {
                    "id": product.id,
                    "label": product.name,
                    "detail": f"{product.code} | {product.classification or 'Uncategorised'} | "
                    f"stock {product.stock_quantity}",
                }
            )
        from repositories.category_repository import CategoryRepository

        for category in CategoryRepository(session).list_all():
            if cleaned.lower() in category.name.lower():
                results["categories"].append(
                    {"id": category.id, "label": category.name, "detail": "Category"}
                )
        for sale in SaleRepository(session).list_sales(search=cleaned, limit=limit):
            results["invoices"].append(
                {
                    "id": sale.id,
                    "label": sale.invoice_number,
                    "detail": f"{format_datetime(sale.sale_date)} | KSh {to_money(sale.total):,.2f}",
                }
            )
    return results
