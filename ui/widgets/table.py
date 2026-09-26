"""Data table with a sticky header and a proper empty state."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class Column:
    label: str
    align: str = "left"  # left | right | center
    width: int | None = None
    stretch: bool = False

    @property
    def qt_align(self) -> Qt.AlignmentFlag:
        return {
            "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "center": Qt.AlignmentFlag.AlignCenter,
        }.get(self.align, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class EmptyOverlay(QWidget):
    """Explains what to do next instead of showing a blank table."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._connected = None
        self.setStyleSheet("background: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel("")
        self.title.setObjectName("EmptyStateTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message = QLabel("")
        self.message.setObjectName("EmptyState")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.action = QPushButton("")
        self.action.setProperty("variant", "primary")
        self.action.setVisible(False)

        layout.addWidget(self.title)
        layout.addWidget(self.message)
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignCenter)

    def set_content(
        self, message: str, *, title: str = "", action_label: str = "", callback=None
    ) -> None:
        self.title.setText(title)
        self.title.setVisible(bool(title))
        self.message.setText(message)
        show_action = bool(action_label and callback)
        self.action.setText(action_label)
        self.action.setVisible(show_action)
        if show_action:
            if self._connected:
                self.action.clicked.disconnect(self._connected)
            self.action.clicked.connect(callback)
            self._connected = callback
        elif self._connected:
            self.action.clicked.disconnect(self._connected)
            self._connected = None


class DataTable(QTableWidget):
    """Column-driven table: set columns once, then push rows of strings/widgets."""

    row_double_clicked = Signal(int)

    def __init__(self, columns: list[Column] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._columns: list[Column] = []
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        self.setWordWrap(False)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._empty = EmptyOverlay(self)
        self._empty.hide()

        if columns:
            self.set_columns(columns)

        self.doubleClicked.connect(lambda index: self.row_double_clicked.emit(index.row()))

    # ------------------------------------------------------------- columns

    def set_columns(self, columns: list[Column]) -> None:
        self._columns = list(columns)
        self.setColumnCount(len(columns))
        self.setHorizontalHeaderLabels([column.label for column in columns])
        header = self.horizontalHeader()
        for index, column in enumerate(columns):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if column.stretch
                else (
                    QHeaderView.ResizeMode.Fixed
                    if column.width
                    else QHeaderView.ResizeMode.ResizeToContents
                )
            )
            header.setSectionResizeMode(index, mode)
            if column.width:
                self.setColumnWidth(index, column.width)
        if not any(column.stretch for column in columns):
            header.setStretchLastSection(True)

    @property
    def columns(self) -> list[Column]:
        return list(self._columns)

    # ---------------------------------------------------------------- rows

    def set_rows(self, rows: list[list]) -> None:
        """Populate the table; each cell is a string or a QWidget."""
        self.clearContents()
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                if column_index >= len(self._columns):
                    break
                if isinstance(value, QWidget):
                    self.setCellWidget(row_index, column_index, value)
                    continue
                item = QTableWidgetItem("" if value is None else str(value))
                item.setTextAlignment(self._columns[column_index].qt_align)
                item.setData(Qt.ItemDataRole.UserRole, row_index)
                self.setItem(row_index, column_index, item)
        self._refresh_empty()

    def append_row(self, values: list) -> int:
        row_index = self.rowCount()
        self.insertRow(row_index)
        for column_index, value in enumerate(values):
            if column_index >= len(self._columns):
                break
            if isinstance(value, QWidget):
                self.setCellWidget(row_index, column_index, value)
                continue
            item = QTableWidgetItem("" if value is None else str(value))
            item.setTextAlignment(self._columns[column_index].qt_align)
            self.setItem(row_index, column_index, item)
        self._refresh_empty()
        return row_index

    def selected_row(self) -> int:
        rows = self.selectionModel().selectedRows()
        return rows[0].row() if rows else self.currentRow()

    def cell_text(self, row: int, column: int) -> str:
        item = self.item(row, column)
        return item.text() if item else ""

    # ---------------------------------------------------------- empty state

    def set_empty_state(
        self, message: str, *, title: str = "", action_label: str = "", callback=None
    ) -> None:
        self._empty.set_content(
            message, title=title, action_label=action_label, callback=callback
        )
        self._refresh_empty()

    def _refresh_empty(self) -> None:
        empty = self.rowCount() == 0
        self._empty.setVisible(empty)
        self.viewport().setVisible(not empty)
        self.horizontalHeader().setVisible(not empty)
        if empty:
            self._empty.setGeometry(self.rect())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._empty.setGeometry(self.rect())
