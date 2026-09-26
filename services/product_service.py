"""Product catalogue: validation, CRUD and safe deletion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from core.constants import UNITS, MovementType, Reason
from core.exceptions import BusinessRuleError, ValidationError
from core.logger import get_logger
from core.money import ZERO, parse_money, to_int
from db.session import session_scope
from models import Category, Product
from repositories.category_repository import CategoryRepository, normalize_name
from repositories.product_repository import ProductRepository
from services.inventory_service import apply_movement

logger = get_logger("services.products")


@dataclass
class ProductInput:
    """Everything the Add/Edit dialog (or an import row) supplies."""

    code: str = ""
    name: str = ""
    category: str = ""
    unit: str = "Piece"
    cost_price: Decimal | str | int | float = ZERO
    selling_price: Decimal | str | int | float = ZERO
    stock_quantity: int = 0
    reorder_level: int = 0
    vat_applicable: bool = True
    image_path: str | None = None


def normalize_unit(unit: str | None) -> str:
    """Accept a known unit or normalized free text; never silently coerce."""
    normalized = " ".join(str(unit or "").split()).title()
    if not normalized:
        return "Piece"
    for known in UNITS:
        if known.lower() == normalized.lower():
            return known
    return normalized


def normalize_code(code: str | None) -> str:
    return " ".join(str(code or "").split()).upper()


def normalize_boolean(value) -> bool:
    """Normalize Yes/No/True/1 style input (used by forms and imports)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float, Decimal)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"yes", "y", "true", "1", "vat", "applicable"}:
        return True
    if text in {"no", "n", "false", "0", "", "none", "n/a"}:
        return False
    raise ValidationError("Use Yes or No.", field="vat_applicable")


def validate(data: ProductInput, session: Session, *, exclude_id: int | None = None) -> dict:
    """Validate and normalize a product payload, raising on the first problem.

    Returns the cleaned field dictionary ready to be applied to a model.
    """
    products = ProductRepository(session)
    errors: list[str] = []

    code = normalize_code(data.code)
    if not code:
        errors.append("Product Code is required.")
    elif products.code_exists(code, exclude_id=exclude_id):
        errors.append(f"Product Code '{code}' is already used by another product.")

    name = normalize_name(data.name)
    if not name:
        errors.append("Product Name is required.")

    try:
        cost_price = parse_money(data.cost_price)
    except ValueError:
        cost_price = None
        errors.append("Cost Price must be a number.")
    if cost_price is not None and cost_price < 0:
        errors.append("Cost Price cannot be negative.")

    try:
        selling_price = parse_money(data.selling_price)
    except ValueError:
        selling_price = None
        errors.append("Selling Price must be a number.")
    if selling_price is not None and selling_price < 0:
        errors.append("Selling Price cannot be negative.")

    try:
        stock_quantity = to_int(data.stock_quantity, field="Opening Stock")
    except ValueError as exc:
        stock_quantity = 0
        errors.append(str(exc))

    try:
        reorder_level = to_int(data.reorder_level, field="Reorder Level")
    except ValueError as exc:
        reorder_level = 0
        errors.append(str(exc))

    if errors:
        raise ValidationError(errors[0], detail=" ".join(errors))

    category_name = normalize_name(data.category)
    return {
        "code": code,
        "name": name,
        "category_name": category_name,
        "unit": normalize_unit(data.unit),
        "cost_price": cost_price,
        "selling_price": selling_price,
        "stock_quantity": stock_quantity,
        "reorder_level": reorder_level,
        "vat_applicable": normalize_boolean(data.vat_applicable),
        "image_path": data.image_path,
    }


def _apply_fields(session: Session, product: Product, fields: dict, *, include_stock: bool) -> None:
    product.code = fields["code"]
    product.name = fields["name"]
    product.unit = fields["unit"]
    product.cost_price = fields["cost_price"]
    product.selling_price = fields["selling_price"]
    product.reorder_level = fields["reorder_level"]
    product.vat_applicable = fields["vat_applicable"]
    if fields.get("image_path") is not None:
        product.image_path = fields["image_path"]

    category, _created = CategoryRepository(session).get_or_create(fields["category_name"])
    product.category_id = category.id if category else None

    if include_stock:
        product.stock_quantity = fields["stock_quantity"]


def create_product(data: ProductInput) -> Product:
    """Create a product; opening stock is written to the ledger for traceability."""
    with session_scope() as session:
        fields = validate(data, session)
        product = Product(is_active=True)
        _apply_fields(session, product, fields, include_stock=False)
        product.stock_quantity = 0
        session.add(product)
        session.flush()

        opening = fields["stock_quantity"]
        if opening > 0:
            apply_movement(
                session,
                product=product,
                movement_type=MovementType.STOCK_IN,
                reason=Reason.INITIAL_STOCK,
                quantity=opening,
                direction="in",
                notes="Opening stock recorded when the product was created.",
            )
        logger.info("Created product %s (%s)", product.code, product.name)
        _ = product.category  # load the relationship before the session closes
        return product


def update_product(product_id: int, data: ProductInput) -> Product:
    """Update master data only — stock changes belong in Inventory (blueprint 6.1)."""
    with session_scope() as session:
        product = session.get(Product, product_id)
        if product is None:
            raise BusinessRuleError("That product no longer exists.")
        fields = validate(data, session, exclude_id=product_id)
        previous_code = product.code
        _apply_fields(session, product, fields, include_stock=False)
        if previous_code != fields["code"]:
            logger.warning(
                "Product code changed from %s to %s (historical records keep the old code)",
                previous_code,
                fields["code"],
            )
        session.flush()
        _ = product.category  # load the relationship before the session closes
        return product


def set_image(product_id: int, stored_path: str | None) -> None:
    with session_scope() as session:
        product = session.get(Product, product_id)
        if product is None:
            raise BusinessRuleError("That product no longer exists.")
        product.image_path = stored_path


def set_active(product_id: int, is_active: bool) -> str:
    """Archive or restore a product; returns a human-readable outcome."""
    with session_scope() as session:
        product = session.get(Product, product_id)
        if product is None:
            raise BusinessRuleError("That product no longer exists.")
        product.is_active = is_active
        return f"{product.name} was {'restored' if is_active else 'archived'}."


def delete_product(product_id: int) -> tuple[str, str]:
    """Delete a product with no history; archive it otherwise (blueprint 6.6).

    Returns (outcome, message) where outcome is ``deleted`` or ``archived``.
    """
    with session_scope() as session:
        product = session.get(Product, product_id)
        if product is None:
            raise BusinessRuleError("That product no longer exists.")

        if ProductRepository(session).has_history(product_id):
            product.is_active = False
            logger.info("Archived product %s (has sales/stock history)", product.code)
            return "archived", (
                f"{product.name} has sales or stock history, so it was archived instead "
                "of deleted. Archived products stay out of the POS and reports."
            )

        name = product.name
        ProductRepository(session).delete(product)
        logger.info("Deleted product %s", name)
        return "deleted", f"{name} was permanently deleted."


# ------------------------------------------------------------------- queries


def list_products(**filters) -> list[Product]:
    with session_scope() as session:
        return ProductRepository(session).list_products(**filters)


def get_product(product_id: int) -> Product | None:
    with session_scope() as session:
        return session.scalars(
            ProductRepository(session)
            .build_query(include_inactive=True)
            .where(Product.id == product_id)
        ).unique().first()


def find_by_code(code: str) -> Product | None:
    with session_scope() as session:
        return ProductRepository(session).get_by_code(code)


def list_categories() -> list[Category]:
    with session_scope() as session:
        return CategoryRepository(session).list_all()


def category_names() -> list[str]:
    return [category.name for category in list_categories()]


def pos_products(*, search: str | None = None, category_id: int | None = None) -> list[Product]:
    with session_scope() as session:
        return ProductRepository(session).for_pos(search=search, category_id=category_id)


def catalogue_stats() -> dict:
    with session_scope() as session:
        products = ProductRepository(session)
        return {
            "products": products.count(),
            "categories": CategoryRepository(session).count(),
            "archived": products.count(include_inactive=True) - products.count(),
        }


def attention_products(*, limit: int | None = None) -> list[Product]:
    with session_scope() as session:
        return ProductRepository(session).attention_list(limit=limit)
