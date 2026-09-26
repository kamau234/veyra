"""Category queries and creation."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Category


def normalize_name(name: str) -> str:
    """Collapse whitespace so 'Detergents ' and '  detergents' are one category."""
    return " ".join(str(name or "").split())


class CategoryRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[Category]:
        return list(self.session.scalars(select(Category).order_by(Category.name)))

    def names(self) -> list[str]:
        return [category.name for category in self.list_all()]

    def get(self, category_id: int | None) -> Category | None:
        return self.session.get(Category, category_id) if category_id else None

    def get_by_name(self, name: str) -> Category | None:
        normalized = normalize_name(name)
        if not normalized:
            return None
        stmt = select(Category).where(func.lower(Category.name) == normalized.lower())
        return self.session.scalars(stmt).first()

    def get_or_create(self, name: str) -> tuple[Category | None, bool]:
        """Return (category, created). Empty names yield (None, False)."""
        normalized = normalize_name(name)
        if not normalized:
            return None, False
        existing = self.get_by_name(normalized)
        if existing:
            return existing, False
        category = Category(name=normalized)
        self.session.add(category)
        self.session.flush()
        return category, True

    def create(self, name: str) -> Category:
        category = Category(name=normalize_name(name))
        self.session.add(category)
        self.session.flush()
        return category

    def count(self) -> int:
        return int(self.session.scalar(select(func.count(Category.id))) or 0)

    def product_counts(self) -> dict[int, int]:
        """Category id -> number of active products, for display and cleanup."""
        from models import Product

        stmt = (
            select(Product.category_id, func.count(Product.id))
            .where(Product.is_active.is_(True))
            .group_by(Product.category_id)
        )
        return {category_id: count for category_id, count in self.session.execute(stmt)}

    def delete_if_unused(self, category_id: int) -> bool:
        category = self.get(category_id)
        if category is None:
            return False
        self.session.delete(category)
        self.session.flush()
        return True
