"""Validate raw workbook rows into an import preview.

Every problem in a row is collected (not just the first), valid rows are
classified as ``add`` or ``update`` against the live catalogue, and update
rows carry a human-readable list of exactly which master-data fields would
change so the UI preview can show it before anything is committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from core.exceptions import FileError, ImportRowError, ValidationError
from core.money import parse_money, to_int, to_money
from db.session import session_scope
from imports.excel_reader import RawRow, RawWorkbook
from imports.excel_template import REQUIRED_COLUMNS, TEMPLATE_COLUMNS
from models import Product
from repositories.category_repository import CategoryRepository, normalize_name
from repositories.product_repository import ProductRepository
from services import product_service
from services.product_service import LEVEL_MAX_LENGTH


@dataclass(frozen=True)
class ImportRow:
    """A fully valid, normalized workbook row ready to be committed.

    ``subcategory`` and ``brand`` are ``None`` when the workbook has no such
    column at all (a template saved before the hierarchy existed). ``None``
    means "leave whatever the product already has alone" — an old workbook
    must never silently wipe the levels a newer one filled in. An empty string
    means the cell was there and deliberately left blank.
    """

    row_number: int
    code: str
    name: str
    category: str
    unit: str
    cost_price: Decimal
    selling_price: Decimal
    opening_stock: int
    reorder_level: int
    vat_applicable: bool
    subcategory: str | None = None
    brand: str | None = None
    existing_product_id: int | None = None
    changes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RejectedRow:
    row_number: int
    values: dict[str, object]
    errors: list[ImportRowError]


@dataclass(frozen=True)
class ImportPreview:
    """The result of validating a workbook: what will happen if committed."""

    source: Path
    add: list[ImportRow]
    update: list[ImportRow]
    rejected: list[RejectedRow]
    categories_to_create: list[str]
    headers: list[str]
    #: Optional hierarchy columns this workbook does not carry, so the UI can
    #: say plainly that those levels will be left untouched.
    missing_optional: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.rejected and bool(self.add or self.update)

    @property
    def total_rows(self) -> int:
        return len(self.add) + len(self.update) + len(self.rejected)

    def summary_counts(self) -> dict:
        return {
            "add": len(self.add),
            "update": len(self.update),
            "rejected": len(self.rejected),
            "total": self.total_rows,
        }


def _validate_row(raw: RawRow, seen_codes: set[str]) -> tuple[ImportRow | None, list[ImportRowError]]:
    """Normalize and check one row, collecting every cell-level problem."""
    errors: list[ImportRowError] = []
    values = raw.values

    code = product_service.normalize_code(values.get("Product Code"))
    if not code:
        errors.append(ImportRowError(raw.row_number, "Product Code", "Product Code is required."))
    elif code in seen_codes:
        errors.append(
            ImportRowError(
                raw.row_number,
                "Product Code",
                f"Duplicate product code '{code}' — it already appears earlier in this workbook.",
            )
        )
    else:
        # First occurrence wins, even if the row later fails another check.
        seen_codes.add(code)

    name = normalize_name(values.get("Product Name"))
    if not name:
        errors.append(ImportRowError(raw.row_number, "Product Name", "Product Name is required."))

    category = normalize_name(values.get("Category"))
    if not category:
        errors.append(ImportRowError(raw.row_number, "Category", "Category is required."))

    subcategory = _optional_level(raw, "Subcategory", errors)
    brand = _optional_level(raw, "Brand", errors)

    unit = normalize_unit_or_none(values.get("Unit"))
    if unit is None:
        errors.append(ImportRowError(raw.row_number, "Unit", "Unit is required."))

    prices: dict[str, Decimal | None] = {}
    for column in ("Cost Price", "Selling Price"):
        try:
            amount = parse_money(values.get(column))
            if amount < 0:
                errors.append(ImportRowError(raw.row_number, column, f"{column} cannot be negative."))
                amount = None
        except ValueError:
            errors.append(ImportRowError(raw.row_number, column, f"{column} must be a number."))
            amount = None
        prices[column] = amount

    quantities: dict[str, int | None] = {}
    for column in ("Opening Stock", "Reorder Level"):
        try:
            quantities[column] = to_int(values.get(column), field=column)
        except ValueError as exc:
            errors.append(ImportRowError(raw.row_number, column, str(exc)))
            quantities[column] = None

    vat_cell = values.get("VAT Applicable")
    if vat_cell is None or str(vat_cell).strip() == "":
        errors.append(
            ImportRowError(
                raw.row_number, "VAT Applicable", "VAT Applicable must be Yes or No."
            )
        )
        vat_applicable = False
    else:
        try:
            vat_applicable = product_service.normalize_boolean(vat_cell)
        except ValidationError:
            errors.append(
                ImportRowError(
                    raw.row_number, "VAT Applicable", "VAT Applicable must be Yes or No."
                )
            )
            vat_applicable = False

    if errors:
        return None, errors

    return (
        ImportRow(
            row_number=raw.row_number,
            code=code,
            name=name,
            category=category,
            unit=unit or "Piece",
            cost_price=prices["Cost Price"],
            selling_price=prices["Selling Price"],
            opening_stock=quantities["Opening Stock"],
            reorder_level=quantities["Reorder Level"],
            vat_applicable=vat_applicable,
            subcategory=subcategory,
            brand=brand,
        ),
        [],
    )


def _optional_level(raw: RawRow, column: str, errors: list[ImportRowError]) -> str | None:
    """Normalize a blankable hierarchy column.

    Returns ``None`` when the workbook has no such column, otherwise the cell
    text (possibly empty, meaning "deliberately blank").
    """
    if column not in raw.values:
        return None
    text = normalize_name(raw.values.get(column))
    if text and len(text) > LEVEL_MAX_LENGTH:
        errors.append(
            ImportRowError(
                raw.row_number,
                column,
                f"{column} is too long (maximum {LEVEL_MAX_LENGTH} characters).",
            )
        )
        return None
    return text


def normalize_unit_or_none(value: object) -> str | None:
    """Normalize a unit cell; None means the required cell was left blank."""
    if value is None or str(value).strip() == "":
        return None
    return product_service.normalize_unit(value)


def _describe_changes(existing: Product, row: ImportRow) -> list[str]:
    """Human-readable master-data differences an update would apply."""
    changes: list[str] = []
    if existing.code != row.code:
        changes.append(f"Product Code: {existing.code} -> {row.code}")
    if existing.name != row.name:
        changes.append(f"Product Name: {existing.name} -> {row.name}")

    new_category = row.category
    if existing.category_name != new_category:
        changes.append(f"Category: {existing.category_name} -> {new_category}")
    for label, incoming, current in (
        ("Subcategory", row.subcategory, existing.subcategory_name),
        ("Brand", row.brand, existing.brand_name),
    ):
        # None means the workbook has no such column: nothing would change.
        if incoming is not None and incoming != current:
            changes.append(f"{label}: {current or '(blank)'} -> {incoming or '(blank)'}")
    if existing.unit != row.unit:
        changes.append(f"Unit: {existing.unit} -> {row.unit}")

    cost = to_money(existing.cost_price)
    if cost != row.cost_price:
        changes.append(f"Cost Price: {cost:.2f} -> {row.cost_price:.2f}")
    selling = to_money(existing.selling_price)
    if selling != row.selling_price:
        changes.append(f"Selling Price: {selling:.2f} -> {row.selling_price:.2f}")

    if (existing.reorder_level or 0) != row.reorder_level:
        changes.append(f"Reorder Level: {existing.reorder_level or 0} -> {row.reorder_level}")
    if bool(existing.vat_applicable) != row.vat_applicable:
        old = "Yes" if existing.vat_applicable else "No"
        new = "Yes" if row.vat_applicable else "No"
        changes.append(f"VAT Applicable: {old} -> {new}")
    return changes


def _pending_categories(rows: list[ImportRow], categories: CategoryRepository) -> list[str]:
    """Distinct, not-yet-existing category names in workbook order."""
    pending: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = row.category.lower()
        if not row.category or key in seen:
            continue
        seen.add(key)
        if categories.get_by_name(row.category) is None:
            pending.append(row.category)
    return pending


def validate_workbook(raw: RawWorkbook) -> ImportPreview:
    """Classify raw rows into add/update/rejected against the live catalogue."""
    missing = [column for column in REQUIRED_COLUMNS if column not in raw.headers]
    if missing:
        raise FileError(
            "The workbook is missing required columns: " + ", ".join(missing) + "."
        )
    # Subcategory and Brand are optional: a workbook saved from an older
    # template imports normally and leaves those levels alone. Columns are
    # always matched by header name, so nothing can be read from the wrong one.
    missing_optional = [column for column in TEMPLATE_COLUMNS if column not in raw.headers]

    add: list[ImportRow] = []
    update: list[ImportRow] = []
    rejected: list[RejectedRow] = []
    seen_codes: set[str] = set()

    with session_scope() as session:
        products = ProductRepository(session)
        categories = CategoryRepository(session)
        for raw_row in raw.rows:
            row, errors = _validate_row(raw_row, seen_codes)
            if errors:
                rejected.append(
                    RejectedRow(
                        row_number=raw_row.row_number,
                        values=dict(raw_row.values),
                        errors=errors,
                    )
                )
                continue
            existing = products.get_by_code(row.code)
            if existing is not None:
                update.append(
                    replace(
                        row,
                        existing_product_id=existing.id,
                        changes=_describe_changes(existing, row),
                    )
                )
            else:
                add.append(row)
        categories_to_create = _pending_categories(add + update, categories)

    return ImportPreview(
        source=raw.source,
        add=add,
        update=update,
        rejected=rejected,
        categories_to_create=categories_to_create,
        headers=list(raw.headers),
        missing_optional=missing_optional,
    )
