"""Product line within a sale.

Blueprint 13.4: the product's name, code, unit price and cost price are stored
as snapshots so editing product master data later never rewrites history.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.types import Money


class SaleItem(Base):
    __tablename__ = "sale_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_code_snapshot: Mapped[str] = mapped_column(String(60), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_snapshot: Mapped[str] = mapped_column(String(30), nullable=False, default="Piece")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[object] = mapped_column(Money, nullable=False)
    cost_price_snapshot: Mapped[object] = mapped_column(Money, nullable=False)
    vat_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    vat_amount: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    discount_allocated: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    line_total: Mapped[object] = mapped_column(Money, nullable=False)

    sale: Mapped["Sale"] = relationship(back_populates="items")  # noqa: F821
    product: Mapped["Product"] = relationship()  # noqa: F821

    @property
    def gross_profit(self):
        """Estimated retail margin: revenue less estimated cost (blueprint 11.4)."""
        from core.money import to_money

        return to_money(self.line_total) - (
            to_money(self.cost_price_snapshot) * self.quantity
        )

    def __repr__(self) -> str:
        return f"<SaleItem {self.product_code_snapshot} x{self.quantity}>"
