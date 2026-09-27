"""Product catalogue queries."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from core.constants import SORT_OPTIONS, StockStatus
from core.money import to_money
from models import Category, Product


def _key(value: object) -> str:
    """Whitespace-collapsed, lower-cased key for matching free-text levels."""
    return " ".join(str(value or "").split()).lower()


def _status_condition(status: str):

    """SQL expression for a stock status (blueprint 14.2)."""
    if status == StockStatus.OUT_OF_STOCK:
        return Product.stock_quantity <= 0
    if status == StockStatus.LOW_STOCK:
        return (Product.stock_quantity > 0) & (Product.stock_quantity <= Product.reorder_level)
    if status == StockStatus.IN_STOCK:
        return Product.stock_quantity > Product.reorder_level
    raise ValueError(f"Unknown stock status: {status!r}")


def _order_clause(sort: str | None):
    sort = sort or SORT_OPTIONS[0]
    return {
        "Name (A-Z)": (func.lower(Product.name),),
        "Name (Z-A)": (func.lower(Product.name).desc(),),
        "Stock (Low-High)": (Product.stock_quantity, Product.name),
        "Stock (High-Low)": (Product.stock_quantity.desc(), Product.name),
        "Code (A-Z)": (Product.code,),
        "Newest first": (Product.created_at.desc(), Product.id.desc()),
    }.get(sort, (func.lower(Product.name),))


class ProductRepository:
    def __init__(self, session: Session):
        self.session = session

    def build_query(
        self,
        *,
        search: str | None = None,
        category_id: int | None = None,
        subcategory: str | None = None,
        brand: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        include_inactive: bool = False,
    ):
        """Filter/sort products.

        ``include_inactive`` shows archived products too; selecting the
        ``Archived`` status shows only those. ``subcategory`` and ``brand``
        match case-insensitively and narrow the Category -> Subcategory ->
        Brand hierarchy one level at a time.
        """
        stmt = (
            select(Product)
            .outerjoin(Product.category)
            .options(contains_eager(Product.category))
        )
        status = status or "All"

        if status == "Archived":
            stmt = stmt.where(Product.is_active.is_(False))
        else:
            if not include_inactive:
                stmt = stmt.where(Product.is_active.is_(True))
            if status != "All":
                stmt = stmt.where(_status_condition(status))

        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if subcategory:
            stmt = stmt.where(func.lower(Product.subcategory) == _key(subcategory))
        if brand:
            stmt = stmt.where(func.lower(Product.brand) == _key(brand))
        if search:
            pattern = f"%{_key(search)}%"
            stmt = stmt.where(
                or_(
                    func.lower(Product.name).like(pattern),
                    func.lower(Product.code).like(pattern),
                    func.lower(Product.brand).like(pattern),
                    func.lower(Product.subcategory).like(pattern),
                    func.lower(Category.name).like(pattern),
                )
            )
        return stmt.order_by(*_order_clause(sort))

    def list_products(self, **filters) -> list[Product]:
        return list(self.session.scalars(self.build_query(**filters)).unique())

    def search(self, term: str, **filters) -> list[Product]:
        return self.list_products(search=term, **filters)

    def _distinct(self, column, *, category_id=None, subcategory=None) -> list[str]:
        """Distinct non-blank values of a hierarchy column, keeping their casing."""
        stmt = select(column).where(Product.is_active.is_(True), column.is_not(None))
        if category_id:
            stmt = stmt.where(Product.category_id == category_id)
        if subcategory:
            stmt = stmt.where(func.lower(Product.subcategory) == _key(subcategory))

        seen: dict[str, str] = {}
        for (value,) in self.session.execute(stmt):
            text = " ".join(str(value or "").split())
            if text:
                seen.setdefault(_key(text), text)
        return [seen[key] for key in sorted(seen)]

    def subcategories(self, *, category_id: int | None = None) -> list[str]:
        """Subcategory names in use, optionally narrowed to one category."""
        return self._distinct(Product.subcategory, category_id=category_id)

    def brands(self, *, category_id: int | None = None, subcategory: str | None = None) -> list[str]:
        """Brand names in use, optionally narrowed to a category/subcategory."""
        return self._distinct(Product.brand, category_id=category_id, subcategory=subcategory)

    def get(self, product_id: int | None) -> Product | None:
        if not product_id:
            return None
        stmt = (
            select(Product)
            .options(joinedload(Product.category))
            .where(Product.id == product_id)
        )
        return self.session.scalars(stmt).first()

    def get_by_code(self, code: str, *, include_inactive: bool = True) -> Product | None:
        normalized = " ".join(str(code or "").split())
        if not normalized:
            return None
        stmt = (
            select(Product)
            .options(joinedload(Product.category))
            .where(func.lower(Product.code) == normalized.lower())
        )
        if not include_inactive:
            stmt = stmt.where(Product.is_active.is_(True))
        return self.session.scalars(stmt).first()

    def code_exists(self, code: str, *, exclude_id: int | None = None) -> bool:
        normalized = " ".join(str(code or "").split())
        stmt = select(func.count(Product.id)).where(func.lower(Product.code) == normalized.lower())
        if exclude_id:
            stmt = stmt.where(Product.id != exclude_id)
        return int(self.session.scalar(stmt) or 0) > 0

    def count(self, *, include_inactive: bool = False) -> int:
        stmt = select(func.count(Product.id))
        if not include_inactive:
            stmt = stmt.where(Product.is_active.is_(True))
        return int(self.session.scalar(stmt) or 0)

    def status_counts(self) -> dict[str, int]:
        """Counts of active products per stock status."""
        stmt = select(
            func.sum(case((_status_condition(StockStatus.IN_STOCK), 1), else_=0)),
            func.sum(case((_status_condition(StockStatus.LOW_STOCK), 1), else_=0)),
            func.sum(case((_status_condition(StockStatus.OUT_OF_STOCK), 1), else_=0)),
        ).where(Product.is_active.is_(True))
        in_stock, low_stock, out_of_stock = self.session.execute(stmt).one()
        return {
            StockStatus.IN_STOCK: int(in_stock or 0),
            StockStatus.LOW_STOCK: int(low_stock or 0),
            StockStatus.OUT_OF_STOCK: int(out_of_stock or 0),
        }

    def stock_value(self) -> Decimal:
        """Sum of stock_quantity x cost_price for active products, in KSh."""
        stmt = select(
            func.coalesce(func.sum(Product.stock_quantity * Product.cost_price), 0)
        ).where(Product.is_active.is_(True))
        return to_money(self.session.scalar(stmt) or 0)

    def total_units(self) -> int:
        stmt = select(func.coalesce(func.sum(Product.stock_quantity), 0)).where(
            Product.is_active.is_(True)
        )
        return int(self.session.scalar(stmt) or 0)

    def low_stock(self, *, limit: int | None = None) -> list[Product]:
        stmt = (
            self.build_query(status=StockStatus.LOW_STOCK)
            .order_by(Product.stock_quantity, func.lower(Product.name))
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def out_of_stock(self, *, limit: int | None = None) -> list[Product]:
        stmt = self.build_query(status=StockStatus.OUT_OF_STOCK).order_by(
            func.lower(Product.name)
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def attention_list(self, *, limit: int | None = None) -> list[Product]:
        """Out of stock first, then lowest stock — the dashboard alert list."""
        stmt = (
            select(Product)
            .options(joinedload(Product.category))
            .where(
                Product.is_active.is_(True),
                Product.stock_quantity <= Product.reorder_level,
            )
            .order_by(Product.stock_quantity, func.lower(Product.name))
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def for_pos(self, *, search: str | None = None, category_id: int | None = None) -> list[Product]:
        """Active products for the POS browser; out-of-stock stay visible but disabled."""
        return self.list_products(search=search, category_id=category_id, sort="Name (A-Z)")

    def has_history(self, product_id: int) -> bool:
        from models import SaleItem, StockMovement

        sold = self.session.scalar(
            select(func.count(SaleItem.id)).where(SaleItem.product_id == product_id)
        )
        moved = self.session.scalar(
            select(func.count(StockMovement.id)).where(StockMovement.product_id == product_id)
        )
        return bool(sold or moved)

    def add(self, product: Product) -> Product:
        self.session.add(product)
        self.session.flush()
        return product

    def delete(self, product: Product) -> None:
        self.session.delete(product)
        self.session.flush()

    def all_active(self) -> list[Product]:
        return self.list_products(sort="Name (A-Z)")
