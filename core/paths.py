"""Filesystem locations for the application.

VEYRA is offline-first and portable: by default all data lives beside the
application (media/, logs/, backups/, veyra.db). Set the VEYRA_HOME
environment variable to point at a different data directory — useful for
tests and for keeping a clean demo dataset.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: veyra/ project root (the directory holding main.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """Where bundled read-only assets live.

    A PyInstaller onefile build unpacks its data files into a temporary
    directory exposed as ``sys._MEIPASS``; in a source checkout the assets sit
    next to the project root.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else PROJECT_ROOT


def _data_home() -> Path:
    override = os.environ.get("VEYRA_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        # A onefile bundle unpacks its sources into a temp directory, so data
        # must live beside the .exe the user launched or it vanishes on exit.
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


DATA_HOME = _data_home()
MEDIA_DIR = DATA_HOME / "media"
PRODUCT_IMAGE_DIR = MEDIA_DIR / "products"
PROFILE_IMAGE_DIR = MEDIA_DIR / "profile"
LOGO_IMAGE_DIR = MEDIA_DIR / "logos"
LOG_DIR = DATA_HOME / "logs"
BACKUP_DIR = DATA_HOME / "backups"
ASSETS_DIR = resource_root() / "assets"
FONT_DIR = ASSETS_DIR / "fonts"

DATABASE_PATH = DATA_HOME / "veyra.db"
LOG_FILE = LOG_DIR / "veyra.log"

REQUIRED_DIRS = (
    DATA_HOME,
    MEDIA_DIR,
    PRODUCT_IMAGE_DIR,
    PROFILE_IMAGE_DIR,
    LOGO_IMAGE_DIR,
    LOG_DIR,
    BACKUP_DIR,
)


def ensure_dirs() -> None:
    for directory in REQUIRED_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def resolve_image_path(stored: str | None) -> Path | None:
    """Turn a stored image reference into an absolute path, or None.

    Stored values are relative to the media directory so a moved/copied
    VEYRA installation keeps working.
    """
    if not stored:
        return None
    candidate = Path(stored)
    if not candidate.is_absolute():
        candidate = MEDIA_DIR / candidate
    return candidate if candidate.exists() else None
