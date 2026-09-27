"""Database initialization.

Idempotent: safe to call on every application start and from tests.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine

from core.logger import get_logger
from db.base import Base
from db.engine import create_db_engine, set_engine
from db.session import new_session, reset_session_factory

logger = get_logger("db.init")

#: Additive schema steps for databases created by an older VEYRA. Every column
#: here must be nullable so existing rows survive untouched — a migration never
#: invents data, it only makes room for it.
_ADDITIVE_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "products": (
        ("subcategory", "VARCHAR(120)"),
        ("brand", "VARCHAR(120)"),
    ),
}


def init_database(path: Path | None = None, *, echo: bool = False) -> Engine:
    """Create the engine, build all tables and seed the settings row."""
    import models  # noqa: F401 - registers every mapper on Base.metadata

    engine = create_db_engine(path, echo=echo)
    set_engine(engine)
    reset_session_factory()
    Base.metadata.create_all(engine)
    _ensure_additive_columns(engine)
    logger.info("Schema ready (%d tables)", len(Base.metadata.tables))
    ensure_settings_row()
    return engine


def _ensure_additive_columns(engine: Engine) -> None:
    """Add columns introduced after a database was first created."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, columns in _ADDITIVE_COLUMNS.items():
            if table not in tables:
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in present:
                    continue
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                connection.execute(
                    text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{name} ON {table} ({name})")
                )
                logger.info("Added missing column %s.%s", table, name)


def ensure_settings_row() -> None:
    """Guarantee exactly one settings row exists (blueprint 13.2)."""
    from models import Settings

    session = new_session()
    try:
        if session.get(Settings, 1) is None:
            session.add(Settings(id=1))
            session.commit()
            logger.info("Default settings row created")
    finally:
        session.close()


def table_names(engine: Engine | None = None) -> list[str]:
    from sqlalchemy import inspect

    from db.engine import get_engine

    return sorted(inspect(engine or get_engine()).get_table_names())
