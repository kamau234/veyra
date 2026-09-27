"""A database created before Subcategory/Brand existed keeps working."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

LEGACY_SCHEMA = """
CREATE TABLE categories (
    id INTEGER NOT NULL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE TABLE products (
    id INTEGER NOT NULL PRIMARY KEY,
    code VARCHAR(60) NOT NULL,
    name VARCHAR(200) NOT NULL,
    category_id INTEGER,
    unit VARCHAR(30) NOT NULL,
    cost_price BIGINT NOT NULL,
    selling_price BIGINT NOT NULL,
    stock_quantity INTEGER NOT NULL,
    reorder_level INTEGER NOT NULL,
    vat_applicable BOOLEAN NOT NULL,
    image_path VARCHAR(500),
    is_active BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL
);
"""


def _legacy_database(path: Path) -> Path:
    """Write a two-table database in the shape VEYRA used before this change."""
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        for statement in LEGACY_SCHEMA.strip().split(";"):
            if statement.strip():
                connection.execute(text(statement))
        connection.execute(
            text(
                "INSERT INTO categories (id, name, created_at) "
                "VALUES (1, 'Detergents', '2026-01-01 09:00:00')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO products (id, code, name, category_id, unit, cost_price, "
                "selling_price, stock_quantity, reorder_level, vat_applicable, image_path, "
                "is_active, created_at, updated_at) VALUES "
                "(1, 'DET001', 'Ariel Detergent 1kg', 1, 'Piece', 29000, 35000, 42, 10, 1, "
                "NULL, 1, '2026-01-01 09:00:00', '2026-01-01 09:00:00')"
            )
        )
    engine.dispose()
    return path


@pytest.fixture
def migrated(tmp_path):
    """Open a legacy database through the normal startup path, then put it back."""
    from db.engine import get_engine, set_engine
    from db.init_db import init_database
    from db.session import reset_session_factory

    original = get_engine()
    engine = init_database(_legacy_database(tmp_path / "legacy.db"))
    try:
        yield engine
    finally:
        engine.dispose()
        set_engine(original)
        reset_session_factory()


def test_existing_database_gains_the_columns_without_losing_rows(migrated):
    columns = {column["name"] for column in inspect(migrated).get_columns("products")}
    assert {"subcategory", "brand"} <= columns

    from services import product_service

    product = product_service.find_by_code("DET001")
    assert product is not None
    assert product.name == "Ariel Detergent 1kg"
    assert product.category_name == "Detergents"
    assert product.selling_price == Decimal("350.00")
    assert product.stock_quantity == 42
    # The migration made room for the new levels; it did not invent them.
    assert product.subcategory is None
    assert product.brand is None

    product_service.update_product(
        product.id,
        product_service.ProductInput(
            code="DET001",
            name="Ariel Detergent 1kg",
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
    refreshed = product_service.find_by_code("DET001")
    assert (refreshed.subcategory, refreshed.brand) == ("Washing Powder", "Ariel")
    assert refreshed.stock_quantity == 42


def test_migration_is_idempotent(migrated, tmp_path):
    from db.init_db import init_database
    from db.session import reset_session_factory

    # Opening the same file twice must not fail on the columns it already added.
    engine = init_database(tmp_path / "legacy.db")
    reset_session_factory()
    try:
        inspector = inspect(engine)
        indexes = {index["name"] for index in inspector.get_indexes("products")}
        assert {"ix_products_subcategory", "ix_products_brand"} <= indexes
        assert len(inspector.get_columns("products")) == 16
    finally:
        engine.dispose()
        reset_session_factory()
