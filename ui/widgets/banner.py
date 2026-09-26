"""Inline banner for workflow-level messages (blueprint 20.3)."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel


class Banner(QFrame):
    """A coloured strip above a form or table: warnings, errors, confirmations."""

    COLORS = {
        "info": ("primary",),
        "success": ("success",),
        "warning": ("warning",),
        "danger": ("danger",),
    }

    def __init__(self, parent=None, kind: str = "warning"):
        super().__init__(parent)
        self.setObjectName("Banner")
        self._label = QLabel(self)
        self._label.setObjectName("BannerLabel")
        self._label.setWordWrap(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.addWidget(self._label)
        self._kind = kind
        self.set_kind(kind)
        self.hide()

    def set_kind(self, kind: str) -> None:
        from ui.theme import current

        theme = current()
        self._kind = kind if kind in self.COLORS else "info"
        background = getattr(theme, self.COLORS[self._kind][0])
        self.setStyleSheet(
            f"QFrame#Banner {{ background: {background}22; border: 1px solid {background}; }}"
            f"QLabel#BannerLabel {{ color: {theme.text}; background: transparent; }}"
        )

    def show_message(self, text: str, kind: str | None = None) -> None:
        if kind:
            self.set_kind(kind)
        self._label.setText(text)
        self.show()

    def clear(self) -> None:
        self._label.setText("")
        self.hide()

    @property
    def kind(self) -> str:
        return self._kind
