"""Excel import: pick a workbook, review the preview, then commit atomically."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from imports.excel_validator import ImportPreview
from services import import_service
from ui.widgets.badge import StatusBadge
from ui.widgets.banner import Banner
from ui.widgets.busy import BusyOverlay
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.import")

XLSX_FILTER = "Excel workbooks (*.xlsx);;All files (*)"


class ImportDialog(QDialog):
    """Blueprint 7.3: nothing is written until the preview is accepted."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setWindowTitle("Import Products from Excel")
        self.setModal(True)
        self.resize(900, 620)

        self.preview: ImportPreview | None = None
        self.summary = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QLabel("Import Products")
        title.setObjectName("CardTitle")
        subtitle = QLabel(
            "Rows are validated first. Existing products are updated on master data only; "
            "live stock and images are never overwritten."
        )
        subtitle.setObjectName("CardSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.banner = Banner(self)
        layout.addWidget(self.banner)

        picker = QHBoxLayout()
        picker.setSpacing(8)
        self.file_label = QLabel("No workbook selected.")
        self.file_label.setObjectName("MetricLabel")
        choose = QPushButton("Choose Workbook...")
        choose.setProperty("variant", "primary")
        choose.clicked.connect(self._choose_file)
        template = QPushButton("Download Template")
        template.setProperty("variant", "quiet")
        template.clicked.connect(self._download_template)
        picker.addWidget(self.file_label, stretch=1)
        picker.addWidget(template)
        picker.addWidget(choose)
        layout.addLayout(picker)

        self.counts = QLabel("")
        self.counts.setObjectName("MetricValue")
        layout.addWidget(self.counts)

        self.tabs = QTabWidget()
        self.rows_table = DataTable([
            Column("Row", "right", 60),
            Column("Code", "left", 110),
            Column("Product", stretch=True),
            Column("Category", "left", 130),
            Column("Action", "center", 90),
            Column("What Changes / Why Rejected", stretch=True),
        ])
        self.rows_table.set_empty_state("Choose a workbook to preview its rows.")
        self.errors_table = DataTable([
            Column("Row", "right", 60),
            Column("Column", "left", 140),
            Column("Problem", stretch=True),
        ])
        self.errors_table.set_empty_state("No row errors.")
        self.tabs.addTab(self.rows_table, "Rows")
        self.tabs.addTab(self.errors_table, "Errors (0)")
        layout.addWidget(self.tabs, stretch=1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.export_errors = QPushButton("Export Error Report")
        self.export_errors.setProperty("variant", "quiet")
        self.export_errors.clicked.connect(self._export_errors)
        self.export_errors.hide()
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        self.commit = QPushButton("Import Valid Rows")
        self.commit.setProperty("variant", "success")
        self.commit.clicked.connect(self._commit)
        self.commit.setEnabled(False)
        footer.addWidget(self.export_errors)
        footer.addWidget(cancel)
        footer.addWidget(self.commit)
        layout.addLayout(footer)

        self.busy = BusyOverlay(self)

    # ------------------------------------------------------------------ steps

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose an import workbook", "",
                                              XLSX_FILTER)
        if not path:
            return
        self.file_label.setText(path)
        self.busy.start("Reading and validating the workbook...")
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()
            self.preview = import_service.preview_import(path)
        except VeyraError as error:
            logger.warning("Import preview failed: %s", error.message)
            self.preview = None
            self.banner.show_message(error.message, "danger")
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "import preview", exc)
            self.preview = None
            self.banner.show_message(f"That workbook could not be read. Reference {reference}.",
                                     "danger")
        finally:
            self.busy.stop()
        self._render_preview()

    def _download_template(self) -> None:
        from imports.excel_template import generate_template

        path, _ = QFileDialog.getSaveFileName(
            self, "Save the import template", "VEYRA_Product_Import_Template.xlsx", XLSX_FILTER
        )
        if not path:
            return
        try:
            written = generate_template(path)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        self.banner.show_message(f"Template saved to {written}.", "success")

    def _render_preview(self) -> None:
        preview = self.preview
        if preview is None:
            self.counts.setText("")
            self.rows_table.set_rows([])
            self.errors_table.set_rows([])
            self.tabs.setTabText(1, "Errors (0)")
            self.commit.setEnabled(False)
            self.export_errors.hide()
            return

        counts = preview.summary_counts()
        self.counts.setText(
            f"{counts['total']} rows read:  {counts['add']} to add,  "
            f"{counts['update']} to update,  {counts['rejected']} rejected."
        )
        if preview.categories_to_create:
            self.counts.setText(
                self.counts.text()
                + f"  New categories: {', '.join(preview.categories_to_create)}."
            )

        rows = []
        for row in preview.add:
            rows.append([row.row_number, row.code, row.name, row.category or "-",
                         StatusBadge("Add", "success"), "New product."])
        for row in preview.update:
            rows.append([row.row_number, row.code, row.name, row.category or "-",
                         StatusBadge("Update", "info"),
                         "; ".join(row.changes) if row.changes else "No master-data changes."])
        for rejected in preview.rejected:
            problems = "; ".join(str(error) for error in rejected.errors)
            rows.append([rejected.row_number,
                         str(rejected.values.get("Product Code") or ""),
                         str(rejected.values.get("Product Name") or ""),
                         "-", StatusBadge("Rejected", "danger"), problems])
        self.rows_table.set_rows(rows)

        self.errors_table.set_rows([
            [error.row, error.column, error.message]
            for rejected in preview.rejected
            for error in rejected.errors
        ])
        self.tabs.setTabText(1, f"Errors ({len(preview.rejected)} rows)")
        self.tabs.setTabEnabled(1, bool(preview.rejected))

        self.commit.setEnabled(preview.is_valid)
        self.export_errors.setVisible(bool(preview.rejected))
        if preview.rejected:
            self.banner.show_message(
                "Fix or remove the rejected rows in the workbook, then preview again. "
                "Valid rows can still be imported.",
                "warning",
            )
        else:
            self.banner.clear()

    def _export_errors(self) -> None:
        if self.preview is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save the error report", "VEYRA_Import_Errors.xlsx", XLSX_FILTER
        )
        if not path:
            return
        try:
            written = import_service.write_error_report(self.preview, path)
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        self.banner.show_message(f"Error report saved to {written}.", "success")

    def _commit(self) -> None:
        if self.preview is None or not self.preview.is_valid:
            return
        self.busy.start("Writing products to the database...")
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.processEvents()
            self.summary = import_service.commit_import(self.preview)
        except VeyraError as error:
            logger.warning("Import commit failed: %s", error.message)
            self.busy.stop()
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            reference = log_unexpected(logger, "import commit", exc)
            self.busy.stop()
            self.banner.show_message(
                f"The import failed and nothing was saved. Reference {reference}.", "danger"
            )
            return
        self.busy.stop()
        self.accept()
