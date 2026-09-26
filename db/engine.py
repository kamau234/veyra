"""SQLite engine creation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from core.logger import get_logger
from core.paths import DATABASE_PATH, ensure_dirs

logger = get_logger("db.engine")

_engine: Engine | None = None


def database_url(path: Path | None = None) -> str:
    target = Path(path or DATABASE_PATH)
    return f"sqlite:///{target.as_posix()}"


def create_db_engine(path: Path | None = None, *, echo: bool = False) -> Engine:
    """Create an engine with foreign key enforcement switched on.

    SQLite ignores foreign keys unless the pragma is set per connection, and
    VEYRA's data integrity rules (a sale cannot exist without items, a
    movement cannot reference a missing product) depend on them.
    """
    if path is None:
        ensure_dirs()
    engine = create_engine(
        database_url(path),
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver glue
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
        logger.info("Database engine created at %s", DATABASE_PATH)
    return _engine


def set_engine(engine: Engine) -> None:
    """Install an engine explicitly (used by tests and after a restore)."""
    global _engine
    _engine = engine


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        logger.info("Database engine disposed")
    _engine = None
