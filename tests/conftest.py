"""Shared pytest fixtures.

Each test gets a brand-new SQLite database in a throwaway VEYRA data home so
tests never touch the developer's real shop data. Qt runs offscreen.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TEST_HOME = PROJECT_ROOT / ".pytest-home"
os.environ["VEYRA_HOME"] = str(TEST_HOME)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


def _wipe(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def fresh_database():
    """Reset the database, media and backups before every test."""
    from core import paths
    from db.engine import dispose_engine
    from db.session import reset_session_factory

    dispose_engine()
    reset_session_factory()

    for suffix in ("", "-wal", "-shm"):
        _wipe(Path(f"{paths.DATABASE_PATH}{suffix}"))
    _wipe(paths.MEDIA_DIR)
    _wipe(paths.BACKUP_DIR)
    paths.ensure_dirs()

    from db.init_db import init_database

    init_database()
    yield
    dispose_engine()
    reset_session_factory()


@pytest.fixture
def sample_products():
    """Three products covering In Stock, Low Stock and Out of Stock."""
    from services import product_service

    in_stock = product_service.create_product(
        product_service.ProductInput(
            code="DET001",
            name="Ariel Detergent 1kg",
            category="Detergents",
            unit="Piece",
            cost_price="290",
            selling_price="350",
            stock_quantity=42,
            reorder_level=10,
            vat_applicable=True,
        )
    )
    low_stock = product_service.create_product(
        product_service.ProductInput(
            code="SP001",
            name="Bar Soap",
            category="Household",
            unit="Piece",
            cost_price="180",
            selling_price="250",
            stock_quantity=4,
            reorder_level=5,
            vat_applicable=True,
        )
    )
    out_of_stock = product_service.create_product(
        product_service.ProductInput(
            code="HM001",
            name="Hammer",
            category="Hardware",
            unit="Piece",
            cost_price="700",
            selling_price="950",
            stock_quantity=0,
            reorder_level=2,
            vat_applicable=False,
        )
    )
    return in_stock, low_stock, out_of_stock
