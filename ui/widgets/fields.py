"""Form field helpers: label above input, visible validation state."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.money import to_money


class Field(QWidget):
    """Label + input + inline error, the standard form row (blueprint 4.3)."""

    def __init__(
        self,
        label: str,
        widget: QWidget,
        *,
        hint: str = "",
        required: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.label = label
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        self.label_widget = QLabel(label + (" *" if required else ""))
        self.label_widget.setObjectName("FieldLabel")
        self.widget = widget
        self.error_widget = QLabel("")
        self.error_widget.setObjectName("FieldError")
        self.error_widget.setWordWrap(True)
        self.error_widget.hide()
        self.hint_widget = QLabel(hint)
        self.hint_widget.setObjectName("FieldHint")
        self.hint_widget.setWordWrap(True)
        self.hint_widget.setVisible(bool(hint))

        layout.addWidget(self.label_widget)
        layout.addWidget(self.widget)
        layout.addWidget(self.hint_widget)
        layout.addWidget(self.error_widget)

    def set_error(self, message: str) -> None:
        self.error_widget.setText(message)
        self.error_widget.setVisible(bool(message))
        self.widget.setProperty("invalid", bool(message))
        self.widget.style().unpolish(self.widget)
        self.widget.style().polish(self.widget)

    def clear_error(self) -> None:
        self.set_error("")

    def set_hint(self, hint: str) -> None:
        self.hint_widget.setText(hint)
        self.hint_widget.setVisible(bool(hint))

    def set_label(self, label: str) -> None:
        self.label = label
        self.label_widget.setText(label)


class MoneySpin(QDoubleSpinBox):
    """KSh amount input with two decimal places."""

    def __init__(self, parent: QWidget | None = None, *, maximum: float = 9_999_999.0):
        super().__init__(parent)
        self.setPrefix("KSh ")
        self.setDecimals(2)
        self.setMaximum(maximum)
        self.setMinimum(0.0)
        self.setSingleStep(1.0)
        self.setGroupSeparatorShown(True)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def decimal_value(self) -> Decimal:
        return to_money(self.value())

    def set_decimal(self, value) -> None:
        self.setValue(float(to_money(value)))


class PercentSpin(QDoubleSpinBox):
    """Percentage input, used for the VAT rate."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSuffix(" %")
        self.setDecimals(2)
        self.setRange(0.0, 100.0)
        self.setSingleStep(0.5)
        self.setKeyboardTracking(False)

    def decimal_value(self) -> Decimal:
        return to_money(self.value())

    def set_decimal(self, value) -> None:
        self.setValue(float(to_money(value)))


class IntSpin(QSpinBox):
    def __init__(self, parent: QWidget | None = None, *, maximum: int = 9_999_999):
        super().__init__(parent)
        self.setRange(0, maximum)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class SearchInput(QLineEdit):
    def __init__(self, placeholder: str = "Search...", parent: QWidget | None = None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)


class TextArea(QPlainTextEdit):
    def __init__(self, placeholder: str = "", parent: QWidget | None = None, *, rows: int = 3):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setFixedHeight(max(rows, 2) * 24 + 12)


class Combo(QComboBox):
    """Combo that treats an empty/'All' entry as no filter."""

    def __init__(self, items: list[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        if items:
            self.addItems(items)

    def selected(self) -> str:
        return self.currentText().strip()

    def selected_or_none(self, placeholder: str = "All") -> str | None:
        value = self.selected()
        return None if value in ("", placeholder) else value


class NumericLineEdit(QLineEdit):
    """Free-text numeric entry that rejects non-numeric keystrokes."""

    def __init__(self, parent: QWidget | None = None, *, decimals: int = 2):
        super().__init__(parent)
        self.setValidator(QDoubleValidator(0.0, 9_999_999.0, decimals, self))
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
