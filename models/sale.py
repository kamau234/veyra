"""Sale header."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.types import Money


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    sale_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )
    subtotal: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    vat_amount: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    discount: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    total: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    vat_rate_snapshot: Mapped[object] = mapped_column(Money, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    items: Mapped[list["SaleItem"]] = relationship(  # noqa: F821
        back_populates="sale",
        cascade="all, delete-orphan",
        order_by="SaleItem.id",
        lazy="selectin",
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    def __repr__(self) -> str:
        return f"<Sale {self.invoice_number} total={self.total}>"
