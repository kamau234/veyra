"""Reports page: pick a report and a period, review it, export CSV/XLSX/PDF.

Blueprint 11: every export states the business name, report name, date range
and the currency (KSh/KES). The grid is built from the report's own column
definitions so a new report needs no UI change.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from core.constants import Period
from core.dates import resolve_period
from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from reports.csv_exporter import export_csv
from reports.excel_exporter import export_xlsx
from reports.pdf_reports import export_pdf
from services import settings_service
from services.reporting_service import REPORT_NAMES, run_report
from ui.widgets.banner import Banner
from ui.widgets.fields import Combo
from ui.widgets.busy import BusyOverlay
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.reports")

PURPOSES = {
    "Sales Report": "Measure sales over a selected period.",
    "Product Sales Report": "Identify product movement through sales.",
    "Inventory Report": "Review current stock levels and stock value.",
    "Stock Movement Report": "Explain every stock change in the ledger.",
    "Low Stock Report": "Identify products that need reordering.",
    "Estimated Gross Profit Report": "Estimate retail margin from sales.",
}

PERIOD_FREE = ("Inventory Report", "Low Stock Report")

EXPORTERS = {
    "Export CSV": (export_csv, "Comma-separated values (*.csv)", ".csv"),
    "Export Excel": (export_xlsx, "Excel workbooks (*.xlsx)", ".xlsx"),
    "Export PDF": (export_pdf, "PDF files (*.pdf)", ".pdf"),
}


class ReportsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self.settings = settings_service.get_settings()
        self.report = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(12)

        self.banner = Banner(self)
        layout.addWidget(self.banner)

        splitter = QSplitter()
        splitter.addWidget(self._build_picker())
        splitter.addWidget(self._build_results())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 900])
        layout.addWidget(splitter, stretch=1)

        self.busy = BusyOverlay(self)
        self.report_list.setCurrentRow(0)
        self.run()

    # ---------------------------------------------------------------- picker

    def _build_picker(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel("Reports")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        self.report_list = QListWidget()
        self.report_list.addItems(list(REPORT_NAMES))
        self.report_list.currentRowChanged.connect(self._report_changed)
        layout.addWidget(self.report_list, stretch=1)

        self.purpose = QLabel("")
        self.purpose.setObjectName("CardSubtitle")
        self.purpose.setWordWrap(True)
        layout.addWidget(self.purpose)

        layout.addWidget(QLabel("Period"))
        self.period_filter = Combo(list(Period.ALL))
        self.period_filter.setCurrentText(Period.THIS_MONTH)
        self.period_filter.currentIndexChanged.connect(self._period_changed)
        layout.addWidget(self.period_filter)

        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        for editor in (self.start_date, self.end_date):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd MMM yyyy")
            editor.dateChanged.connect(self.run)
            editor.hide()
            layout.addWidget(editor)

        run = QPushButton("Run Report")
        run.setProperty("variant", "primary")
        run.clicked.connect(self.run)
        layout.addWidget(run)
        return panel

    def _build_results(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self.result_title = QLabel("")
        self.result_title.setObjectName("CardTitle")
        header.addWidget(self.result_title)
        header.addStretch(1)
        self.export_buttons: dict[str, QPushButton] = {}
        for label in EXPORTERS:
            button = QPushButton(label)
            button.setProperty("variant", "quiet")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, text=label: self.export_report(text))
            header.addWidget(button)
            self.export_buttons[label] = button
        layout.addLayout(header)

        self.result_subtitle = QLabel("")
        self.result_subtitle.setObjectName("CardSubtitle")
        self.result_subtitle.setWordWrap(True)
        layout.addWidget(self.result_subtitle)

        self.table = DataTable()
        self.table.set_empty_state("Run a report to see its rows here.")
        layout.addWidget(self.table, stretch=1)

        self.notes = QLabel("")
        self.notes.setObjectName("FieldHint")
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)
        return panel

    # -------------------------------------------------------------- behaviour

    def _report_changed(self, row: int) -> None:
        name = self.current_report()
        self.purpose.setText(PURPOSES.get(name, ""))
        period_free = name in PERIOD_FREE
        self.period_filter.setEnabled(not period_free)
        self.start_date.setVisible(not period_free and self._is_custom())
        self.end_date.setVisible(not period_free and self._is_custom())
        if row >= 0:
            self.run()

    def _is_custom(self) -> bool:
        return self.period_filter.currentText() == Period.CUSTOM

    def _period_changed(self) -> None:
        custom = self._is_custom() and self.current_report() not in PERIOD_FREE
        self.start_date.setVisible(custom)
        self.end_date.setVisible(custom)
        self.run()

    def current_report(self) -> str:
        row = self.report_list.currentRow()
        names = list(REPORT_NAMES)
        return names[row] if 0 <= row < len(names) else names[0]

    def _range(self):
        custom = self._is_custom()
        return resolve_period(
            self.period_filter.currentText(),
            self.start_date.date().toPython() if custom else None,
            self.end_date.date().toPython() if custom else None,
        )

    def run(self) -> None:
        name = self.current_report()
        start, end = (None, None) if name in PERIOD_FREE else self._range()
        self.busy.start(f"Running {name}...")
        try:
            report = run_report(name, start=start, end=end)
        except VeyraError as error:
            self.busy.stop()
            self.report = None
            self.banner.show_message(error.message, "danger")
            self.table.set_columns([])
            self.table.set_rows([])
            self.result_title.setText(name)
            self.result_subtitle.setText("")
            self.notes.setText("")
            for button in self.export_buttons.values():
                button.setEnabled(False)
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            self.busy.stop()
            reference = log_unexpected(logger, f"report:{name}", exc)
            self.report = None
            self.banner.show_message(
                f"The report could not be produced. Reference {reference}.", "danger"
            )
            return
        self.busy.stop()
        self.banner.clear()
        self.report = report
        self._render(report)

    def _render(self, report) -> None:
        self.result_title.setText(report.title)
        subtitle = report.subtitle or report.period_label
        self.result_subtitle.setText(
            f"{subtitle} - {report.row_count:,} row(s) - currency KSh (KES)"
        )
        self.table.set_columns([
            Column(column.label, column.align, stretch=(column.align == "left" and index == 1))
            for index, column in enumerate(report.columns)
        ])

        rows = [[column.format(row.get(column.key)) for column in report.columns]
                for row in report.rows]
        if report.totals:
            rows.append([
                "TOTAL" if index == 0 else column.format(report.totals.get(column.key))
                for index, column in enumerate(report.columns)
            ])
        self.table.set_rows(rows)
        if report.is_empty:
            self.table.set_empty_state(
                "No rows match this period. Try a wider date range.",
                title="Nothing to report",
            )
        self.notes.setText(" ".join(report.notes))
        for button in self.export_buttons.values():
            button.setEnabled(True)

    # ----------------------------------------------------------------- export

    def export_report(self, label: str) -> None:
        if self.report is None:
            self.banner.show_message("Run a report before exporting it.", "info")
            return
        exporter, filter_text, suffix = EXPORTERS[label]
        default = (
            f"{self.report.title.replace(' ', '_')}_"
            f"{self.report.generated_at:%Y%m%d_%H%M}{suffix}"
        )
        path, _ = QFileDialog.getSaveFileName(self, label, default, filter_text)
        if not path:
            return
        self.busy.start("Exporting...")
        try:
            written = exporter(
                self.report,
                path,
                business_name=self.settings.business_name,
                logo_path=self.settings.logo_image,
            )
        except VeyraError as error:
            self.busy.stop()
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001
            self.busy.stop()
            reference = log_unexpected(logger, f"export:{label}", exc)
            self.banner.show_message(
                f"The export could not be written. Reference {reference}.", "danger"
            )
            return
        self.busy.stop()
        self.banner.clear()
        self.window_ref.notify(f"{self.report.title} saved to {written.name}.")

    # ------------------------------------------------------- shell callbacks

    def refresh(self) -> None:
        self.settings = settings_service.get_settings()
        self.run()
