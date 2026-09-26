"""Product master-data tests: categories, validation, updates, archive rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import BusinessRuleError, ValidationError
from services import product_service
from services.product_service import ProductInput


def _input(**overrides) -> ProductInput:
    data = dict(
        code="TEA001",
        name="Tea Leaves 250g",
        category="Groceries",
        unit="Pack",
        cost_price="120",
        selling_price="180",
        stock_quantity=10,
        reorder_level=4,
        vat_applicable=True,
        image_path=None,
    )
    data.update(overrides)
    return ProductInput(**data)


class TestCategories:
    def test_new_category_is_created_and_reused(self):
        first = product_service.create_product(_input())
        second = product_service.create_product(_input(code="TEA002", name="Tea Leaves 500g"))
        assert first.category_name == "Groceries"
        assert second.category_name == "Groceries"
        names = product_service.category_names()
        assert names.count("Groceries") == 1

    def test_category_lookup_is_case_insensitive(self):
        product_service.create_product(_input())
        product_service.create_product(_input(code="TEA002", category="groceries "))
        assert product_service.category_names() == ["Groceries"]


class TestValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"selling_price": "-5"},
            {"cost_price": "-1"},
            {"code": ""},
            {"name": "   "},
            {"stock_quantity": "abc"},
        ],
    )
    def test_bad_fields_are_rejected(self, overrides):
        with pytest.raises(ValidationError):
            product_service.create_product(_input(**overrides))

    def test_all_row_problems_are_reported_together(self):
        with pytest.raises(ValidationError) as info:
            product_service.create_product(_input(code="", selling_price="-5"))
        assert "Product Code" in info.value.detail
        assert "Selling Price" in info.value.detail

    def test_duplicate_code_is_rejected(self, sample_products):
        with pytest.raises(ValidationError):
            product_service.create_product(_input(code="DET001"))

    def test_code_is_normalized(self):
        product = product_service.create_product(_input(code="  tea-009 "))
        assert product.code == "TEA-009"


class TestUpdates:
    def test_update_changes_master_data_but_not_stock(self, sample_products):
        in_stock, _low, _out = sample_products
        product_service.update_product(
            in_stock.id,
            _input(
                code="DET001",
                name="Ariel Detergent 1kg (new pack)",
                category="Detergents",
                unit="Piece",
                cost_price="300",
                selling_price="360",
                stock_quantity=999,
                reorder_level=12,
            ),
        )
        refreshed = product_service.get_product(in_stock.id)
        assert refreshed.name == "Ariel Detergent 1kg (new pack)"
        assert refreshed.selling_price == Decimal("360.00")
        assert refreshed.stock_quantity == 42
        assert refreshed.reorder_level == 12

    def test_update_of_missing_product_is_a_business_error(self):
        with pytest.raises(BusinessRuleError):
            product_service.update_product(9999, _input())


class TestArchiveAndDelete:
    def test_product_with_history_is_archived_not_deleted(self, sample_products):
        from services import pos_service
        from services.pos_service import Cart

        cart = Cart()
        cart.add(sample_products[0], 1)
        pos_service.complete_sale(cart)

        outcome, message = product_service.delete_product(sample_products[0].id)
        assert outcome == "archived"
        assert "archived" in message
        product = product_service.get_product(sample_products[0].id)
        assert product.is_active is False

    def test_product_without_history_is_deleted(self):
        product = product_service.create_product(_input(stock_quantity=0))
        outcome, _message = product_service.delete_product(product.id)
        assert outcome == "deleted"
        assert product_service.get_product(product.id) is None

    def test_archived_products_leave_the_pos_but_stay_listable(self, sample_products):
        product_service.set_active(sample_products[0].id, False)
        codes = [product.code for product in product_service.pos_products()]
        assert "DET001" not in codes
        listed = product_service.list_products(status="Archived", include_inactive=True)
        assert [product.code for product in listed] == ["DET001"]
