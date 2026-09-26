"""Cards: the surface used for KPIs, summaries and content blocks."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """A white surface with an optional title row and a body area."""

    def __init__(
        self,
        title: str | None = None,
        subtitle: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label = QLabel(title or "")
        self.title_label.setObjectName("CardTitle")
        self.subtitle_label = QLabel(subtitle or "")
        self.subtitle_label.setObjectName("CardSubtitle")
        self.subtitle_label.setWordWrap(True)

        self.title_column = QVBoxLayout()
        self.title_column.setSpacing(1)
        self.title_column.addWidget(self.title_label)
        self.title_column.addWidget(self.subtitle_label)

        self.header.addLayout(self.title_column, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        self.header.addLayout(self.actions)
        layout.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        layout.addLayout(self.body, 1)

        if not title and not subtitle:
            self.header.setContentsMargins(0, 0, 0, 0)

    def set_title(self, title: str, subtitle: str | None = None) -> None:
        self.title_label.setText(title)
        self.title_label.setVisible(bool(title))
        self.subtitle_label.setText(subtitle or "")
        self.subtitle_label.setVisible(bool(subtitle))

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget

    def set_content(self, widget: QWidget) -> None:
        """Replace the body with a single widget."""
        while self.body.count():
            item = self.body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.body.addWidget(widget)

    def add_widget(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


class KpiCard(QFrame):
    """One dashboard metric: accent bar, label, value, optional hint."""

    def __init__(
        self,
        label: str,
        value: str = "—",
        *,
        accent: str = "#2563EB",
        hint: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(96)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.accent = QFrame()
        self.accent.setObjectName("KpiAccent")
        self.accent.setFixedWidth(4)
        self.accent.setStyleSheet(
            f"background: {accent}; border-top-left-radius: 9px; border-bottom-left-radius: 9px;"
        )
        outer.addWidget(self.accent)

        content = QVBoxLayout()
        content.setContentsMargins(14, 12, 14, 12)
        content.setSpacing(3)
        self.label = QLabel(label.upper())
        self.label.setObjectName("KpiLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("KpiValue")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("KpiHint")
        self.hint_label.setVisible(bool(hint))
        content.addWidget(self.label)
        content.addWidget(self.value_label)
        content.addWidget(self.hint_label)
        content.addStretch(1)
        outer.addLayout(content, 1)

        self._on_click = None

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)

    def set_hint(self, hint: str) -> None:
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))

    def set_accent(self, color: str) -> None:
        self.accent.setStyleSheet(
            f"background: {color}; border-top-left-radius: 9px; border-bottom-left-radius: 9px;"
        )

    def set_clickable(self, callback) -> None:
        """Make the whole card a button-like target for quick navigation."""
        self._on_click = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._on_click and event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)


class MetricRow(QFrame):
    """Compact 'label ........ value' line used in cart and report summaries."""

    def __init__(self, label: str, value: str = "", *, strong: bool = False, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)
        self.label_widget = QLabel(label)
        self.value_widget = QLabel(value)
        self.value_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if strong:
            self.setObjectName("TotalsRow")
            self.label_widget.setStyleSheet("font-weight: 700;")
            self.value_widget.setObjectName("TotalValue")
        else:
            self.label_widget.setObjectName("MetricLabel")
            self.value_widget.setObjectName("MetricValue")
        layout.addWidget(self.label_widget)
        layout.addStretch(1)
        layout.addWidget(self.value_widget)

    def set_value(self, value: str) -> None:
        self.value_widget.setText(value)

    def set_label(self, label: str) -> None:
        self.label_widget.setText(label)
