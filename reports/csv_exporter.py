"""CSV export for reports.

The file is written as UTF-8 with a BOM so Excel recognises the encoding and
opens it with the correct separators, and carries a small identification block
above the column headers so a printed/forwarded file stays traceable.
"""

from __future__ import annotations

import csv
from pathlib import Path

from core.dates import format_datetime
from core.exceptions import FileError
from core.logger import get_logger
from services.reporting_service import ReportResult

logger = get_logger("reports.csv")

CURRENCY_LINE = "Currency: KES (KSh)"
EMPTY_MESSAGE = "No records for the selected period."


def export_csv(
    report: ReportResult,
    destination: Path | str,
    *,
    business_name: str,
    logo_path: str | None = None,
) -> Path:
    """Write ``report`` to ``destination`` as CSV and return the path written.

    ``logo_path`` is accepted so every exporter shares one signature; CSV has
    no way to embed an image, so it is ignored here.
    """
    path = Path(destination)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([business_name])
            writer.writerow([report.title])
            if report.period_label:
                writer.writerow([f"Period: {report.period_label}"])
            writer.writerow([f"Generated: {format_datetime(report.generated_at)}"])
            writer.writerow([CURRENCY_LINE])
            writer.writerow([])

            writer.writerow([column.label for column in report.columns])
            if report.is_empty:
                writer.writerow([EMPTY_MESSAGE])
            for row in report.rows:
                writer.writerow(
                    [column.format(row.get(column.key)) for column in report.columns]
                )
            if report.totals:
                writer.writerow(_totals_row(report))
    except OSError as exc:
        logger.error("CSV export to %s failed: %s", path, exc)
        raise FileError("The CSV file could not be written.", detail=str(exc)) from exc

    logger.info("CSV export '%s': %d rows -> %s", report.title, report.row_count, path)
    return path


def _totals_row(report: ReportResult) -> list[str]:
    """'TOTAL' plus formatted totals; keys absent from the columns are dropped."""
    cells = ["TOTAL"]
    for column in report.columns[1:]:
        value = (report.totals or {}).get(column.key)
        cells.append(column.format(value) if value is not None else "")
    return cells
