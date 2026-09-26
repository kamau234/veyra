"""The single source of truth for sale pricing.

VEYRA Version 1 pricing rule (blueprint 14.3 - 14.7), applied identically by
the POS live totals, the Complete Sale transaction, receipts and reports:

1. ``line_total = quantity x unit_selling_price``. Selling prices are treated
   as VAT-exclusive; VAT is added on top.
2. A sale-level discount is a fixed KSh amount, validated to
   ``0 <= discount <= subtotal``.
3. The discount is allocated across lines pro-rata by ``line_total`` so each
   line knows its own share. Rounding is to the cent and the residual cent(s)
   are pushed onto the last line, guaranteeing the allocated parts sum exactly
   to the discount.
4. VAT is computed per line, only for lines flagged VAT-applicable, on the
   line amount *after* that line's discount allocation:
   ``vat = (line_total - discount_allocated) x vat_rate / 100``.
5. ``total = subtotal + vat - discount``.

Every result is a 2dp Decimal. Historical sales store the amounts they were
priced with, so changing the VAT rate later never rewrites them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from core.exceptions import BusinessRuleError
from core.money import ZERO, round_money, to_money

HUNDRED = Decimal("100")


@dataclass(frozen=True)
class CartLineInput:
    """What the UI hands to the pricing engine for one cart row."""

    product_id: int
    code: str
    name: str
    quantity: int
    unit_price: Decimal
    cost_price: Decimal = ZERO
    unit: str = "Piece"
    vat_applicable: bool = True
    available_stock: int | None = None


@dataclass(frozen=True)
class PricedLine:
    product_id: int
    code: str
    name: str
    unit: str
    quantity: int
    unit_price: Decimal
    cost_price: Decimal
    vat_applicable: bool
    line_total: Decimal
    discount_allocated: Decimal
    vat_amount: Decimal

    @property
    def payable(self) -> Decimal:
        """Line total plus its VAT, less its share of the discount."""
        return round_money(self.line_total + self.vat_amount - self.discount_allocated)

    @property
    def estimated_cost(self) -> Decimal:
        return round_money(to_money(self.cost_price) * self.quantity)

    @property
    def gross_profit(self) -> Decimal:
        return round_money(self.line_total - self.estimated_cost)


@dataclass(frozen=True)
class PricedCart:
    lines: list[PricedLine] = field(default_factory=list)
    subtotal: Decimal = ZERO
    discount: Decimal = ZERO
    vat: Decimal = ZERO
    total: Decimal = ZERO
    vat_rate: Decimal = ZERO
    vat_enabled: bool = True

    @property
    def item_count(self) -> int:
        return len(self.lines)

    @property
    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    def line_for(self, product_id: int) -> PricedLine | None:
        return next((line for line in self.lines if line.product_id == product_id), None)


def line_total(quantity: int, unit_price: Decimal) -> Decimal:
    """Blueprint 14.3."""
    return round_money(to_money(unit_price) * Decimal(int(quantity)))


def allocate_discount(amounts: list[Decimal], discount: Decimal) -> list[Decimal]:
    """Split a sale-level discount pro-rata, absorbing rounding on the last line."""
    base = round_money(discount)
    if base <= 0 or not amounts:
        return [ZERO] * len(amounts)

    pool = sum(amounts) or ZERO
    if pool <= 0:
        return [ZERO] * len(amounts)

    shares: list[Decimal] = []
    allocated = ZERO
    for index, amount in enumerate(amounts):
        if index == len(amounts) - 1:
            shares.append(round_money(base - allocated))
        else:
            share = round_money(base * amount / pool)
            shares.append(share)
            allocated += share
    return shares


def validate_discount(discount: Decimal, subtotal: Decimal) -> Decimal:
    value = to_money(discount)
    if value < 0:
        raise BusinessRuleError("Discount cannot be negative.")
    if value > subtotal:
        raise BusinessRuleError(
            f"Discount cannot be greater than the subtotal of KSh {subtotal:,.2f}."
        )
    return value


def validate_vat_rate(rate: Decimal) -> Decimal:
    value = to_money(rate)
    if value < 0 or value > 100:
        raise BusinessRuleError("VAT rate must be between 0 and 100.")
    return value


def price_cart(
    cart_lines: list[CartLineInput],
    *,
    discount: Decimal = ZERO,
    vat_rate: Decimal = ZERO,
    vat_enabled: bool = True,
) -> PricedCart:
    """Price a whole cart. Pure function — no database access."""
    if not cart_lines:
        return PricedCart(vat_rate=to_money(vat_rate), vat_enabled=vat_enabled)

    rate = validate_vat_rate(vat_rate) if vat_enabled else ZERO
    lines: list[PricedLine] = []
    totals: list[Decimal] = []

    for item in cart_lines:
        quantity = int(item.quantity)
        if quantity <= 0:
            raise BusinessRuleError(f"Quantity for {item.name} must be greater than zero.")
        amount = line_total(quantity, item.unit_price)
        totals.append(amount)
        lines.append(
            PricedLine(
                product_id=item.product_id,
                code=item.code,
                name=item.name,
                unit=item.unit,
                quantity=quantity,
                unit_price=to_money(item.unit_price),
                cost_price=to_money(item.cost_price),
                vat_applicable=bool(item.vat_applicable),
                line_total=amount,
                discount_allocated=ZERO,
                vat_amount=ZERO,
            )
        )

    subtotal = round_money(sum(totals))
    discount_value = validate_discount(to_money(discount), subtotal)
    shares = allocate_discount(totals, discount_value)

    vat_total = ZERO
    priced: list[PricedLine] = []
    for line, share in zip(lines, shares):
        taxable = round_money(line.line_total - share) if line.vat_applicable else ZERO
        amount = round_money(taxable * rate / HUNDRED) if rate > 0 else ZERO
        vat_total += amount
        priced.append(
            PricedLine(
                product_id=line.product_id,
                code=line.code,
                name=line.name,
                unit=line.unit,
                quantity=line.quantity,
                unit_price=line.unit_price,
                cost_price=line.cost_price,
                vat_applicable=line.vat_applicable,
                line_total=line.line_total,
                discount_allocated=share,
                vat_amount=amount,
            )
        )

    vat_total = round_money(vat_total)
    total = round_money(subtotal + vat_total - discount_value)

    return PricedCart(
        lines=priced,
        subtotal=subtotal,
        discount=discount_value,
        vat=vat_total,
        total=total,
        vat_rate=rate,
        vat_enabled=vat_enabled,
    )
