"""Master product catalogue."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.constants import StockStatus
from db.base import Base
from db.types import Money


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Category -> Subcategory -> Brand -> Product Name -> Code. Subcategory and
    #: brand are free text on purpose: they stay NULL for products where they
    #: genuinely do not apply, and no lookup tables are invented for them.
    subcategory: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="Piece")
    cost_price: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    selling_price: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vat_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    category: Mapped["Category | None"] = relationship(back_populates="products")  # noqa: F821
    movements: Mapped[list["StockMovement"]] = relationship(  # noqa: F821
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="desc(StockMovement.created_at)",
    )

    @property
    def stock_status(self) -> str:
        """Blueprint 14.2: 0 -> Out of Stock, <= reorder -> Low Stock."""
        stock = self.stock_quantity or 0
        if stock <= 0:
            return StockStatus.OUT_OF_STOCK
        if stock <= (self.reorder_level or 0):
            return StockStatus.LOW_STOCK
        return StockStatus.IN_STOCK

    @property
    def stock_value(self):
        from core.money import to_money

        return to_money(self.cost_price) * (self.stock_quantity or 0)

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else "Uncategorised"

    @property
    def subcategory_name(self) -> str:
        return self.subcategory or ""

    @property
    def brand_name(self) -> str:
        return self.brand or ""

    @property
    def classification(self) -> str:
        """The non-empty hierarchy levels, broadest first, for display/reports."""
        return " > ".join(
            part
            for part in (self.category_name, self.subcategory or "", self.brand or "")
            if part and part != "Uncategorised"
        )

    def has_low_stock(self) -> bool:
        return self.stock_status == StockStatus.LOW_STOCK

    def __repr__(self) -> str:
        return f"<Product {self.code} {self.name!r} stock={self.stock_quantity}>"
