"""Database backup and restore (blueprint 12.4, 17.3, 17.4)."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.exceptions import FileError
from core.logger import get_logger
from core.paths import BACKUP_DIR, DATABASE_PATH, ensure_dirs

logger = get_logger("services.backup")

BACKUP_PATTERN = "veyra-backup-*.db"
PRE_RESTORE_PREFIX = "veyra-pre-restore-"


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: datetime
    size_bytes: int

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_label(self) -> str:
        size = self.size_bytes
        for unit in ("B", "KB", "MB"):
            if size < 1024 or unit == "MB":
                return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
            size /= 1024
        return f"{size:,.1f} MB"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _copy_database(source: Path, destination: Path) -> Path:
    """Consistent copy via the SQLite backup API (safe with WAL enabled).

    ``with sqlite3.connect(...)`` only manages the transaction, not the
    connection, so the handles are closed explicitly — an open handle would
    lock the file and break restore on Windows.
    """
    if not source.exists():
        raise FileError("There is no database to back up yet.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(destination))
    try:
        src.backup(dst)
    except sqlite3.Error as exc:
        logger.error("Backup copy failed: %s", exc)
        raise FileError("The database backup could not be written.") from exc
    finally:
        dst.close()
        src.close()

    if not destination.exists() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise FileError("The backup file was not written correctly.")
    return destination


def create_backup(directory: Path | None = None) -> BackupInfo:
    """Create a timestamped backup and verify it was written."""
    ensure_dirs()
    target_dir = Path(directory) if directory else BACKUP_DIR
    destination = target_dir / f"veyra-backup-{_timestamp()}.db"
    _copy_database(DATABASE_PATH, destination)
    logger.info("Backup created: %s", destination)
    return _info(destination)


def create_pre_restore_backup() -> BackupInfo | None:
    """Automatic safety net taken before a restore replaces live data."""
    if not DATABASE_PATH.exists():
        return None
    destination = BACKUP_DIR / f"{PRE_RESTORE_PREFIX}{_timestamp()}.db"
    _copy_database(DATABASE_PATH, destination)
    logger.info("Pre-restore backup created: %s", destination)
    return _info(destination)


def list_backups(directory: Path | None = None) -> list[BackupInfo]:
    target_dir = Path(directory) if directory else BACKUP_DIR
    if not target_dir.exists():
        return []
    entries = [_info(path) for path in target_dir.glob("*.db") if path.is_file()]
    return sorted(entries, key=lambda item: item.created_at, reverse=True)


def _info(path: Path) -> BackupInfo:
    stamp = datetime.fromtimestamp(path.stat().st_mtime)
    return BackupInfo(path=path, created_at=stamp, size_bytes=path.stat().st_size)


def validate_backup(path: str | Path) -> Path:
    """Confirm a file really is a readable VEYRA database."""
    candidate = Path(path)
    if not candidate.exists():
        raise FileError("That backup file could not be found.")
    if candidate.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        raise FileError("Choose a VEYRA backup file (.db).")
    connection = None
    try:
        connection = sqlite3.connect(str(candidate))
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        logger.error("Backup validation failed for %s: %s", candidate, exc)
        raise FileError("That file is not a valid VEYRA database.") from exc
    finally:
        if connection is not None:
            connection.close()

    required = {"products", "sales", "sale_items", "stock_movements", "settings", "categories"}
    if not required.issubset(tables):
        raise FileError(
            "That database is missing VEYRA tables and cannot be restored."
        )
    if not integrity or str(integrity[0]).lower() != "ok":
        raise FileError("That backup failed its integrity check and was not restored.")
    return candidate


def _remove(path: Path) -> None:
    """Delete a file, tolerating the brief lock Windows keeps after a close."""
    if not path.exists():
        return
    for attempt in range(5):
        try:
            path.unlink()
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


def restore_backup(path: str | Path) -> tuple[BackupInfo | None, Path]:
    """Replace the live database with a backup.

    The current database is backed up first, all engine connections are
    dropped and the file plus its WAL sidecars are replaced, then the engine is
    re-initialized so no stale connection remains in memory. The UI should
    still advise a restart before continuing to work.
    """
    source = validate_backup(path)
    ensure_dirs()

    safety_net = create_pre_restore_backup()

    from db.engine import dispose_engine
    from db.session import reset_session_factory

    dispose_engine()
    reset_session_factory()

    try:
        for suffix in ("-wal", "-shm", ""):
            _remove(Path(f"{DATABASE_PATH}{suffix}"))
    except PermissionError as exc:
        logger.error("Could not replace the database file for restore", exc_info=exc)
        raise FileError(
            "VEYRA could not replace the database file. Close the application and try again."
        ) from exc

    _copy_database(source, DATABASE_PATH)

    from db.init_db import init_database

    init_database()
    logger.info("Database restored from %s", source)
    return safety_net, DATABASE_PATH


def latest_backup() -> BackupInfo | None:
    backups = list_backups()
    return backups[0] if backups else None
