"""Product/owner image rendering with a safe placeholder fallback."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from services import image_service
from ui import theme


def _placeholder(size: int, text: str, *, round_: bool = False) -> QPixmap:
    """Neutral tile with the item's initials — used whenever no image loads."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    current = theme.current()

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    background = QColor(current.surface_alt)
    painter.setBrush(background)
    painter.setPen(QColor(current.border))
    if round_:
        painter.drawEllipse(0, 0, size, size)
    else:
        painter.drawRoundedRect(0, 0, size, size, 8, 8)

    initials = "".join(part[0] for part in str(text or "?").split()[:2]).upper() or "?"
    font = QFont()
    font.setPixelSize(max(int(size * 0.38), 10))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(current.muted))
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, initials)
    painter.end()
    return pixmap


def product_pixmap(stored_path: str | None, name: str = "", size: int = 44) -> QPixmap:
    """Load a product thumbnail, falling back to initials when unavailable."""
    image = image_service.load_qimage(stored_path, size * 2)
    if image is None:
        return _placeholder(size, name or "?")
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        return _placeholder(size, name or "?")
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def avatar_pixmap(stored_path: str | None, name: str = "", size: int = 40) -> QPixmap:
    image = image_service.load_qimage(stored_path, size * 2)
    if image is None:
        return _placeholder(size, name or "V", round_=True)
    pixmap = QPixmap.fromImage(image).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    rounded = QPixmap(size, size)
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.setBrush(QColor(255, 255, 255, 255))
    painter.drawEllipse(0, 0, size, size)
    painter.end()
    return rounded


class Thumbnail(QWidget):
    """Fixed-size image holder that keeps its layout stable when empty."""

    def __init__(self, size: int = 44, parent: QWidget | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        self.setFixedSize(size, size)
        self._size = size
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(self)
        self._label.setFixedSize(size, size)
        layout.addWidget(self._label)

    def set_image(self, stored_path: str | None, name: str = "") -> None:
        self._label.setPixmap(product_pixmap(stored_path, name, self._size))
