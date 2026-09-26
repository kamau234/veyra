"""Inventory: stock movements and the current-stock overview.

Blueprint 8.6 validation and the rule that a successful movement updates
``Product.stock_quantity`` and writes a ``StockMovement`` row in the same
database transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from core.constants import (
    DIRECTION_BY_TYPE,
    NOTES_REQUIRED_REASONS,
    MovementType,
    Reason,
)
from core.exceptions import BusinessRuleError, ValidationError
from core.logger import get_logger
from core.money import to_int
from db.session import session_scope
from models import Product, StockMovement
from repositories.product_repository import ProductRepository
from repositories.stock_repository import StockRepository

logger = get_logger("services.inventory")

MAX_NOTE_LENGTH = 500
MAX_REFERENCE_LENGTH = 80


@dataclass(frozen=True)
class MovementResult:
    movement_id: int
    product_id: int
    product_name: str
    movement_type: str
    direction: str
    quantity: int
    reason: str
    previous_stock: int
    new_stock: int
    created_at: datetime

    @property
    def message(self) -> str:
        sign = "+" if self.direction == "in" else "-"
        return (
            f"{self.product_name}: {sign}{self.quantity} ({self.reason}). "
            f"Stock was {self.previous_stock}, now {self.new_stock}."
        )


@dataclass
class StockSummary:
    total_units: int
    stock_value: object
    product_count: int
    in_stock: int
    low_stock: int
    out_of_stock: int


def resolve_direction(movement_type: str, direction: str | None) -> str:
    """Fixed-direction types ignore the supplied direction; adjustments need one."""
    movement_type = (movement_type or "").strip()
    if movement_type not in MovementType.ALL:
        raise ValidationError("Choose a valid movement type.", field="movement_type")
    fixed = DIRECTION_BY_TYPE.get(movement_type)
    if fixed:
        return fixed
    if direction not in ("in", "out"):
        raise ValidationError(
            "An adjustment needs an explicit direction (increase or decrease).",
            field="direction",
        )
    return direction


def normalize_reason(reason: str | None) -> str:
    normalized = " ".join(str(reason or "").split()).title()
    if normalized not in Reason.ALL:
        raise ValidationError(
            f"Unknown reason '{reason}'. Choose one from the list.", field="reason"
        )
    return normalized


def validate_movement(
    *,
    product: Product | None,
    movement_type: str,
    reason: str,
    quantity,
    direction: str | None,
    notes: str | None,
) -> tuple[str, str, int]:
    """Return (movement_type, reason, quantity) or raise a user-facing error."""
    if product is None:
        raise ValidationError("Select a product.", field="product")
    if not product.is_active:
        raise BusinessRuleError(f"{product.name} is archived and cannot be adjusted.")

    resolved_direction = resolve_direction(movement_type, direction)
    resolved_reason = normalize_reason(reason)
    amount = to_int(quantity, field="Quantity")
    if amount <= 0:
        raise ValidationError("Quantity must be greater than zero.", field="quantity")

    if resolved_direction == "out" and amount > product.stock_quantity:
        raise BusinessRuleError(
            f"Only {product.stock_quantity} in stock for {product.name}. "
            f"Stock cannot go negative."
        )
    if resolved_reason in NOTES_REQUIRED_REASONS and not (notes or "").strip():
        raise ValidationError(
            "A correction needs a note explaining why stock was adjusted.", field="notes"
        )
    return movement_type.strip(), resolved_reason, amount


def apply_movement(
    session: Session,
    *,
    product: Product,
    movement_type: str,
    reason: str,
    quantity: int,
    direction: str,
    reference: str | None = None,
    notes: str | None = None,
    sale_id: int | None = None,
    created_at: datetime | None = None,
) -> StockMovement:
    """Mutate stock and append the ledger row inside the caller's transaction."""
    previous = product.stock_quantity or 0
    delta = quantity if direction == "in" else -quantity
    new_stock = previous + delta
    if new_stock < 0:
        raise BusinessRuleError(
            f"Stock for {product.name} would go negative ({new_stock})."
        )

    product.stock_quantity = new_stock
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        direction=direction,
        quantity=quantity,
        reason=reason,
        reference=(reference or "").strip()[:MAX_REFERENCE_LENGTH] or None,
        notes=(notes or "").strip()[:MAX_NOTE_LENGTH] or None,
        sale_id=sale_id,
        balance_after=new_stock,
        created_at=created_at or datetime.now(),
    )
    session.add(movement)
    session.flush()
    return movement


def record_movement(
    *,
    product_id: int,
    movement_type: str,
    reason: str,
    quantity,
    direction: str | None = None,
    reference: str | None = None,
    notes: str | None = None,
) -> MovementResult:
    """Validate then commit one stock movement atomically."""
    with session_scope() as session:
        product = ProductRepository(session).get(product_id)
        if product is None:
            raise ValidationError("That product no longer exists.", field="product")

        resolved_type, resolved_reason, amount = validate_movement(
            product=product,
            movement_type=movement_type,
            reason=reason,
            quantity=quantity,
            direction=direction,
            notes=notes,
        )
        resolved_direction = resolve_direction(resolved_type, direction)
        previous = product.stock_quantity or 0

        movement = apply_movement(
            session,
            product=product,
            movement_type=resolved_type,
            reason=resolved_reason,
            quantity=amount,
            direction=resolved_direction,
            reference=reference,
            notes=notes,
        )
        logger.info(
            "Stock movement %s: product=%s type=%s qty=%s reason=%s",
            movement.id,
            product.code,
            resolved_type,
            amount,
            resolved_reason,
        )
        return MovementResult(
            movement_id=movement.id,
            product_id=product.id,
            product_name=product.name,
            movement_type=resolved_type,
            direction=resolved_direction,
            quantity=amount,
            reason=resolved_reason,
            previous_stock=previous,
            new_stock=movement.balance_after,
            created_at=movement.created_at,
        )


def preview_resulting_stock(product_stock: int, movement_type: str, quantity, direction=None) -> int:
    """Used by the dialog's live 'Resulting stock' label."""
    amount = to_int(quantity, field="Quantity")
    resolved = resolve_direction(movement_type, direction)
    return product_stock + (amount if resolved == "in" else -amount)


def list_movements(**filters) -> list[StockMovement]:
    with session_scope() as session:
        return StockRepository(session).list_movements(**filters)


def movements_for_product(product_id: int, *, limit: int | None = None) -> list[StockMovement]:
    with session_scope() as session:
        return StockRepository(session).for_product(product_id, limit=limit)


def summary() -> StockSummary:
    with session_scope() as session:
        products = ProductRepository(session)
        counts = products.status_counts()
        from core.constants import StockStatus

        return StockSummary(
            total_units=products.total_units(),
            stock_value=products.stock_value(),
            product_count=products.count(),
            in_stock=counts[StockStatus.IN_STOCK],
            low_stock=counts[StockStatus.LOW_STOCK],
            out_of_stock=counts[StockStatus.OUT_OF_STOCK],
        )
