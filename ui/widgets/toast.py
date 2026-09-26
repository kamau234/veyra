"""Transient success/failure confirmations (blueprint 4.3, 20.2)."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui import theme

DURATION_MS = 3600
MAX_VISIBLE = 3

KIND_COLORS = {
    "success": "#16A34A",
    "error": "#DC2626",
    "warning": "#F59E0B",
    "info": "#2563EB",
}


class Toast(QFrame):
    def __init__(self, message: str, kind: str = "success", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 14, 9)
        layout.setSpacing(9)

        dot = QLabel()
        dot.setFixedSize(9, 9)
        color = KIND_COLORS.get(kind, KIND_COLORS["info"])
        dot.setStyleSheet(f"background: {color}; border-radius: 4px;")

        label = QLabel(message)
        label.setObjectName("ToastLabel")
        label.setWordWrap(True)
        label.setMaximumWidth(360)

        layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(label, 1)

        self.setFixedWidth(380)
        self.adjustSize()

    def fade_out(self, on_finished) -> None:
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(260)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        animation.finished.connect(lambda: on_finished(self))
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._animation = animation  # keep a reference so it is not collected


class ToastHost(QWidget):
    """Transparent stack pinned to the bottom-right of a window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 18, 18)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self._toasts: list[Toast] = []
        self._anchor = parent

    def show(self, message: str, kind: str = "success") -> None:  # noqa: A003 - Qt naming
        if not message:
            return
        toast = Toast(message, kind, self)
        self._layout.insertWidget(self._layout.count() - 1, toast)
        self._toasts.append(toast)

        while len(self._toasts) > MAX_VISIBLE:
            self._dismiss(self._toasts[0])

        self._reposition()
        QTimer.singleShot(DURATION_MS, lambda: self._safe_dismiss(toast))

    def show_error(self, message: str) -> None:
        self.show(message, "error")

    def show_warning(self, message: str) -> None:
        self.show(message, "warning")

    def _safe_dismiss(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._dismiss(toast)

    def _dismiss(self, toast: Toast) -> None:
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)
        toast.fade_out(self._remove)

    def _remove(self, toast: Toast) -> None:
        self._layout.removeWidget(toast)
        toast.deleteLater()
        self._reposition()

    def _reposition(self) -> None:
        if self._anchor is not None:
            self.setGeometry(self._anchor.rect())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._reposition()


def toast_background() -> QColor:
    return QColor(theme.current().sidebar)
