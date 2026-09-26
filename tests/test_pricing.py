"""Money, pricing and stock-status rules (blueprint 14, 21.2)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import BusinessRuleError
from core.money import to_int, to_money
from services.pricing import CartLineInput, allocate_discount, line_total, price_cart


def blueprint_lines() -> list[CartLineInput]:
    return [
        CartLineInput(1, "DET001", "Ariel Detergent 1kg", 2, Decimal("350"), Decimal("290")),
        CartLineInput(2, "SP001", "Soap", 3, Decimal("250"), Decimal("180")),
        CartLineInput(3, "HM001", "Hammer", 1, Decimal("950"), Decimal("700")),
    ]


class TestMoney:
    def test_rounds_half_up_to_two_places(self):
        assert to_money("291.555") == Decimal("291.56")
        assert to_money(Decimal("0.005")) == Decimal("0.01")

    def test_strips_currency_text(self):
        assert to_money("KSh 1,234.50") == Decimal("1234.50")

    def test_rejects_non_numeric(self):
        with pytest.raises(ValueError):
            to_money("abc")

    def test_quantity_must_be_a_non_negative_whole_number(self):
        assert to_int("12", field="Quantity") == 12
        with pytest.raises(ValueError):
            to_int(-1, field="Quantity")
        with pytest.raises(ValueError):
            to_int(1.5, field="Quantity")


class TestPricing:
    def test_blueprint_sale_example(self):
        """Blueprint 21.2: subtotal 2,400 / VAT 384 / total 2,784."""
        cart = price_cart(blueprint_lines(), vat_rate=Decimal("16"), vat_enabled=True)
        assert cart.subtotal == Decimal("2400.00")
        assert cart.vat == Decimal("384.00")
        assert cart.discount == Decimal("0.00")
        assert cart.total == Decimal("2784.00")
        assert cart.total_quantity == 6
        assert cart.item_count == 3

    def test_line_total_is_quantity_times_unit_price(self):
        assert line_total(3, Decimal("250")) == Decimal("750.00")

    def test_total_formula_holds_with_a_discount(self):
        cart = price_cart(blueprint_lines(), discount=Decimal("100"), vat_rate=Decimal("16"))
        assert cart.total == cart.subtotal + cart.vat - cart.discount
        assert sum(line.discount_allocated for line in cart.lines) == Decimal("100.00")

    def test_vat_only_applies_to_flagged_lines(self):
        lines = [
            CartLineInput(1, "A", "Bread", 1, Decimal("100"), vat_applicable=False),
            CartLineInput(2, "B", "Soap", 1, Decimal("100"), vat_applicable=True),
        ]
        cart = price_cart(lines, vat_rate=Decimal("16"))
        assert cart.vat == Decimal("16.00")
        assert cart.total == Decimal("216.00")

    def test_disabling_vat_zeroes_the_rate(self):
        cart = price_cart(blueprint_lines(), vat_rate=Decimal("16"), vat_enabled=False)
        assert cart.vat == Decimal("0.00")
        assert cart.total == cart.subtotal

    def test_vat_is_calculated_after_discount_allocation(self):
        lines = [CartLineInput(1, "A", "Soap", 1, Decimal("1000"), vat_applicable=True)]
        cart = price_cart(lines, discount=Decimal("500"), vat_rate=Decimal("16"))
        assert cart.vat == Decimal("80.00")  # 16% of 500, not of 1000
        assert cart.total == Decimal("580.00")

    def test_discount_cannot_exceed_subtotal(self):
        with pytest.raises(BusinessRuleError):
            price_cart(blueprint_lines(), discount=Decimal("99999"))

    def test_negative_discount_rejected(self):
        with pytest.raises(BusinessRuleError):
            price_cart(blueprint_lines(), discount=Decimal("-5"))

    def test_zero_quantity_rejected(self):
        lines = [CartLineInput(1, "A", "Soap", 0, Decimal("100"))]
        with pytest.raises(BusinessRuleError):
            price_cart(lines)

    def test_empty_cart_prices_to_zero(self):
        cart = price_cart([])
        assert cart.is_empty
        assert cart.total == Decimal("0.00")

    @pytest.mark.parametrize(
        "amounts,discount",
        [
            ([Decimal("0.01"), Decimal("0.01"), Decimal("0.01")], Decimal("0.02")),
            ([Decimal("10.00"), Decimal("20.00"), Decimal("30.00")], Decimal("7.77")),
            ([Decimal("333.33")], Decimal("333.33")),
        ],
    )
    def test_allocation_always_sums_exactly_to_the_discount(self, amounts, discount):
        shares = allocate_discount(amounts, discount)
        assert sum(shares) == discount
        assert all(share >= 0 for share in shares)
        assert all(share <= amount for share, amount in zip(shares, amounts))

    def test_gross_profit_uses_the_line_cost(self):
        cart = price_cart(blueprint_lines(), vat_rate=Decimal("16"))
        ariel = cart.line_for(1)
        assert ariel.estimated_cost == Decimal("580.00")
        assert ariel.gross_profit == Decimal("120.00")


class TestStockStatus:
    def test_status_formula(self, sample_products):
        in_stock, low_stock, out_of_stock = sample_products
        assert in_stock.stock_status == "In Stock"
        assert low_stock.stock_status == "Low Stock"
        assert out_of_stock.stock_status == "Out of Stock"

    def test_stock_equal_to_reorder_level_is_low(self, sample_products):
        from services import product_service

        in_stock, _, _ = sample_products
        product_service.update_product(
            in_stock.id,
            product_service.ProductInput(
                code=in_stock.code,
                name=in_stock.name,
                category="Detergents",
                cost_price=in_stock.cost_price,
                selling_price=in_stock.selling_price,
                reorder_level=42,
            ),
        )
        assert product_service.get_product(in_stock.id).stock_status == "Low Stock"

    def test_stock_value_is_quantity_times_cost(self, sample_products):
        from services import inventory_service

        summary = inventory_service.summary()
        # 42 x 290 + 4 x 180 + 0 x 700
        assert summary.stock_value == Decimal("12900.00")
        assert summary.total_units == 46
        assert summary.low_stock == 1
        assert summary.out_of_stock == 1
