"""A4 landscape PDF export for every report.

One layout serves all reports: identification block, a repeating-header table,
an optional totals row, notes and a "Page X of Y" footer. Column widths are
measured from the actual text so a report with long product names still fits.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from core.dates import format_datetime
from core.exceptions import FileError
from core.logger import get_logger
from core.paths import resolve_image_path
from services.reporting_service import ReportColumn, ReportResult

logger = get_logger("reports.pdf")

PAGE_SIZE = landscape(A4)
MARGIN = 14 * mm
#: reportlab's Frame pads 6pt on every side; keep table widths inside it.
FRAME_PADDING = 6
CONTENT_WIDTH = PAGE_SIZE[0] - (2 * MARGIN) - (2 * FRAME_PADDING)

CURRENCY_LINE = "All amounts are in KES (KSh)."
EMPTY_MESSAGE = "No records for the selected period."

HEADER_FILL = colors.HexColor("#2563EB")
BORDER = colors.HexColor("#E5E7EB")
ZEBRA = colors.HexColor("#F8FAFC")
TOTALS_FILL = colors.HexColor("#F3F4F6")
TEXT = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_SIZE = 8
LEADING = 10


class _NumberedCanvas(pdf_canvas.Canvas):
    """Draws 'Page X of Y' — the total is only known after the last page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages: list[dict] = []

    def showPage(self):  # noqa: N802 - reportlab naming
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        self.setFont(FONT, 7.5)
        self.setFillColor(MUTED)
        self.drawString(MARGIN, 8 * mm, CURRENCY_LINE)
        self.drawRightString(
            PAGE_SIZE[0] - MARGIN, 8 * mm, f"Page {self._pageNumber} of {total}"
        )


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "business": ParagraphStyle(
            "business", fontName=FONT_BOLD, fontSize=14, leading=16, textColor=TEXT
        ),
        "title": ParagraphStyle(
            "title", fontName=FONT_BOLD, fontSize=12, leading=14, textColor=TEXT
        ),
        "meta": ParagraphStyle("meta", fontName=FONT, fontSize=8, leading=10, textColor=MUTED),
        "meta_right": ParagraphStyle(
            "meta_right", fontName=FONT, fontSize=8, leading=10, textColor=MUTED,
            alignment=TA_RIGHT,
        ),
        "note": ParagraphStyle("note", fontName=FONT, fontSize=7.5, leading=9.5, textColor=MUTED),
        "empty": ParagraphStyle(
            "empty", fontName=FONT, fontSize=10, leading=14, textColor=MUTED, alignment=TA_CENTER
        ),
    }


def _cell_styles() -> dict[str, ParagraphStyle]:
    styles = {}
    for align, name in (("left", TA_LEFT), ("right", TA_RIGHT)):
        styles[f"body_{align}"] = ParagraphStyle(
            f"body_{align}", fontName=FONT, fontSize=FONT_SIZE, leading=LEADING, alignment=name
        )
        styles[f"head_{align}"] = ParagraphStyle(
            f"head_{align}", fontName=FONT_BOLD, fontSize=FONT_SIZE, leading=LEADING,
            alignment=name, textColor=colors.white,
        )
    return styles


def _logo(stored_reference: str | None, height: float = 12 * mm):
    source = resolve_image_path(stored_reference)
    if source is None:
        return None
    try:
        image = Image(str(source))
    except Exception:  # noqa: BLE001 - a broken logo must not block an export
        logger.warning("Report logo %s could not be embedded", source)
        return None
    ratio = min((40 * mm) / image.imageWidth, height / image.imageHeight)
    image.drawWidth = image.imageWidth * ratio
    image.drawHeight = image.imageHeight * ratio
    return image


def _column_widths(columns: list[ReportColumn], rows: list[dict], totals: dict | None) -> list:
    """Share the page width in proportion to the widest text in each column."""
    sample = rows[:300]
    weights: list[float] = []
    for index, column in enumerate(columns):
        widest = stringWidth(column.label, FONT_BOLD, FONT_SIZE)
        for row in sample:
            text = column.format(row.get(column.key))
            widest = max(widest, stringWidth(text, FONT, FONT_SIZE))
        if totals and column.key in totals:
            widest = max(
                widest, stringWidth(column.format(totals[column.key]), FONT_BOLD, FONT_SIZE)
            )
        # Padding for the cell margins plus a floor so short columns stay usable.
        weights.append(max(widest + 6, 28))

    scale = CONTENT_WIDTH / sum(weights)
    return [weight * scale for weight in weights]


def _header_block(report: ReportResult, business_name: str, logo_path: str | None) -> list:
    styles = _styles()
    left: list = []
    logo = _logo(logo_path)
    if logo is not None:
        left.append(logo)
        left.append(Spacer(1, 2 * mm))
    left.append(Paragraph(escape(business_name), styles["business"]))
    left.append(Paragraph(escape(report.title), styles["title"]))

    right_lines = []
    if report.subtitle:
        right_lines.append(escape(report.subtitle))
    if report.period_label:
        right_lines.append(f"Period: {escape(report.period_label)}")
    right_lines.append(f"Generated: {format_datetime(report.generated_at)}")
    right_lines.append(f"Records: {report.row_count:,}")
    right = [Paragraph("<br/>".join(right_lines), styles["meta_right"])]

    block = Table([[left, right]], colWidths=[CONTENT_WIDTH * 0.55, CONTENT_WIDTH * 0.45])
    block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [block, Spacer(1, 2 * mm),
            HRFlowable(width="100%", thickness=1, color=HEADER_FILL), Spacer(1, 4 * mm)]


def _data_table(
    report: ReportResult, cell_styles: dict[str, ParagraphStyle]
) -> Table:
    widths = _column_widths(report.columns, report.rows, report.totals)
    data: list[list] = [[
        Paragraph(escape(column.label), cell_styles[f"head_{column.align}"])
        for column in report.columns
    ]]
    for row in report.rows:
        data.append([
            Paragraph(escape(column.format(row.get(column.key))),
                      cell_styles[f"body_{column.align}"])
            for column in report.columns
        ])

    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_FILL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ])
    for index in range(1, len(data)):
        if index % 2 == 0:
            style.add("BACKGROUND", (0, index), (-1, index), ZEBRA)

    if report.totals and report.rows:
        totals_row = []
        for position, column in enumerate(report.columns):
            if position == 0:
                totals_row.append(Paragraph("TOTAL", cell_styles["body_left"]))
                continue
            value = report.totals.get(column.key)
            text = column.format(value) if value is not None else ""
            totals_row.append(Paragraph(escape(text), cell_styles[f"body_{column.align}"]))
        data.append(totals_row)
        last = len(data) - 1
        style.add("BACKGROUND", (0, last), (-1, last), TOTALS_FILL)
        style.add("LINEABOVE", (0, last), (-1, last), 0.9, TEXT)

    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(style)
    return table


def export_pdf(
    report: ReportResult,
    destination: Path | str,
    *,
    business_name: str,
    logo_path: str | None = None,
) -> Path:
    """Write ``report`` to ``destination`` as a landscape A4 PDF."""
    path = Path(destination)
    cell_styles = _cell_styles()
    styles = _styles()

    story: list = _header_block(report, business_name, logo_path)
    if report.is_empty:
        story.append(Spacer(1, 10 * mm))
        story.append(Paragraph(EMPTY_MESSAGE, styles["empty"]))
    else:
        story.append(_data_table(report, cell_styles))

    if report.notes:
        story.append(Spacer(1, 5 * mm))
        for note in report.notes:
            story.append(Paragraph(escape(str(note)), styles["note"]))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = SimpleDocTemplate(
            str(path),
            pagesize=PAGE_SIZE,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=MARGIN + 4,
            title=f"{report.title} - {business_name}",
            author=business_name,
            subject=report.period_label or report.title,
        )
        document.build(story, canvasmaker=_NumberedCanvas)
    except OSError as exc:
        logger.error("PDF export to %s failed: %s", path, exc)
        raise FileError("The PDF could not be saved.", detail=repr(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - reportlab internals surface as FileError
        logger.error("PDF export to %s failed", path, exc_info=exc)
        raise FileError("The PDF report could not be generated.", detail=repr(exc)) from exc

    logger.info("PDF export '%s': %d rows -> %s", report.title, report.row_count, path)
    return path
