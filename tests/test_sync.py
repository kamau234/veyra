"""Cloud sync tests against an in-memory fake of the Supabase table.

No network is touched: ``sync_service._request`` is replaced with a stub that
behaves like PostgREST (upsert on POST, list on GET). The tests prove the
snapshot round-trips losslessly and that a restore can never silently destroy
local data (blueprint 16: no false success).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import ValidationError
from services import pos_service, product_service, settings_service, sync_service
from services.pos_service import Cart


class FakeServer:
    """Minimal stand-in for ``public.veyra_sync``."""

    def __init__(self):
        self.rows: dict[str, dict] = {}

    def __call__(self, method, path, *, body=None, params=""):
        if method == "POST":
            self.rows[body["shop_id"]] = body
            return None
        row = self.rows.get(sync_service.shop_id())
        if row is None:
            return []
        return [{"payload": row["payload"], "schema_version": row["schema_version"]}]


@pytest.fixture
def server(monkeypatch):
    fake = FakeServer()
    monkeypatch.setattr(sync_service, "_request", fake)
    return fake


def _seed_sale():
    cart = Cart()
    cart.add(product_service.find_by_code("DET001"), 2)
    return pos_service.complete_sale(cart, note="sync seed")


def test_commit_marks_the_cloud_copy_stale(sample_products):
    assert sync_service.consume_dirty() is True


def test_push_uploads_a_complete_snapshot(server, sample_products):
    settings_service.update_business_profile(
        business_name="Njeri General Stores", owner_name="Mary Njeri"
    )
    _seed_sale()

    result = sync_service.push()

    assert result.ok is True
    assert result.products == 3
    assert result.sales == 1
    payload = server.rows[sync_service.shop_id()]["payload"]
    assert payload["settings"]["business_name"] == "Njeri General Stores"
    assert payload["sales"][0]["invoice_number"] == "INV-00001"
    assert payload["sales"][0]["items"][0]["product_code"] == "DET001"
    codes = {entry["code"] for entry in payload["products"]}
    assert codes == {"DET001", "SP001", "HM001"}
    movements = [m for m in payload["movements"] if m["reason"] == "Sale"]
    assert len(movements) == 1


def test_restore_rebuilds_catalogue_sales_and_profile(server, sample_products):
    settings_service.update_business_profile(
        business_name="Njeri General Stores", phone="0712 345 678"
    )
    _seed_sale()
    sync_service.push()
    payload = server.rows[sync_service.shop_id()]["payload"]

    with pytest.raises(ValidationError):
        sync_service.restore_payload(payload)  # local data present, no consent

    result = sync_service.restore_payload(payload, allow_overwrite=True)

    assert result.ok is True
    assert product_service.find_by_code("DET001").stock_quantity == 40
    assert product_service.find_by_code("HM001").stock_quantity == 0
    sale = pos_service.next_invoice_number()
    assert sale == "INV-00002"  # the restored ledger kept its invoice number
    settings = settings_service.get_settings()
    assert settings.business_name == "Njeri General Stores"
    assert settings.phone == "0712 345 678"
    assert settings.vat_rate == Decimal("16.00")


def test_restore_onto_an_empty_shop_needs_no_consent(server, sample_products):
    _seed_sale()
    sync_service.push()
    payload = server.rows[sync_service.shop_id()]["payload"]

    # A brand-new install has no products and no sales.
    from db.session import session_scope
    from models import Category, Product, Sale, SaleItem, StockMovement
    from sqlalchemy import delete

    with session_scope() as session:
        session.execute(delete(SaleItem))
        session.execute(delete(StockMovement))
        session.execute(delete(Sale))
        session.execute(delete(Product))
        session.execute(delete(Category))

    result = sync_service.restore_payload(payload)
    assert result.ok is True
    assert len(product_service.list_products(include_inactive=True)) == 3


def test_pull_without_a_cloud_copy_reports_honestly(server, sample_products):
    result = sync_service.pull_and_restore()
    assert result.ok is False
    assert "no copy" in result.message


def test_hierarchy_levels_survive_a_sync_round_trip(server, sample_products):
    product = product_service.find_by_code("DET001")
    product_service.update_product(
        product.id,
        product_service.ProductInput(
            code="DET001",
            name="1kg Washing Powder",
            category="Detergents",
            subcategory="Washing Powder",
            brand="Ariel",
            unit="Piece",
            cost_price="290",
            selling_price="350",
            reorder_level=10,
            vat_applicable=True,
        ),
    )
    sync_service.push()
    payload = server.rows[sync_service.shop_id()]["payload"]
    entry = next(item for item in payload["products"] if item["code"] == "DET001")
    assert (entry["subcategory"], entry["brand"]) == ("Washing Powder", "Ariel")

    sync_service.restore_payload(payload, allow_overwrite=True)

    restored = product_service.find_by_code("DET001")
    assert (restored.subcategory, restored.brand) == ("Washing Powder", "Ariel")
    assert restored.name == "1kg Washing Powder"
    # SP001 carries no levels in the snapshot, so the restore must not invent any.
    assert product_service.find_by_code("SP001").subcategory is None
    assert product_service.find_by_code("SP001").brand is None


def test_probe_reports_a_missing_table(server, monkeypatch, sample_products):
    def refuse(method, path, *, body=None, params=""):
        raise sync_service.SyncError(sync_service.SCHEMA_HINT)

    monkeypatch.setattr(sync_service, "_request", refuse)
    result = sync_service.probe()
    assert result.ok is False
    assert "schema.sql" in result.message
    assert sync_service.load_state().ok is False


def test_sync_id_can_be_moved_to_another_computer(tmp_path, monkeypatch):
    target = tmp_path / "sync_id.txt"
    monkeypatch.setattr(sync_service, "SYNC_ID_FILE", target)
    with pytest.raises(ValidationError):
        sync_service.set_shop_id("ab")
    sync_service.set_shop_id("shop1234567890")
    assert sync_service.shop_id() == "shop1234567890"
