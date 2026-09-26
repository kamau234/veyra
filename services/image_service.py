"""Product, logo and profile image handling.

Images are resized to a small maximum dimension and stored as files under
``media/`` rather than as SQLite blobs (blueprint 6.7). A failed load never
raises into the UI: callers get ``None`` and show a neutral placeholder.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from core.config import MAX_PRODUCT_IMAGE_PX
from core.exceptions import ImageError
from core.logger import get_logger
from core.paths import (
    LOGO_IMAGE_DIR,
    MEDIA_DIR,
    PROFILE_IMAGE_DIR,
    PRODUCT_IMAGE_DIR,
    resolve_image_path,
)

logger = get_logger("services.images")

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
STORE_FORMAT = "JPG"
STORE_QUALITY = 88

SUBDIRS = {
    "products": PRODUCT_IMAGE_DIR,
    "profile": PROFILE_IMAGE_DIR,
    "logos": LOGO_IMAGE_DIR,
}


def supported_suffix(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def import_image(
    source: str | Path,
    *,
    kind: str = "products",
    max_px: int = MAX_PRODUCT_IMAGE_PX,
) -> str:
    """Copy, resize and store an image; return the path saved in the database.

    Raises ``ImageError`` with a user-readable message for unsupported or
    corrupt files so the caller can keep the rest of the form intact.
    """
    source_path = Path(source)
    if not source_path.exists():
        raise ImageError("That image file could not be found.")
    if not supported_suffix(source_path):
        raise ImageError(
            "Unsupported image type. Use JPG, PNG or WEBP."
        )

    image = QImage(str(source_path))
    if image.isNull():
        logger.warning("Could not decode image: %s", source_path)
        raise ImageError("That image appears to be corrupt and could not be read.")

    if max(image.width(), image.height()) > max_px:
        image = image.scaled(
            max_px,
            max_px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    directory = SUBDIRS.get(kind, PRODUCT_IMAGE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{kind[:-1] if kind.endswith('s') else kind}-{uuid.uuid4().hex[:12]}.{STORE_FORMAT.lower()}"
    target = directory / filename

    if not image.convertToFormat(QImage.Format.Format_RGB32).save(
        str(target), STORE_FORMAT, STORE_QUALITY
    ):
        raise ImageError("VEYRA could not save that image. Please try another file.")

    logger.info("Stored image %s (%dx%d)", target.name, image.width(), image.height())
    return str(target.relative_to(MEDIA_DIR)).replace("\\", "/")


def absolute_path(stored: str | None) -> Path | None:
    return resolve_image_path(stored)


def load_qimage(stored: str | None, size: int | None = None) -> QImage | None:
    """Load a stored image, optionally scaled for a widget. Never raises."""
    path = absolute_path(stored)
    if path is None:
        return None
    try:
        image = QImage(str(path))
        if image.isNull():
            logger.warning("Stored image failed to load: %s", path)
            return None
        if size and max(image.width(), image.height()) > size:
            image = image.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return image
    except Exception as exc:  # noqa: BLE001 - image problems must not break lists
        logger.warning("Image load failed for %s: %s", stored, exc)
        return None


def delete_image(stored: str | None) -> bool:
    path = absolute_path(stored)
    if path is None:
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.warning("Could not delete image %s: %s", path, exc)
        return False
