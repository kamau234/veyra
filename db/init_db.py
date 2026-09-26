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


def init_database(path: Path | None = None, *, echo: bool = False) -> Engine:
    """Create the engine, build all tables and seed the settings row."""
    import models  # noqa: F401 - registers every mapper on Base.metadata

    engine = create_db_engine(path, echo=echo)
    set_engine(engine)
    reset_session_factory()
    Base.metadata.create_all(engine)
    logger.info("Schema ready (%d tables)", len(Base.metadata.tables))
    ensure_settings_row()
    return engine


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
