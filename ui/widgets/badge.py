"""Compact status badges (In Stock / Low Stock / Out of Stock / states)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QWidget

from core.constants import StockStatus
from ui import theme

KIND_BY_STATUS = {
    StockStatus.IN_STOCK: "success",
    StockStatus.LOW_STOCK: "warning",
    StockStatus.OUT_OF_STOCK: "danger",
    "Archived": "neutral",
    "Completed": "success",
    "Stock In": "success",
    "Stock Out": "danger",
    "Adjustment": "warning",
}


def status_kind(text: str) -> str:
    return KIND_BY_STATUS.get(str(text or "").strip(), "neutral")


class StatusBadge(QLabel):
    """A pill whose colour is derived from the status text it shows."""

    def __init__(self, text: str = "", kind: str | None = None, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self._kind = kind
        self._apply()

    def set_status(self, text: str, kind: str | None = None) -> None:
        self.setText(text)
        self._kind = kind
        self._apply()

    @property
    def kind(self) -> str:
        return self._kind or status_kind(self.text())

    def _apply(self) -> None:
        background, foreground = theme.current().badge_colors(self.kind)
        self.setStyleSheet(
            f"background: {background}; color: {foreground}; border-radius: 9px;"
        )
