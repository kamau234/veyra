"""Generation of the authoritative VEYRA product import workbook.

The template produced here is the single definition of the import contract:
``TEMPLATE_COLUMNS`` is consumed by the reader and the validator so column
names, order and dropdown choices can never drift apart.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from core.constants import UNITS
from core.exceptions import FileError
from core.logger import get_logger

logger = get_logger("imports.template")

#: Required columns, in order. One definition — reader and validator import this.
TEMPLATE_COLUMNS = (
    "Product Code",
    "Product Name",
    "Category",
    "Unit",
    "Cost Price",
    "Selling Price",
    "Opening Stock",
    "Reorder Level",
    "VAT Applicable",
)

TEMPLATE_TITLE = "VEYRA PRODUCT IMPORT TEMPLATE"
BRAND_FILL = "2563EB"
HEADER_FILL = "DBEAFE"
BORDER_COLOR = "9CA3AF"

#: Rows the dropdowns cover; users rarely paste more than a few hundred products.
DROPDOWN_LAST_ROW = 500

_EXAMPLE_ROWS = (
    ("DET001", "Ariel Detergent 1kg", "Detergents", "Piece", 290, 350, 40, 10, "Yes"),
    ("BRD001", "Supreme Bread 400g", "Bakery", "Piece", 45, 60, 25, 8, "No"),
    ("MIL001", "Fresh Milk 500ml", "Beverages", "Litre", 55, 70, 30, 12, "Yes"),
)

_COLUMN_WIDTHS = {
    "Product Code": 16,
    "Product Name": 32,
    "Category": 18,
    "Unit": 12,
    "Cost Price": 14,
    "Selling Price": 14,
    "Opening Stock": 15,
    "Reorder Level": 15,
    "VAT Applicable": 15,
}

INSTRUCTIONS = (
    "1. Do not rename the required columns.",
    "2. Enter one product per row.",
    "3. Category can be a new or existing category.",
    "4. Prices must be numeric; do not type currency symbols into cells.",
    "5. Opening Stock and Reorder Level must be non-negative numbers.",
    "6. VAT Applicable must be Yes or No.",
    "7. Save the workbook as .xlsx before importing.",
)

#: Column name / required / example, printed on the Instructions sheet.
#: Blueprint 7.2: every one of the nine columns is required.
_COLUMN_REFERENCE = (
    ("Product Code", "Yes", "DET001"),
    ("Product Name", "Yes", "Ariel Detergent 1kg"),
    ("Category", "Yes", "Detergents"),
    ("Unit", "Yes", "Piece"),
    ("Cost Price", "Yes", "290"),
    ("Selling Price", "Yes", "350"),
    ("Opening Stock", "Yes", "40"),
    ("Reorder Level", "Yes", "10"),
    ("VAT Applicable", "Yes", "Yes"),
)


def _build_products_sheet(sheet) -> None:
    last_column = len(TEMPLATE_COLUMNS)
    banner_font = Font(bold=True, size=14, color="FFFFFF")
    banner_fill = PatternFill("solid", fgColor=BRAND_FILL)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    for column in range(1, last_column + 1):
        cell = sheet.cell(row=1, column=column)
        cell.fill = banner_fill
        cell.font = banner_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.cell(row=1, column=1, value=TEMPLATE_TITLE)
    sheet.row_dimensions[1].height = 26

    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor=HEADER_FILL)
    thin = Side(style="thin", color=BORDER_COLOR)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for column, name in enumerate(TEMPLATE_COLUMNS, start=1):
        cell = sheet.cell(row=2, column=column, value=name)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.column_dimensions[get_column_letter(column)].width = _COLUMN_WIDTHS[name]

    for offset, example in enumerate(_EXAMPLE_ROWS):
        for column, value in enumerate(example, start=1):
            sheet.cell(row=3 + offset, column=column, value=value).border = border

    sheet.freeze_panes = "A3"

    unit_column = get_column_letter(TEMPLATE_COLUMNS.index("Unit") + 1)
    vat_column = get_column_letter(TEMPLATE_COLUMNS.index("VAT Applicable") + 1)
    unit_validation = DataValidation(
        type="list",
        formula1='"' + ",".join(UNITS) + '"',
        allow_blank=True,
        showErrorMessage=True,
    )
    unit_validation.error = "Choose a unit from the list."
    unit_validation.errorTitle = "Invalid unit"
    sheet.add_data_validation(unit_validation)
    unit_validation.add(f"{unit_column}3:{unit_column}{DROPDOWN_LAST_ROW}")

    vat_validation = DataValidation(
        type="list",
        formula1='"Yes,No"',
        allow_blank=True,
        showErrorMessage=True,
    )
    vat_validation.error = "VAT Applicable must be Yes or No."
    vat_validation.errorTitle = "Invalid value"
    sheet.add_data_validation(vat_validation)
    vat_validation.add(f"{vat_column}3:{vat_column}{DROPDOWN_LAST_ROW}")


def _build_instructions_sheet(sheet) -> None:
    title = sheet.cell(row=1, column=1, value="How to fill in the import template")
    title.font = Font(bold=True, size=13, color=BRAND_FILL)

    row = 3
    for line in INSTRUCTIONS:
        sheet.cell(row=row, column=1, value=line)
        row += 1

    row += 1
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor=HEADER_FILL)
    for column, heading in enumerate(("Column", "Required", "Example"), start=1):
        cell = sheet.cell(row=row, column=column, value=heading)
        cell.font = header_font
        cell.fill = header_fill
    row += 1
    for reference in _COLUMN_REFERENCE:
        for column, value in enumerate(reference, start=1):
            sheet.cell(row=row, column=column, value=value)
        row += 1

    sheet.column_dimensions["A"].width = 60
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].width = 28


def generate_template(destination: Path | str) -> Path:
    """Write the official import template to ``destination`` and return the path."""
    path = Path(destination)
    workbook = Workbook()
    products = workbook.active
    products.title = "Products"
    _build_products_sheet(products)
    _build_instructions_sheet(workbook.create_sheet("Instructions"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(path)
    except OSError as exc:
        logger.error("Could not save the import template to %s", path, exc_info=exc)
        raise FileError(
            f"The template could not be saved to '{path.name}'.", detail=repr(exc)
        ) from exc
    logger.info("Generated import template at %s", path)
    return path
