"""Point of sale: cart rules and the atomic complete-sale transaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.exceptions import BusinessRuleError, ValidationError
from core.logger import get_logger
from core.money import ZERO, to_int, to_money
from db.session import session_scope
from models import Product, Sale, SaleItem
from repositories.sale_repository import SaleRepository
from services.inventory_service import apply_movement
from services.pricing import CartLineInput, PricedCart, PricedLine, price_cart
from services.settings_service import get_settings

logger = get_logger("services.pos")


@dataclass
class CartItem:
    product_id: int
    code: str
    name: str
    unit: str
    unit_price: Decimal
    cost_price: Decimal
    vat_applicable: bool
    available_stock: int
    quantity: int = 1

    @property
    def line_total(self) -> Decimal:
        return to_money(self.unit_price) * self.quantity

    def to_input(self) -> CartLineInput:
        return CartLineInput(
            product_id=self.product_id,
            code=self.code,
            name=self.name,
            quantity=self.quantity,
            unit_price=self.unit_price,
            cost_price=self.cost_price,
            unit=self.unit,
            vat_applicable=self.vat_applicable,
            available_stock=self.available_stock,
        )


@dataclass(frozen=True)
class SaleResult:
    sale_id: int
    invoice_number: str
    subtotal: Decimal
    vat: Decimal
    discount: Decimal
    total: Decimal
    vat_rate: Decimal
    item_count: int
    total_quantity: int
    sale_date: datetime
    lines: list[PricedLine] = field(default_factory=list)

    @property
    def message(self) -> str:
        return f"Sale {self.invoice_number} completed — KSh {self.total:,.2f}"


class Cart:
    """Temporary UI state (blueprint 9.5) with stock rules enforced here."""

    def __init__(self) -> None:
        self._items: dict[int, CartItem] = {}
        self.discount: Decimal = ZERO

    # ------------------------------------------------------------------ state

    @property
    def items(self) -> list[CartItem]:
        return list(self._items.values())

    @property
    def is_empty(self) -> bool:
        return not self._items

    def __len__(self) -> int:
        return len(self._items)

    def quantity_of(self, product_id: int) -> int:
        item = self._items.get(product_id)
        return item.quantity if item else 0

    def get(self, product_id: int) -> CartItem | None:
        return self._items.get(product_id)

    def clear(self) -> None:
        self._items.clear()
        self.discount = ZERO

    # -------------------------------------------------------------- mutations

    def add(self, product: Product, quantity: int = 1) -> CartItem:
        """Add a product, merging into an existing line rather than duplicating."""
        if not product.is_active:
            raise BusinessRuleError(f"{product.name} is archived and cannot be sold.")
        amount = to_int(quantity, field="Quantity")
        if amount <= 0:
            raise ValidationError("Quantity must be greater than zero.", field="quantity")
        if product.stock_quantity <= 0:
            raise BusinessRuleError(f"{product.name} is out of stock.")

        existing = self._items.get(product.id)
        wanted = (existing.quantity if existing else 0) + amount
        if wanted > product.stock_quantity:
            raise BusinessRuleError(
                f"Only {product.stock_quantity} of {product.name} in stock "
                f"(already {existing.quantity if existing else 0} in the cart)."
            )

        if existing:
            existing.quantity = wanted
            existing.available_stock = product.stock_quantity
            existing.unit_price = to_money(product.selling_price)
            return existing

        item = CartItem(
            product_id=product.id,
            code=product.code,
            name=product.name,
            unit=product.unit,
            unit_price=to_money(product.selling_price),
            cost_price=to_money(product.cost_price),
            vat_applicable=bool(product.vat_applicable),
            available_stock=product.stock_quantity,
            quantity=amount,
        )
        self._items[product.id] = item
        return item

    def set_quantity(self, product_id: int, quantity) -> CartItem:
        item = self._items.get(product_id)
        if item is None:
            raise BusinessRuleError("That product is not in the cart.")
        amount = to_int(quantity, field="Quantity")
        if amount <= 0:
            raise ValidationError("Quantity must be greater than zero.", field="quantity")
        if amount > item.available_stock:
            raise BusinessRuleError(
                f"Only {item.available_stock} of {item.name} in stock."
            )
        item.quantity = amount
        return item

    def remove(self, product_id: int) -> None:
        self._items.pop(product_id, None)

    def set_discount(self, discount) -> Decimal:
        value = to_money(discount)
        if value < 0:
            raise ValidationError("Discount cannot be negative.", field="discount")
        self.discount = value
        return value

    # ---------------------------------------------------------------- pricing

    def price(self, *, vat_rate: Decimal | None = None, vat_enabled: bool = True) -> PricedCart:
        """Live totals for display, using the same engine as the real sale."""
        if vat_rate is None or vat_enabled is None:
            settings = get_settings()
            vat_rate = settings.vat_rate if vat_rate is None else vat_rate
            vat_enabled = settings.vat_enabled if vat_enabled is None else vat_enabled
        return price_cart(
            [item.to_input() for item in self.items],
            discount=self.discount,
            vat_rate=vat_rate,
            vat_enabled=vat_enabled,
        )


def complete_sale(
    cart: Cart,
    *,
    discount: Decimal | None = None,
    note: str | None = None,
    sale_date: datetime | None = None,
) -> SaleResult:
    """Persist a sale atomically (blueprint 9.8).

    Prices, stock and the VAT rate are re-read from the database so a stale
    POS screen can never sell more than exists or charge an outdated price.
    On any failure the transaction rolls back and no stock changes.
    """
    if cart.is_empty:
        raise BusinessRuleError("The cart is empty. Add at least one product.")

    if discount is not None:
        cart.set_discount(discount)

    with session_scope() as session:
        settings = get_settings(session)
        vat_rate = settings.effective_vat_rate

        lines: list[CartLineInput] = []
        products: dict[int, Product] = {}
        for item in cart.items:
            product = session.get(Product, item.product_id)
            if product is None:
                raise BusinessRuleError(f"{item.name} no longer exists and was removed.")
            if not product.is_active:
                raise BusinessRuleError(f"{product.name} is archived and cannot be sold.")
            if item.quantity > product.stock_quantity:
                raise BusinessRuleError(
                    f"Only {product.stock_quantity} of {product.name} remain in stock. "
                    f"The cart asked for {item.quantity}. No stock was changed."
                )
            products[product.id] = product
            lines.append(
                CartLineInput(
                    product_id=product.id,
                    code=product.code,
                    name=product.name,
                    quantity=item.quantity,
                    unit_price=to_money(product.selling_price),
                    cost_price=to_money(product.cost_price),
                    unit=product.unit,
                    vat_applicable=bool(product.vat_applicable),
                    available_stock=product.stock_quantity,
                )
            )

        priced = price_cart(
            lines,
            discount=cart.discount,
            vat_rate=vat_rate,
            vat_enabled=settings.vat_enabled,
        )

        sales = SaleRepository(session)
        sale = Sale(
            invoice_number=sales.next_invoice_number(),
            sale_date=sale_date or datetime.now(),
            subtotal=priced.subtotal,
            vat_amount=priced.vat,
            discount=priced.discount,
            total=priced.total,
            vat_rate_snapshot=vat_rate,
            item_count=priced.item_count,
            note=(note or "").strip() or None,
        )
        sales.add(sale)

        for line in priced.lines:
            session.add(
                SaleItem(
                    sale_id=sale.id,
                    product_id=line.product_id,
                    product_code_snapshot=line.code,
                    product_name_snapshot=line.name,
                    unit_snapshot=line.unit,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    cost_price_snapshot=line.cost_price,
                    vat_applicable=line.vat_applicable,
                    vat_amount=line.vat_amount,
                    discount_allocated=line.discount_allocated,
                    line_total=line.line_total,
                )
            )
        session.flush()

        for line in priced.lines:
            apply_movement(
                session,
                product=products[line.product_id],
                movement_type="Stock Out",
                reason="Sale",
                quantity=line.quantity,
                direction="out",
                reference=sale.invoice_number,
                notes=f"Sold on invoice {sale.invoice_number}.",
                sale_id=sale.id,
                created_at=sale.sale_date,
            )

        cart.clear()
        logger.info(
            "Sale %s committed: %d lines, total KSh %s",
            sale.invoice_number,
            priced.item_count,
            priced.total,
        )
        return SaleResult(
            sale_id=sale.id,
            invoice_number=sale.invoice_number,
            subtotal=priced.subtotal,
            vat=priced.vat,
            discount=priced.discount,
            total=priced.total,
            vat_rate=vat_rate,
            item_count=priced.item_count,
            total_quantity=priced.total_quantity,
            sale_date=sale.sale_date,
            lines=priced.lines,
        )


def quote_cart(
    cart: Cart,
    *,
    session: Session | None = None,
) -> PricedCart:
    """Price the cart using current database settings (for the live POS panel)."""
    settings = get_settings(session)
    return price_cart(
        [item.to_input() for item in cart.items],
        discount=cart.discount,
        vat_rate=settings.effective_vat_rate,
        vat_enabled=settings.vat_enabled,
    )


def next_invoice_number() -> str:
    """The invoice number the next completed sale will receive (POS header)."""
    with session_scope() as session:
        return SaleRepository(session).next_invoice_number()
