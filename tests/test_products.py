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


@pytest.fixture
def hierarchy():
    """Category -> Subcategory -> Brand -> Product Name, as the shop would stock it."""
    rows = (
        ("COF001", "Classic", "Beverages", "Coffee", "Nescafé", "Piece", "480", "570"),
        ("COF002", "Gold", "Beverages", "Coffee", "Nescafé", "Piece", "850", "990"),
        ("COF003", "House Blend", "Beverages", "Coffee", "Dormans", "Pack", "620", "750"),
        ("DET001", "1kg Washing Powder", "Detergents", "Washing Powder", "Ariel", "Piece", "290", "350"),
        ("DET002", "1kg Washing Powder", "Detergents", "Washing Powder", "Omo", "Piece", "260", "320"),
        ("DIS001", "Dishwashing Liquid 750ml", "Detergents", "Dishwashing", "Sunlight", "Bottle", "210", "265"),
    )
    return [
        product_service.create_product(
            _input(code=code, name=name, category=category, subcategory=subcategory,
                   brand=brand, unit=unit, cost_price=cost, selling_price=selling,
                   stock_quantity=10, reorder_level=3)
        )
        for code, name, category, subcategory, brand, unit, cost, selling in rows
    ]


class TestHierarchy:
    def test_category_only_product_has_no_other_levels(self):
        product = product_service.create_product(_input())
        assert product.category_name == "Groceries"
        assert product.subcategory is None
        assert product.brand is None
        assert product.classification == "Groceries"

    def test_subcategory_alone_is_stored(self):
        product = product_service.create_product(_input(subcategory="Tea Leaves"))
        assert product.subcategory == "Tea Leaves"
        assert product.brand is None
        assert product.classification == "Groceries > Tea Leaves"

    def test_full_hierarchy_is_stored(self):
        product = product_service.create_product(
            _input(code="COF001", name="Classic", category="Beverages",
                   subcategory="Coffee", brand="Nescafé")
        )
        assert product.category_name == "Beverages"
        assert product.subcategory == "Coffee"
        assert product.brand == "Nescafé"
        assert product.classification == "Beverages > Coffee > Nescafé"

    def test_blank_levels_are_normalized_to_none(self):
        product = product_service.create_product(_input(subcategory="   ", brand=""))
        assert product.subcategory is None and product.brand is None

    def test_level_text_is_collapsed_not_rewritten(self):
        product = product_service.create_product(_input(subcategory=" washing  powder ", brand=" ariel "))
        assert (product.subcategory, product.brand) == ("washing powder", "ariel")

    def test_overlong_levels_are_rejected(self):
        with pytest.raises(ValidationError):
            product_service.create_product(_input(subcategory="x" * 121))
        with pytest.raises(ValidationError):
            product_service.create_product(_input(brand="y" * 121))

    def test_several_brands_share_one_subcategory(self, hierarchy):
        assert product_service.subcategory_names() == ["Coffee", "Dishwashing", "Washing Powder"]
        assert product_service.brand_names(subcategory="Coffee") == ["Dormans", "Nescafé"]
        assert product_service.brand_names(subcategory="Washing Powder") == ["Ariel", "Omo"]

    def test_several_products_share_one_brand(self, hierarchy):
        nescafe = product_service.list_products(brand="Nescafé")
        assert [product.code for product in nescafe] == ["COF001", "COF002"]
        assert {product.name for product in nescafe} == {"Classic", "Gold"}

    def test_the_same_name_can_exist_under_different_brands(self, hierarchy):
        powders = product_service.list_products(subcategory="Washing Powder")
        assert [product.code for product in powders] == ["DET001", "DET002"]
        assert [product.brand for product in powders] == ["Ariel", "Omo"]

    def test_filters_narrow_one_level_at_a_time(self, hierarchy):
        beverages = [category for category in product_service.list_categories()
                     if category.name == "Beverages"][0]

        assert len(product_service.list_products(category_id=beverages.id)) == 3
        assert len(product_service.list_products(category_id=beverages.id, subcategory="Coffee")) == 3
        assert len(product_service.list_products(category_id=beverages.id, brand="Nescafé")) == 2
        assert len(product_service.list_products(subcategory="Dishwashing")) == 1
        # Brand matching is case-insensitive, like the rest of the catalogue.
        assert len(product_service.list_products(brand="  nescafé ")) == 2

    def test_search_finds_code_name_brand_category_and_subcategory(self, hierarchy):
        assert [p.code for p in product_service.list_products(search="COF002")] == ["COF002"]
        assert [p.code for p in product_service.list_products(search="House Blend")] == ["COF003"]
        assert [p.code for p in product_service.list_products(search="Dormans")] == ["COF003"]
        assert [p.code for p in product_service.list_products(search="dishwashing")] == ["DIS001"]
        assert len(product_service.list_products(search="Detergents")) == 3

    def test_existing_products_without_levels_stay_readable(self, sample_products):
        products = product_service.list_products()
        assert [product.subcategory for product in products] == [None, None, None]
        assert [product.brand for product in products] == [None, None, None]
        # They group under a blank level rather than being dropped or guessed at.
        assert sorted(product_service.catalogue_hierarchy()) == ["Detergents", "Hardware", "Household"]
        assert list(product_service.catalogue_hierarchy()["Detergents"]) == [""]

    def test_hierarchy_groups_category_subcategory_brand(self, hierarchy):
        tree = product_service.catalogue_hierarchy()
        assert sorted(tree) == ["Beverages", "Detergents"]
        assert sorted(tree["Beverages"]) == ["Coffee"]
        assert sorted(tree["Beverages"]["Coffee"]) == ["Dormans", "Nescafé"]
        assert [p.code for p in tree["Beverages"]["Coffee"]["Nescafé"]] == ["COF001", "COF002"]
        assert sorted(tree["Detergents"]) == ["Dishwashing", "Washing Powder"]
        assert [p.code for p in tree["Detergents"]["Washing Powder"]["Ariel"]] == ["DET001"]

        rows = product_service.hierarchy_rows()
        assert len(rows) == 6
        assert rows[0]["category"] == "Beverages"
        assert {row["brand"] for row in rows} == {"Nescafé", "Dormans", "Ariel", "Omo", "Sunlight"}

    def test_updating_a_product_can_clear_a_level(self, hierarchy):
        product = product_service.find_by_code("COF001")
        product_service.update_product(
            product.id,
            _input(code="COF001", name="Classic", category="Beverages", subcategory="Coffee",
                   brand="", unit="Piece", cost_price="480", selling_price="570"),
        )
        refreshed = product_service.find_by_code("COF001")
        assert refreshed.brand is None
        assert refreshed.subcategory == "Coffee"
        # Gold is still a Nescafé product, so the brand stays on offer.
        assert product_service.brand_names(subcategory="Coffee") == ["Dormans", "Nescafé"]
        assert [p.code for p in product_service.list_products(brand="Nescafé")] == ["COF002"]
