"""Stock movement ledger — the audit trail for every quantity change."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    #: Signed effect actually applied to stock; kept for reporting clarity.
    direction: Mapped[str] = mapped_column(String(5), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    #: Sale that produced this movement, when the reason is Sale.
    sale_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Stock level immediately after the movement, for traceability.
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )

    product: Mapped["Product"] = relationship(back_populates="movements")  # noqa: F821

    @property
    def signed_quantity(self) -> int:
        return self.quantity if self.direction == "in" else -self.quantity

    def __repr__(self) -> str:
        return f"<StockMovement {self.movement_type} {self.signed_quantity} reason={self.reason}>"
