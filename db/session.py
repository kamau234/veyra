"""Session factory and transaction helper."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker

from core.exceptions import DatabaseError, VeyraError
from core.logger import get_logger
from db.engine import get_engine

logger = get_logger("db.session")

_session_factory: sessionmaker[Session] | None = None


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), expire_on_commit=False, future=True
        )
    return _session_factory


def reset_session_factory() -> None:
    """Drop the cached factory (after the engine changed, e.g. a restore)."""
    global _session_factory
    _session_factory = None


def new_session() -> Session:
    return get_session_factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Run a unit of work atomically.

    Commits on success and rolls back on any exception. VEYRA domain errors
    (validation, business rules) propagate unchanged so the UI can show their
    message; anything unexpected becomes a ``DatabaseError`` with the technical
    detail kept in the log. This is the boundary that makes "a sale either
    fully succeeds or nothing changes" true.
    """
    session = new_session()
    try:
        yield session
        session.commit()
    except VeyraError:
        session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001 - converted to a domain error
        session.rollback()
        logger.error("Database transaction failed and was rolled back", exc_info=exc)
        raise DatabaseError(detail=repr(exc)) from exc
    finally:
        session.close()
