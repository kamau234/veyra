"""Stock movement ledger queries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from models import Product, StockMovement


class StockRepository:
    def __init__(self, session: Session):
        self.session = session

    def build_query(
        self,
        *,
        search: str | None = None,
        product_id: int | None = None,
        category_id: int | None = None,
        movement_type: str | None = None,
        reason: str | None = None,
        direction: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        stmt = (
            select(StockMovement)
            .options(joinedload(StockMovement.product).joinedload(Product.category))
            .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        )
        if product_id:
            stmt = stmt.where(StockMovement.product_id == product_id)
        if category_id:
            stmt = stmt.join(Product, Product.id == StockMovement.product_id).where(
                Product.category_id == category_id
            )
        if movement_type and movement_type != "All":
            stmt = stmt.where(StockMovement.movement_type == movement_type)
        if reason and reason != "All":
            stmt = stmt.where(StockMovement.reason == reason)
        if direction and direction != "All":
            stmt = stmt.where(StockMovement.direction == direction)
        if start:
            stmt = stmt.where(StockMovement.created_at >= start)
        if end:
            stmt = stmt.where(StockMovement.created_at <= end)
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.join(Product, Product.id == StockMovement.product_id, isouter=True).where(
                func.lower(Product.name).like(pattern)
                | func.lower(Product.code).like(pattern)
                | func.lower(func.coalesce(StockMovement.reference, "")).like(pattern)
            )
        return stmt

    def list_movements(self, *, limit: int | None = None, **filters) -> list[StockMovement]:
        stmt = self.build_query(**filters)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def recent(self, *, limit: int = 6) -> list[StockMovement]:
        return self.list_movements(limit=limit)

    def count(self, **filters) -> int:
        stmt = select(func.count()).select_from(self.build_query(**filters).subquery())
        return int(self.session.scalar(stmt) or 0)

    def for_product(self, product_id: int, *, limit: int | None = None) -> list[StockMovement]:
        return self.list_movements(product_id=product_id, limit=limit)

    def totals(self, *, start: datetime | None = None, end: datetime | None = None) -> dict:
        """Units in and units out for a period."""
        stmt = select(
            StockMovement.direction,
            func.coalesce(func.sum(StockMovement.quantity), 0),
            func.count(StockMovement.id),
        ).group_by(StockMovement.direction)
        if start:
            stmt = stmt.where(StockMovement.created_at >= start)
        if end:
            stmt = stmt.where(StockMovement.created_at <= end)
        result = {"in": 0, "out": 0, "movements": 0}
        for direction, quantity, count in self.session.execute(stmt):
            result[direction] = int(quantity or 0)
            result["movements"] += int(count or 0)
        return result

    def reason_breakdown(
        self, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict]:
        stmt = select(
            StockMovement.reason,
            StockMovement.direction,
            func.coalesce(func.sum(StockMovement.quantity), 0),
            func.count(StockMovement.id),
        ).group_by(StockMovement.reason, StockMovement.direction)
        if start:
            stmt = stmt.where(StockMovement.created_at >= start)
        if end:
            stmt = stmt.where(StockMovement.created_at <= end)
        return [
            {
                "reason": reason,
                "direction": direction,
                "quantity": int(quantity or 0),
                "movements": int(count or 0),
            }
            for reason, direction, quantity, count in self.session.execute(stmt)
        ]

    def add(self, movement: StockMovement) -> StockMovement:
        self.session.add(movement)
        self.session.flush()
        return movement
