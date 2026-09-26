"""POS and sale-completion tests (blueprint 9 and section 22)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import BusinessRuleError, DatabaseError, ValidationError
from models import Product, Sale, SaleItem, StockMovement
from services import inventory_service, pos_service, product_service
from services.pos_service import Cart


def _cart_with(*pairs) -> Cart:
    cart = Cart()
    for code, quantity in pairs:
        cart.add(product_service.find_by_code(code), quantity)
    return cart


class TestCartRules:
    def test_adding_the_same_product_merges_the_line(self, sample_products):
        in_stock, _low, _out = sample_products
        cart = Cart()
        cart.add(in_stock, 2)
        cart.add(in_stock, 3)
        assert len(cart.items) == 1
        assert cart.quantity_of(in_stock.id) == 5

    def test_cart_quantity_cannot_exceed_stock(self, sample_products):
        in_stock, _low, _out = sample_products
        cart = Cart()
        cart.add(in_stock, 40)
        with pytest.raises(BusinessRuleError):
            cart.add(in_stock, 3)
        with pytest.raises(BusinessRuleError):
            cart.set_quantity(in_stock.id, 43)

    def test_out_of_stock_products_cannot_be_sold(self, sample_products):
        _in_stock, _low, out_of_stock = sample_products
        cart = Cart()
        with pytest.raises(BusinessRuleError):
            cart.add(out_of_stock, 1)

    def test_zero_and_negative_quantities_are_rejected(self, sample_products):
        in_stock, _low, _out = sample_products
        cart = Cart()
        with pytest.raises(ValidationError):
            cart.add(in_stock, 0)
        with pytest.raises(ValidationError):
            cart.set_discount(-1)

    def test_discount_larger_than_subtotal_is_rejected(self, sample_products):
        cart = _cart_with(("DET001", 1))
        cart.set_discount(Decimal("999999"))
        with pytest.raises(BusinessRuleError):
            cart.price(vat_rate=Decimal("16"), vat_enabled=True)


class TestCompleteSale:
    def test_sale_writes_snapshots_movements_and_stock(self, sample_products):
        in_stock, _low, _out = sample_products
        cart = _cart_with(("DET001", 2), ("SP001", 1))
        result = pos_service.complete_sale(cart, note="Counter sale")

        assert result.invoice_number == "INV-00001"
        assert result.subtotal == Decimal("950.00")
        assert result.vat == Decimal("152.00")
        assert result.total == Decimal("1102.00")
        assert result.message == "Sale INV-00001 completed — KSh 1,102.00"

        from services import reporting_service

        sale = reporting_service.get_sale(result.sale_id)
        assert sale.note == "Counter sale"
        assert sale.item_count == 2
        assert [item.product_code_snapshot for item in sale.items] == ["DET001", "SP001"]
        assert [item.quantity for item in sale.items] == [2, 1]
        hammer_line = [line for line in result.lines if line.code == "SP001"][0]
        assert hammer_line.vat_amount == Decimal("40.00")
        assert cart.is_empty

    def test_sale_totals_match_the_pricing_engine(self, sample_products):
        cart = _cart_with(("DET001", 2), ("SP001", 1))
        priced = cart.price(vat_rate=Decimal("16"), vat_enabled=True)
        result = pos_service.complete_sale(cart)
        assert (result.subtotal, result.vat, result.discount, result.total) == (
            priced.subtotal,
            priced.vat,
            priced.discount,
            priced.total,
        )

    def test_stock_falls_and_movements_reference_the_invoice(self, sample_products):
        in_stock, low, _out = sample_products
        pos_service.complete_sale(_cart_with(("DET001", 2), ("SP001", 1)))

        assert product_service.get_product(in_stock.id).stock_quantity == 40
        assert product_service.get_product(low.id).stock_quantity == 3

        movements = inventory_service.list_movements(movement_type="Stock Out")
        assert len(movements) == 2
        for movement in movements:
            assert movement.reason == "Sale"
            assert movement.reference == "INV-00001"
            assert movement.direction == "out"

    def test_invoice_numbers_increment(self, sample_products):
        pos_service.complete_sale(_cart_with(("DET001", 1)))
        second = pos_service.complete_sale(_cart_with(("DET001", 1)))
        assert second.invoice_number == "INV-00002"
        assert pos_service.next_invoice_number() == "INV-00003"

    def test_empty_cart_is_rejected(self):
        with pytest.raises(BusinessRuleError):
            pos_service.complete_sale(Cart())

    def test_stale_cart_quantity_is_rejected_without_changing_stock(self, sample_products):
        in_stock, _low, _out = sample_products
        cart = _cart_with(("DET001", 40))
        inventory_service.record_movement(
            product_id=in_stock.id,
            movement_type="Stock Out",
            reason="Damaged",
            quantity=39,
        )
        with pytest.raises(BusinessRuleError):
            pos_service.complete_sale(cart)
        assert product_service.get_product(in_stock.id).stock_quantity == 3

    def test_failure_mid_transaction_changes_nothing(self, sample_products, monkeypatch):
        in_stock, _low, _out = sample_products
        cart = _cart_with(("DET001", 2))

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(pos_service, "apply_movement", boom)
        with pytest.raises(DatabaseError):
            pos_service.complete_sale(cart)

        from db.session import session_scope

        with session_scope() as session:
            assert session.query(Sale).count() == 0
            assert session.query(SaleItem).count() == 0
            assert (
                session.query(StockMovement)
                .filter(StockMovement.reason == "Sale")
                .count()
                == 0
            )
            assert session.get(Product, in_stock.id).stock_quantity == 42
        assert cart.quantity_of(in_stock.id) == 2

    def test_sale_items_keep_their_prices_after_a_price_edit(self, sample_products):
        in_stock, _low, _out = sample_products
        result = pos_service.complete_sale(_cart_with(("DET001", 1)))
        product_service.update_product(
            in_stock.id,
            product_service.ProductInput(
                code="DET001",
                name="Ariel Detergent 1kg",
                category="Detergents",
                unit="Piece",
                cost_price="400",
                selling_price="500",
                stock_quantity=41,
                reorder_level=10,
                vat_applicable=True,
            ),
        )
        from services import reporting_service

        sale = reporting_service.get_sale(result.sale_id)
        item = sale.items[0]
        assert item.unit_price == Decimal("350.00")
        assert item.cost_price_snapshot == Decimal("290.00")
        assert sale.total == Decimal("406.00")

    def test_archived_products_cannot_be_sold(self, sample_products):
        in_stock, _low, _out = sample_products
        cart = _cart_with(("DET001", 1))
        product_service.set_active(in_stock.id, False)
        with pytest.raises(BusinessRuleError):
            pos_service.complete_sale(cart)
