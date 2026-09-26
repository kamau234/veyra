"""Settings, VAT history and backup/restore tests (blueprint 12 and section 22)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.exceptions import FileError, ValidationError
from core.paths import BACKUP_DIR
from services import backup_service, pos_service, product_service, settings_service
from services.pos_service import Cart


def _sell(code: str, quantity: int = 1):
    cart = Cart()
    cart.add(product_service.find_by_code(code), quantity)
    return pos_service.complete_sale(cart)


class TestTaxSettings:
    def test_changing_the_rate_does_not_rewrite_history(self, sample_products):
        first = _sell("DET001")
        assert first.vat == Decimal("56.00")  # 350 x 16%

        settings_service.update_tax_settings(vat_enabled=True, vat_rate=Decimal("18"))
        second = _sell("DET001")

        from services import reporting_service

        old = reporting_service.get_sale(first.sale_id)
        assert old.vat_amount == Decimal("56.00")
        assert old.vat_rate_snapshot == Decimal("16.00")
        assert second.vat == Decimal("63.00")
        assert settings_service.get_settings().vat_label == "VAT (18%)"

    def test_disabling_vat_removes_it_from_new_sales(self, sample_products):
        settings_service.update_tax_settings(vat_enabled=False, vat_rate=Decimal("16"))
        result = _sell("DET001")
        assert result.vat == Decimal("0.00")
        assert result.total == Decimal("350.00")
        assert settings_service.get_settings().vat_label == "VAT (off)"

    def test_rate_out_of_range_is_rejected(self):
        with pytest.raises(ValidationError):
            settings_service.update_tax_settings(vat_enabled=True, vat_rate=Decimal("140"))


class TestBusinessProfile:
    def test_name_is_required_and_email_is_checked(self):
        with pytest.raises(ValidationError):
            settings_service.update_business_profile(business_name="   ")
        with pytest.raises(ValidationError):
            settings_service.update_business_profile(
                business_name="Shop", email="not-an-email"
            )

    def test_profile_roundtrip_and_image_clearing(self):
        settings_service.update_business_profile(
            business_name="Njeri General Stores",
            owner_name="Mary Njeri",
            phone="0712 345 678",
            address="Kiambu Road",
        )
        snapshot = settings_service.get_settings()
        assert snapshot.business_name == "Njeri General Stores"
        assert snapshot.owner_name == "Mary Njeri"
        assert snapshot.setup_complete is True

        settings_service.update_business_profile(business_name="Shop", logo_image="")
        assert settings_service.get_settings().logo_image is None

    def test_appearance_rejects_unknown_values(self):
        with pytest.raises(ValidationError):
            settings_service.update_appearance(theme="Neon", font_size="Normal")
        with pytest.raises(ValidationError):
            settings_service.update_appearance(theme="Light", font_size="Huge")
        snapshot = settings_service.update_appearance(theme="dark", font_size="large")
        assert snapshot.theme == "Dark"
        assert snapshot.font_size == "Large"


class TestBackupRestore:
    def test_backup_creates_a_timestamped_copy(self, sample_products):
        info = backup_service.create_backup()
        assert info.path.parent == BACKUP_DIR
        assert info.path.exists()
        assert info.size_bytes > 0
        assert backup_service.list_backups()[0].path == info.path

    def test_restore_brings_back_deleted_data(self, sample_products):
        _sell("DET001", 2)
        product_service.create_product(
            product_service.ProductInput(
                code="NEW001",
                name="Spare Product",
                category="Hardware",
                unit="Piece",
                cost_price="10",
                selling_price="20",
                stock_quantity=0,
                reorder_level=1,
                vat_applicable=True,
            )
        )
        backup = backup_service.create_backup()

        outcome, _message = product_service.delete_product(
            product_service.find_by_code("NEW001").id
        )
        assert outcome == "deleted"
        assert product_service.find_by_code("NEW001") is None

        safety, destination = backup_service.restore_backup(backup.path)
        assert destination.exists()
        assert safety is not None and safety.name.startswith("veyra-pre-restore-")

        restored = product_service.find_by_code("NEW001")
        assert restored is not None
        from services import reporting_service

        sales, totals, _label = reporting_service.list_sales()
        assert totals["invoices"] == 1
        assert sales[0].invoice_number == "INV-00001"

    def test_restore_rejects_a_file_that_is_not_a_database(self, tmp_path):
        fake = tmp_path / "notes.db"
        fake.write_text("hello, not a database")
        with pytest.raises(FileError):
            backup_service.restore_backup(fake)

    def test_restore_rejects_a_database_without_veyra_tables(self, tmp_path):
        import sqlite3

        foreign = tmp_path / "other.db"
        connection = sqlite3.connect(str(foreign))
        connection.execute("CREATE TABLE notes (id INTEGER)")
        connection.commit()
        connection.close()
        with pytest.raises(FileError):
            backup_service.restore_backup(foreign)

    def test_missing_backup_file_is_reported(self):
        with pytest.raises(FileError):
            backup_service.restore_backup(BACKUP_DIR / "nope.db")
