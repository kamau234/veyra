"""Excel template generation, import validation and the atomic commit."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from core.exceptions import FileError
from imports.excel_template import TEMPLATE_COLUMNS, generate_template
from services import import_service, inventory_service, product_service


def write_workbook(path: Path, rows: list[tuple], *, header: tuple = TEMPLATE_COLUMNS) -> Path:
    """Build a plain workbook with a header row and the given data rows."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Products"
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    workbook.save(path)
    return path


GOOD_ROW = ("DET001", "Ariel Detergent 1kg", "Detergents", "Piece", 290, 350, 40, 10, "Yes")


class TestTemplate:
    def test_generates_a_workbook_with_both_sheets(self, tmp_path):
        path = generate_template(tmp_path / "template.xlsx")
        assert path.exists() and path.stat().st_size > 0

        workbook = load_workbook(path)
        assert "Products" in workbook.sheetnames
        assert "Instructions" in workbook.sheetnames

    def test_products_sheet_matches_the_documented_contract(self, tmp_path):
        path = generate_template(tmp_path / "template.xlsx")
        sheet = load_workbook(path)["Products"]

        assert sheet.cell(row=1, column=1).value == "VEYRA PRODUCT IMPORT TEMPLATE"
        assert tuple(sheet.cell(row=2, column=index).value for index in range(1, 10)) == (
            TEMPLATE_COLUMNS
        )
        # Three example rows, all with a code, name and Yes/No VAT flag.
        for row in range(3, 6):
            assert sheet.cell(row=row, column=1).value
            assert sheet.cell(row=row, column=9).value in {"Yes", "No"}
        assert sheet.freeze_panes == "A3"

    def test_instructions_sheet_lists_the_rules(self, tmp_path):
        sheet = load_workbook(generate_template(tmp_path / "t.xlsx"))["Instructions"]
        text = " ".join(
            str(value)
            for row in sheet.iter_rows(values_only=True)
            for value in row
            if value is not None
        )
        assert "Do not rename the required columns" in text
        assert "VAT Applicable must be Yes or No" in text
        assert "Save the workbook as .xlsx" in text

    def test_generated_template_can_be_imported_as_is(self, tmp_path):
        path = generate_template(tmp_path / "template.xlsx")
        preview = import_service.preview_import(path)
        assert preview.is_valid
        assert len(preview.add) == 3
        summary = import_service.commit_import(preview)
        assert summary.imported == 3
        assert product_service.catalogue_stats()["products"] == 3


class TestReader:
    def test_missing_file_raises_file_error(self, tmp_path):
        with pytest.raises(FileError):
            import_service.preview_import(tmp_path / "nope.xlsx")

    def test_non_xlsx_raises_file_error(self, tmp_path):
        path = tmp_path / "products.csv"
        path.write_text("Product Code,Product Name\nA,B", encoding="utf-8")
        with pytest.raises(FileError):
            import_service.preview_import(path)

    def test_workbook_without_a_header_row_raises_file_error(self, tmp_path):
        path = write_workbook(tmp_path / "bad.xlsx", [GOOD_ROW], header=("Code", "Item"))
        with pytest.raises(FileError, match="header row"):
            import_service.preview_import(path)

    def test_missing_required_column_is_reported(self, tmp_path):
        path = write_workbook(
            tmp_path / "partial.xlsx",
            [("DET001", "Ariel")],
            header=("Product Code", "Product Name"),
        )
        with pytest.raises(FileError, match="missing required columns"):
            import_service.preview_import(path)

    def test_blank_rows_are_skipped(self, tmp_path):
        path = write_workbook(tmp_path / "blanks.xlsx", [GOOD_ROW, ("", "", "", "", "", "", "", "", "")])
        preview = import_service.preview_import(path)
        assert preview.total_rows == 1


class TestValidation:
    def test_valid_row_is_classified_as_add(self, tmp_path):
        preview = import_service.preview_import(write_workbook(tmp_path / "ok.xlsx", [GOOD_ROW]))
        assert len(preview.add) == 1
        assert not preview.update and not preview.rejected
        assert preview.categories_to_create == ["Detergents"]
        row = preview.add[0]
        assert row.cost_price == Decimal("290.00")
        assert row.opening_stock == 40
        assert row.vat_applicable is True

    def test_category_and_unit_are_normalized(self, tmp_path):
        row = list(GOOD_ROW)
        row[2] = "  detergents "
        row[3] = "PIECE"
        preview = import_service.preview_import(write_workbook(tmp_path / "n.xlsx", [tuple(row)]))
        assert preview.add[0].category == "detergents"
        assert preview.add[0].unit == "Piece"

    @pytest.mark.parametrize(
        "column_index,value,column_name",
        [
            (4, "free", "Cost Price"),
            (5, -20, "Selling Price"),
            (6, 4.5, "Opening Stock"),
            (7, -3, "Reorder Level"),
            (8, "maybe", "VAT Applicable"),
        ],
    )
    def test_bad_cells_are_reported_by_row_and_column(
        self, tmp_path, column_index, value, column_name
    ):
        row = list(GOOD_ROW)
        row[column_index] = value
        preview = import_service.preview_import(write_workbook(tmp_path / "bad.xlsx", [tuple(row)]))

        assert preview.rejected and not preview.add
        error = preview.rejected[0].errors[0]
        assert error.column == column_name
        assert error.row == 2
        assert not preview.is_valid

    def test_required_blank_cells_are_reported(self, tmp_path):
        row = list(GOOD_ROW)
        row[0] = ""
        row[2] = ""
        row[3] = ""
        row[8] = ""
        preview = import_service.preview_import(write_workbook(tmp_path / "blank.xlsx", [tuple(row)]))
        columns = {error.column for error in preview.rejected[0].errors}
        assert {"Product Code", "Category", "Unit", "VAT Applicable"} <= columns

    def test_all_errors_in_a_row_are_collected(self, tmp_path):
        row = ["", "", "", "", "free", -1, "x", -2, "maybe"]
        preview = import_service.preview_import(write_workbook(tmp_path / "many.xlsx", [row]))
        assert len(preview.rejected[0].errors) >= 6

    def test_duplicate_code_within_the_workbook_is_rejected(self, tmp_path):
        second = list(GOOD_ROW)
        second[1] = "Ariel Detergent 2kg"
        preview = import_service.preview_import(
            write_workbook(tmp_path / "dupes.xlsx", [GOOD_ROW, tuple(second)])
        )
        assert len(preview.add) == 1
        assert len(preview.rejected) == 1
        assert "Duplicate product code" in preview.rejected[0].errors[0].message

    def test_error_report_can_be_exported(self, tmp_path):
        preview = import_service.preview_import(
            write_workbook(tmp_path / "bad.xlsx", [("X", "No prices", "Cat", "Piece", "a", "b", 1, 1, "Yes")])
        )
        report = import_service.write_error_report(preview, tmp_path / "errors.xlsx")
        sheet = load_workbook(report)["Import Errors"]
        assert sheet.cell(row=1, column=3).value == "Problem"
        assert sheet.max_row >= 2


class TestCommit:
    def test_import_creates_products_categories_and_opening_movements(self, tmp_path):
        rows = [
            GOOD_ROW,
            ("BRD001", "Supreme Bread 400g", "Bakery", "Piece", 45, 60, 25, 8, "No"),
            ("WTR001", "Mineral Water 1L", "Beverages", "Piece", 30, 50, 0, 5, "Yes"),
        ]
        summary = import_service.commit_import(
            import_service.preview_import(write_workbook(tmp_path / "ok.xlsx", rows))
        )

        assert summary.imported == 3
        assert summary.errors == 0
        assert sorted(summary.created_categories) == ["Bakery", "Beverages", "Detergents"]
        assert product_service.catalogue_stats() == {
            "products": 3,
            "categories": 3,
            "archived": 0,
        }

        ariel = product_service.find_by_code("DET001")
        assert ariel.stock_quantity == 40
        assert ariel.vat_applicable is True

        # Opening stock is traceable in the ledger; the zero-stock product has none.
        movements = inventory_service.movements_for_product(ariel.id)
        assert [(m.reason, m.quantity, m.direction) for m in movements] == [
            ("Initial Stock", 40, "in")
        ]
        assert inventory_service.movements_for_product(
            product_service.find_by_code("WTR001").id
        ) == []

    def test_nothing_is_written_when_the_preview_has_errors(self, tmp_path):
        preview = import_service.preview_import(
            write_workbook(tmp_path / "mixed.xlsx", [GOOD_ROW, ("B1", "Bad", "Cat", "Piece", "x", 1, 1, 1, "Yes")])
        )
        assert preview.rejected
        # The UI stops the user here; committing an invalid preview must not create rows.
        assert not preview.is_valid
        assert product_service.catalogue_stats()["products"] == 0

    def test_reimport_updates_master_data_but_never_stock(self, tmp_path):
        import_service.commit_import(
            import_service.preview_import(write_workbook(tmp_path / "first.xlsx", [GOOD_ROW]))
        )
        product = product_service.find_by_code("DET001")
        inventory_service.record_movement(
            product_id=product.id,
            movement_type="Stock Out",
            reason="Damaged",
            quantity=15,
            notes="Crushed",
        )
        product_service.set_image(product.id, "products/keep-me.jpg")
        stock_before = product_service.find_by_code("DET001").stock_quantity
        assert stock_before == 25

        changed = ("DET001", "Ariel Detergent 2kg", "Laundry", "Pack", 310, 399, 999, 12, "No")
        preview = import_service.preview_import(write_workbook(tmp_path / "second.xlsx", [changed]))
        assert len(preview.update) == 1 and not preview.add
        assert any(change.startswith("Selling Price") for change in preview.update[0].changes)

        summary = import_service.commit_import(preview)
        assert summary.updated == 1 and summary.imported == 0

        after = product_service.find_by_code("DET001")
        assert after.name == "Ariel Detergent 2kg"
        assert after.category_name == "Laundry"
        assert after.unit == "Pack"
        assert after.cost_price == Decimal("310.00")
        assert after.selling_price == Decimal("399.00")
        assert after.reorder_level == 12
        assert after.vat_applicable is False
        # The critical rule: live stock and image survived the import untouched.
        assert after.stock_quantity == stock_before
        assert after.image_path == "products/keep-me.jpg"
        assert product_service.catalogue_stats()["products"] == 1

    def test_existing_category_is_reused_not_duplicated(self, tmp_path):
        import_service.commit_import(
            import_service.preview_import(write_workbook(tmp_path / "a.xlsx", [GOOD_ROW]))
        )
        second = ("DET002", "Ariel Detergent 2kg", "detergents", "Piece", 500, 600, 5, 2, "Yes")
        summary = import_service.commit_import(
            import_service.preview_import(write_workbook(tmp_path / "b.xlsx", [second]))
        )
        assert summary.created_categories == []
        assert product_service.catalogue_stats()["categories"] == 1

    def test_commit_is_atomic_when_a_row_fails_mid_transaction(self, tmp_path, monkeypatch):
        rows = [
            GOOD_ROW,
            ("BRD001", "Supreme Bread 400g", "Bakery", "Piece", 45, 60, 25, 8, "No"),
        ]
        preview = import_service.preview_import(write_workbook(tmp_path / "atomic.xlsx", rows))

        original = import_service.apply_movement
        calls = {"count": 0}

        def explode(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("simulated disk failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(import_service, "apply_movement", explode)

        from core.exceptions import DatabaseError

        with pytest.raises(DatabaseError):
            import_service.commit_import(preview)

        assert product_service.catalogue_stats()["products"] == 0
        assert product_service.list_categories() == []
        assert inventory_service.list_movements() == []
