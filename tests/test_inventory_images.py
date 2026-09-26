"""Inventory movement rules and image handling tests (blueprint 7, 6.7, 22)."""

from __future__ import annotations

import pytest

from core.constants import REASONS_BY_TYPE, MovementType, Reason
from core.exceptions import BusinessRuleError, ImageError, ValidationError
from services import image_service, inventory_service, product_service


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class TestMovements:
    def test_restock_increases_stock_and_writes_the_ledger(self, sample_products):
        in_stock, _low, _out = sample_products
        result = inventory_service.record_movement(
            product_id=in_stock.id,
            movement_type=MovementType.STOCK_IN,
            reason=Reason.RESTOCK,
            quantity=8,
            reference="GRN-12",
        )
        assert result.new_stock == 50
        assert result.direction == "in"
        assert result.previous_stock == 42

    @pytest.mark.parametrize("reason", REASONS_BY_TYPE[MovementType.STOCK_OUT])
    def test_every_stock_out_reason_is_accepted(self, sample_products, reason):
        in_stock, _low, _out = sample_products
        notes = "counted again" if reason == Reason.CORRECTION else None
        result = inventory_service.record_movement(
            product_id=in_stock.id,
            movement_type=MovementType.STOCK_OUT,
            reason=reason,
            quantity=1,
            notes=notes,
        )
        assert result.direction == "out"
        assert result.new_stock == 41

    def test_correction_requires_a_note(self, sample_products):
        in_stock, _low, _out = sample_products
        with pytest.raises(ValidationError):
            inventory_service.record_movement(
                product_id=in_stock.id,
                movement_type=MovementType.ADJUSTMENT,
                reason=Reason.CORRECTION,
                quantity=1,
                direction="out",
            )

    def test_adjustment_can_move_either_way(self, sample_products):
        in_stock, _low, _out = sample_products
        down = inventory_service.record_movement(
            product_id=in_stock.id,
            movement_type=MovementType.ADJUSTMENT,
            reason=Reason.OTHER,
            quantity=2,
            direction="out",
            notes="shelf count",
        )
        up = inventory_service.record_movement(
            product_id=in_stock.id,
            movement_type=MovementType.ADJUSTMENT,
            reason=Reason.OTHER,
            quantity=5,
            direction="in",
            notes="found in store room",
        )
        assert down.new_stock == 40
        assert up.new_stock == 45

    def test_stock_cannot_go_negative(self, sample_products):
        _in_stock, low, _out = sample_products
        with pytest.raises(BusinessRuleError):
            inventory_service.record_movement(
                product_id=low.id,
                movement_type=MovementType.STOCK_OUT,
                reason=Reason.DAMAGED,
                quantity=5,
            )
        assert product_service.get_product(low.id).stock_quantity == 4

    def test_out_of_stock_product_can_be_restocked_to_zero_then_sold_never(
        self, sample_products
    ):
        _in_stock, _low, out_of_stock = sample_products
        result = inventory_service.record_movement(
            product_id=out_of_stock.id,
            movement_type=MovementType.STOCK_IN,
            reason=Reason.RESTOCK,
            quantity=3,
        )
        assert result.new_stock == 3

    def test_archived_products_cannot_be_moved(self, sample_products):
        in_stock, _low, _out = sample_products
        product_service.set_active(in_stock.id, False)
        with pytest.raises(BusinessRuleError):
            inventory_service.record_movement(
                product_id=in_stock.id,
                movement_type=MovementType.STOCK_IN,
                reason=Reason.RESTOCK,
                quantity=1,
            )

    def test_preview_matches_the_recorded_result(self, sample_products):
        in_stock, _low, _out = sample_products
        assert inventory_service.preview_resulting_stock(42, "Stock Out", 5) == 37


class TestImages:
    def _png(self, tmp_path, size=900, color=(200, 60, 60)):
        from PySide6.QtGui import QColor, QImage

        image = QImage(size, size, QImage.Format.Format_RGB32)
        image.fill(QColor(*color))
        path = tmp_path / "source.png"
        assert image.save(str(path))
        return path

    def test_images_are_resized_and_stored_under_media(self, tmp_path):
        stored = image_service.import_image(self._png(tmp_path), kind="products")
        assert stored.startswith("products/")
        assert stored.endswith(".jpg")
        from core.paths import MEDIA_DIR

        on_disk = MEDIA_DIR / stored
        assert on_disk.exists()
        from PySide6.QtGui import QImage

        assert max(QImage(str(on_disk)).width(), QImage(str(on_disk)).height()) <= 300

    def test_unsupported_and_corrupt_files_are_rejected(self, tmp_path):
        text_file = tmp_path / "notes.txt"
        text_file.write_text("not an image")
        with pytest.raises(ImageError):
            image_service.import_image(text_file)

        corrupt = tmp_path / "broken.png"
        corrupt.write_bytes(b"\x89PNG\r\n\x1a\n" + b"garbage" * 40)
        with pytest.raises(ImageError):
            image_service.import_image(corrupt)

    def test_missing_file_is_reported(self, tmp_path):
        with pytest.raises(ImageError):
            image_service.import_image(tmp_path / "nope.png")

    def test_stored_images_render_in_widgets(self, qapp, sample_products, tmp_path):
        in_stock, _low, _out = sample_products
        stored = image_service.import_image(self._png(tmp_path), kind="products")
        product_service.set_image(in_stock.id, stored)

        from ui.widgets.images import product_pixmap

        pixmap = product_pixmap(stored, in_stock.name, 44)
        assert not pixmap.isNull()
        assert pixmap.width() <= 44

        product = product_service.get_product(in_stock.id)
        assert product.image_path == stored

    def test_unknown_images_fall_back_to_a_placeholder(self, qapp):
        from ui.widgets.images import product_pixmap

        assert not product_pixmap(None, "Missing", 44).isNull()
        assert image_service.load_qimage("does/not/exist.jpg") is None
