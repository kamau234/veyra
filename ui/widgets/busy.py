"""Blocking overlay shown while a long operation runs.

Imports, report generation and backups can take a noticeable amount of time.
The overlay dims the page and spins so the user knows a click registered
instead of staring at a frozen window (blueprint 20.1).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.theme import current


class Spinner(QWidget):
    """A small rotating arc, drawn by hand so no extra Qt module is needed."""

    def __init__(self, parent: QWidget | None = None, size: int = 22):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def set_running(self, running: bool) -> None:
        if running:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QPen(QColor(current().border), 3)
        painter.setPen(track)
        painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        arc = QPen(QColor(current().primary), 3)
        arc.setCapStyle(Qt.RoundCap)
        painter.setPen(arc)
        painter.drawArc(2, 2, self.width() - 4, self.height() - 4,
                        self._angle * 16, 90 * 16)
        painter.end()


class BusyOverlay(QWidget):
    """A dimmed panel with a spinner that covers ``parent`` while busy."""

    def __init__(self, parent: QWidget, message: str = "Working..."):
        super().__init__(parent)
        self.setObjectName("BusyOverlay")
        self._message = QLabel(message)
        self._message.setAlignment(Qt.AlignCenter)
        self._message.setWordWrap(True)

        panel = QFrame(self)
        panel.setObjectName("BusyPanel")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)
        self._spinner = Spinner(panel)
        layout.addWidget(self._spinner)
        layout.addWidget(self._message, stretch=1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(panel, alignment=Qt.AlignHCenter)
        outer.addStretch(1)

        self._apply_style()
        self.hide()
        parent.installEventFilter(self)

    def _apply_style(self) -> None:
        theme = current()
        self._message.setStyleSheet(
            f"color: {theme.text}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        self.setStyleSheet(
            f"#BusyOverlay {{ background: rgba(17, 24, 39, 96); }}"
            f"#BusyPanel {{ background: {theme.surface}; border: 1px solid {theme.border};"
            f" border-radius: 10px; }}"
        )

    def eventFilter(self, watched, event):  # noqa: N802 - Qt naming
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.resize(watched.size())
        return super().eventFilter(watched, event)

    def start(self, message: str | None = None) -> None:
        if message:
            self._message.setText(message)
        self._apply_style()
        self.resize(self.parent().size())
        self._spinner.set_running(True)
        self.show()
        self.raise_()

    def stop(self) -> None:
        self._spinner.set_running(False)
        self.hide()

    def is_busy(self) -> bool:
        return self.isVisible()
