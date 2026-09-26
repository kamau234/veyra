"""Sale and sale-item queries, including the aggregates behind dashboards."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from core.config import INVOICE_PREFIX
from core.money import to_money
from models import Sale, SaleItem


def _money(value) -> Decimal:
    """Normalize a money aggregate.

    ``func.sum``/``func.coalesce`` over a Money column inherit the Money type,
    so results already arrive as Decimal; this only re-quantizes to 2dp.
    """
    return to_money(value)


class SaleRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ reads

    def build_query(
        self,
        *,
        search: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        stmt = select(Sale).order_by(Sale.sale_date.desc(), Sale.id.desc())
        if search:
            stmt = stmt.where(func.lower(Sale.invoice_number).like(f"%{search.strip().lower()}%"))
        if start:
            stmt = stmt.where(Sale.sale_date >= start)
        if end:
            stmt = stmt.where(Sale.sale_date <= end)
        return stmt

    def list_sales(self, *, limit: int | None = None, **filters) -> list[Sale]:
        stmt = self.build_query(**filters)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get(self, sale_id: int | None) -> Sale | None:
        if not sale_id:
            return None
        stmt = select(Sale).options(joinedload(Sale.items)).where(Sale.id == sale_id)
        return self.session.scalars(stmt).unique().first()

    def get_by_invoice(self, invoice_number: str) -> Sale | None:
        stmt = (
            select(Sale)
            .options(joinedload(Sale.items))
            .where(func.lower(Sale.invoice_number) == invoice_number.strip().lower())
        )
        return self.session.scalars(stmt).unique().first()

    def count(self, *, start: datetime | None = None, end: datetime | None = None) -> int:
        stmt = select(func.count(Sale.id))
        if start:
            stmt = stmt.where(Sale.sale_date >= start)
        if end:
            stmt = stmt.where(Sale.sale_date <= end)
        return int(self.session.scalar(stmt) or 0)

    # ------------------------------------------------------------- aggregates

    def totals(self, *, start: datetime | None = None, end: datetime | None = None) -> dict:
        """Revenue, VAT, discount and invoice count for a period."""
        stmt = select(
            func.coalesce(func.sum(Sale.total), 0),
            func.coalesce(func.sum(Sale.subtotal), 0),
            func.coalesce(func.sum(Sale.vat_amount), 0),
            func.coalesce(func.sum(Sale.discount), 0),
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.item_count), 0),
        )
        if start:
            stmt = stmt.where(Sale.sale_date >= start)
        if end:
            stmt = stmt.where(Sale.sale_date <= end)
        total, subtotal, vat, discount, invoices, items = self.session.execute(stmt).one()
        return {
            "total": _money(total),
            "subtotal": _money(subtotal),
            "vat": _money(vat),
            "discount": _money(discount),
            "invoices": int(invoices or 0),
            "items": int(items or 0),
        }

    def daily_series(self, *, start: datetime, end: datetime) -> dict[date, dict]:
        """Per-day totals, zero-filled across the whole requested range."""
        from core.dates import each_day

        day_expr = func.date(Sale.sale_date)
        stmt = (
            select(
                day_expr.label("day"),
                func.coalesce(func.sum(Sale.total), 0),
                func.count(Sale.id),
            )
            .where(Sale.sale_date >= start, Sale.sale_date <= end)
            .group_by(day_expr)
            .order_by(day_expr)
        )
        series = {day: {"total": Decimal("0.00"), "invoices": 0} for day in each_day(start, end)}
        for raw_day, total, invoices in self.session.execute(stmt):
            day = date.fromisoformat(str(raw_day)[:10])
            if day in series:
                series[day] = {"total": _money(total), "invoices": int(invoices or 0)}
        return series

    def daily_totals(self, *, start: datetime, end: datetime) -> list[dict]:
        """One row per day that had sales, oldest first."""
        day_expr = func.date(Sale.sale_date)
        stmt = (
            select(
                day_expr.label("day"),
                func.count(Sale.id),
                func.coalesce(func.sum(Sale.item_count), 0),
                func.coalesce(func.sum(Sale.subtotal), 0),
                func.coalesce(func.sum(Sale.vat_amount), 0),
                func.coalesce(func.sum(Sale.discount), 0),
                func.coalesce(func.sum(Sale.total), 0),
            )
            .where(Sale.sale_date >= start, Sale.sale_date <= end)
            .group_by(day_expr)
            .order_by(day_expr)
        )
        return [
            {
                "date": date.fromisoformat(str(day)[:10]),
                "invoices": int(invoices or 0),
                "items": int(items or 0),
                "subtotal": _money(subtotal),
                "vat": _money(vat),
                "discount": _money(discount),
                "total": _money(total),
            }
            for day, invoices, items, subtotal, vat, discount, total in self.session.execute(stmt)
        ]

    def top_products(
        self, *, start: datetime | None = None, end: datetime | None = None, limit: int = 5
    ) -> list[dict]:
        """Best sellers by quantity, with revenue and estimated gross profit."""
        stmt = (
            select(
                SaleItem.product_name_snapshot,
                SaleItem.product_code_snapshot,
                func.coalesce(func.sum(SaleItem.quantity), 0),
                func.coalesce(func.sum(SaleItem.line_total), 0),
                func.coalesce(func.sum(SaleItem.quantity * SaleItem.cost_price_snapshot), 0),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .group_by(SaleItem.product_name_snapshot, SaleItem.product_code_snapshot)
            .order_by(func.sum(SaleItem.quantity).desc())
            .limit(limit)
        )
        if start:
            stmt = stmt.where(Sale.sale_date >= start)
        if end:
            stmt = stmt.where(Sale.sale_date <= end)
        return [
            {
                "name": name,
                "code": code,
                "quantity": int(quantity or 0),
                "revenue": _money(revenue),
                "estimated_cost": _money(cost),
                "gross_profit": _money(revenue) - _money(cost),
            }
            for name, code, quantity, revenue, cost in self.session.execute(stmt)
        ]

    def product_sales(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict]:
        """Every product sold in a period (Product Sales / Gross Profit reports)."""
        stmt = (
            select(
                SaleItem.product_code_snapshot,
                SaleItem.product_name_snapshot,
                func.coalesce(func.sum(SaleItem.quantity), 0),
                func.coalesce(func.sum(SaleItem.line_total), 0),
                func.coalesce(func.sum(SaleItem.quantity * SaleItem.cost_price_snapshot), 0),
                func.coalesce(func.sum(SaleItem.vat_amount), 0),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .group_by(SaleItem.product_code_snapshot, SaleItem.product_name_snapshot)
            .order_by(func.sum(SaleItem.line_total).desc())
        )
        if start:
            stmt = stmt.where(Sale.sale_date >= start)
        if end:
            stmt = stmt.where(Sale.sale_date <= end)
        return [
            {
                "code": code,
                "name": name,
                "quantity": int(quantity or 0),
                "revenue": _money(revenue),
                "estimated_cost": _money(cost),
                "gross_profit": _money(revenue) - _money(cost),
                "vat": _money(vat),
            }
            for code, name, quantity, revenue, cost, vat in self.session.execute(stmt)
        ]

    def recent(self, *, limit: int = 6) -> list[Sale]:
        return self.list_sales(limit=limit)

    # ----------------------------------------------------------------- writes

    def next_invoice_number(self) -> str:
        """INV-00001 style, continuing from the highest existing number."""
        highest = self.session.scalar(select(func.max(Sale.invoice_number))) or ""
        suffix = highest.rsplit("-", 1)[-1]
        try:
            number = int(suffix)
        except ValueError:
            number = 0
        return f"{INVOICE_PREFIX}-{number + 1:05d}"

    def add(self, sale: Sale) -> Sale:
        self.session.add(sale)
        self.session.flush()
        return sale
