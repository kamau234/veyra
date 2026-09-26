"""Shared dialog shells: message, confirm and the scrollable form dialog.

Every dialog in VEYRA is built on one of these three so behaviour stays
predictable: validation errors appear inline next to the offending field,
workflow failures appear in a banner, and the technical detail goes to the
log instead of a traceback (blueprint 20.3).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.exceptions import ValidationError, VeyraError
from core.logger import get_logger, log_unexpected
from ui.widgets.banner import Banner
from ui.widgets.fields import Field

logger = get_logger("ui.dialogs")


def _icon_label(kind: str) -> QLabel:
    from ui.theme import current

    theme = current()
    glyph = {"info": "i", "success": "✓", "warning": "!", "danger": "×"}.get(kind, "i")
    color = {
        "info": theme.primary,
        "success": theme.success,
        "warning": theme.warning,
        "danger": theme.danger,
    }.get(kind, theme.primary)

    label = QLabel(glyph)
    label.setFixedSize(34, 34)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(
        f"background: {color}; color: #FFFFFF; border-radius: 17px;"
        f" font-size: 18px; font-weight: 700;"
    )
    return label


class MessageDialog(QDialog):
    """A single-message dialog; the UI's replacement for raw tracebacks."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        kind: str = "info",
        detail: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_icon_label(kind))
        texts = QVBoxLayout()
        texts.setSpacing(3)
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        body = QLabel(message)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        texts.addWidget(heading)
        texts.addWidget(body)
        top.addLayout(texts, stretch=1)
        layout.addLayout(top)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            detail_label.setStyleSheet(
                "color: #6B7280; font-size: 11px; padding-left: 46px;"
            )
            detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(detail_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons, alignment=Qt.AlignRight)

    @staticmethod
    def show_message(
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        kind: str = "info",
        detail: str | None = None,
    ) -> None:
        dialog = MessageDialog(parent, title, message, kind=kind, detail=detail)
        dialog.exec()


class ConfirmDialog(QDialog):
    """Yes/no question with an explicit danger variant for destructive acts."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm_label: str = "Confirm",
        variant: str = "primary",
        detail: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_icon_label("danger" if variant == "danger" else "warning"))
        texts = QVBoxLayout()
        texts.setSpacing(3)
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        body = QLabel(message)
        body.setWordWrap(True)
        texts.addWidget(heading)
        texts.addWidget(body)
        top.addLayout(texts, stretch=1)
        layout.addLayout(top)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setWordWrap(True)
            detail_label.setStyleSheet("color: #6B7280; font-size: 11px; padding-left: 46px;")
            layout.addWidget(detail_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(confirm_label)
        confirm.setProperty("variant", variant)
        confirm.setDefault(True)
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        confirm.setFocus()

    @staticmethod
    def ask(
        parent: QWidget | None,
        title: str,
        message: str,
        *,
        confirm_label: str = "Confirm",
        variant: str = "primary",
        detail: str | None = None,
    ) -> bool:
        dialog = ConfirmDialog(
            parent, title, message,
            confirm_label=confirm_label, variant=variant, detail=detail,
        )
        return dialog.exec() == QDialog.Accepted


class FormDialog(QDialog):
    """Scrollable form shell with a banner, inline errors and Save/Cancel.

    Subclasses fill ``self.form_layout`` and implement :meth:`on_submit`.
    Raising ``ValidationError`` from ``on_submit`` keeps the dialog open and
    paints the problem next to the matching field; any other ``VeyraError``
    shows in the banner.
    """

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        subtitle: str = "",
        *,
        confirm_label: str = "Save",
        confirm_variant: str = "primary",
        width: int = 560,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(width, min(640, max(420, width)))

        self.fields: dict[str, Field] = {}
        self._submitted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        root.addWidget(heading)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("CardSubtitle")
            sub.setWordWrap(True)
            root.addWidget(sub)

        self.banner = Banner(self)
        root.addWidget(self.banner)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.form_widget = QWidget()
        self.form_layout = QVBoxLayout(self.form_widget)
        self.form_layout.setContentsMargins(2, 2, 6, 2)
        self.form_layout.setSpacing(12)
        self.form_layout.addStretch(1)
        scroll.setWidget(self.form_widget)
        root.addWidget(scroll, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.confirm_button = QPushButton(confirm_label)
        self.confirm_button.setProperty("variant", confirm_variant)
        self.confirm_button.setDefault(True)
        self.confirm_button.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm_button)
        root.addLayout(buttons)

    # ------------------------------------------------------------- building

    def add_field(self, field: Field) -> Field:
        self.form_layout.insertWidget(self.form_layout.count() - 1, field)
        self.fields[field.label] = field
        return field

    def add_widget(self, widget: QWidget) -> QWidget:
        self.form_layout.insertWidget(self.form_layout.count() - 1, widget)
        return widget

    def add_row(self, *fields: Field) -> QHBoxLayout:
        """Place several fields side by side (prices, stock/reorder...)."""
        row = QHBoxLayout()
        row.setSpacing(12)
        for field in fields:
            row.addWidget(field)
            self.fields[field.label] = field
        self.form_layout.insertLayout(self.form_layout.count() - 1, row)
        return row

    # ------------------------------------------------------------- feedback

    def clear_errors(self) -> None:
        self.banner.clear()
        for field in self.fields.values():
            field.clear_error()

    def show_validation_error(self, error: ValidationError) -> None:
        """Paint the banner plus any inline errors the message maps to."""
        self.banner.show_message(error.message, "danger")
        if error.field and error.field in self.fields:
            self.fields[error.field].set_error(error.message)
        for sentence in (error.detail or "").split(". "):
            for label, field in self.fields.items():
                if sentence.startswith(label):
                    field.set_error(sentence if sentence.endswith(".") else sentence + ".")

    def show_error(self, error: VeyraError) -> None:
        self.banner.show_message(error.message, "danger")

    # ------------------------------------------------------------- submit

    def _submit(self) -> None:
        self.clear_errors()
        try:
            self.on_submit()
        except ValidationError as error:
            logger.info("%s rejected: %s", self.windowTitle(), error.message)
            self.show_validation_error(error)
            return
        except VeyraError as error:
            logger.warning("%s failed: %s", self.windowTitle(), error.message)
            self.show_error(error)
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback to the user
            reference = log_unexpected(logger, f"dialog:{self.windowTitle()}", exc)
            self.banner.show_message(
                "Something went wrong. "
                f"Reference {reference}. No changes were saved.",
                "danger",
            )
            return
        self._submitted = True
        self.accept()

    def on_submit(self) -> None:
        raise NotImplementedError

    @property
    def submitted(self) -> bool:
        return self._submitted
