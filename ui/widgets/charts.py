"""Charts painted with QPainter — no extra plotting dependency.

Two views cover the dashboard: a sales trend line and a stock-status donut.
Both degrade gracefully to an explanatory message when there is no data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from core.money import to_money
from ui import theme


@dataclass
class SeriesPoint:
    label: str
    value: Decimal


def _nice_ceiling(value: float) -> float:
    """Round an axis maximum up to a readable number."""
    if value <= 0:
        return 10.0
    magnitude = 10 ** int(len(str(int(value))) - 1)
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10):
        candidate = magnitude * step
        if candidate >= value:
            return float(candidate)
    return float(magnitude * 10)


class ChartWidget(QWidget):
    """Base class handling the empty-state message and repaints."""

    def __init__(self, parent: QWidget | None = None, *, minimum_height: int = 180):
        super().__init__(parent)
        self.setMinimumHeight(minimum_height)
        self._empty_message = "No data for this period yet."
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_empty_message(self, message: str) -> None:
        self._empty_message = message

    def _paint_empty(self, painter: QPainter) -> None:
        current = theme.current()
        painter.setPen(QColor(current.muted))
        font = QFont()
        font.setPixelSize(theme.font_sizes(theme.base_font_size())["base"])
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_message)


class LineChart(ChartWidget):
    """Area/line chart of KSh totals over a series of days."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, minimum_height=200)
        self._points: list[SeriesPoint] = []

    def set_data(self, points: list[SeriesPoint] | list[tuple[str, Decimal]]) -> None:
        self._points = [
            point if isinstance(point, SeriesPoint) else SeriesPoint(str(point[0]), to_money(point[1]))
            for point in points
        ]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current = theme.current()

        if not self._points:
            self._paint_empty(painter)
            painter.end()
            return

        left, right, top, bottom = 62, 16, 14, 30
        plot = QRectF(left, top, max(self.width() - left - right, 10), max(self.height() - top - bottom, 10))
        values = [float(point.value) for point in self._points]
        ceiling = _nice_ceiling(max(values))

        sizes = theme.font_sizes(theme.base_font_size())
        label_font = QFont()
        label_font.setPixelSize(sizes["small"])
        painter.setFont(label_font)

        # gridlines + y labels
        steps = 4
        for index in range(steps + 1):
            ratio = index / steps
            y = plot.bottom() - plot.height() * ratio
            painter.setPen(QPen(QColor(current.border), 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(QColor(current.muted))
            painter.drawText(
                QRectF(0, y - 8, plot.left() - 8, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{ceiling * ratio:,.0f}",
            )

        def position(index: int, value: float) -> QPointF:
            if len(self._points) == 1:
                x = plot.center().x()
            else:
                x = plot.left() + plot.width() * index / (len(self._points) - 1)
            y = plot.bottom() - (plot.height() * (value / ceiling) if ceiling else 0)
            return QPointF(x, y)

        positions = [position(index, value) for index, value in enumerate(values)]

        area = QPainterPath()
        area.moveTo(positions[0].x(), plot.bottom())
        for point in positions:
            area.lineTo(point)
        area.lineTo(positions[-1].x(), plot.bottom())
        area.closeSubpath()
        fill = QColor(current.primary)
        fill.setAlpha(38)
        painter.fillPath(area, fill)

        painter.setPen(QPen(QColor(current.primary), 2.4))
        for start, end in zip(positions, positions[1:]):
            painter.drawLine(start, end)

        painter.setBrush(QColor(current.surface))
        for point in positions:
            painter.setPen(QPen(QColor(current.primary), 2))
            painter.drawEllipse(point, 3.2, 3.2)

        # x labels (thinned so they never overlap)
        painter.setPen(QColor(current.muted))
        every = max(1, len(self._points) // 7)
        for index, point in enumerate(self._points):
            if index % every and index != len(self._points) - 1:
                continue
            anchor = positions[index]
            painter.drawText(
                QRectF(anchor.x() - 40, plot.bottom() + 6, 80, 18),
                Qt.AlignmentFlag.AlignCenter,
                point.label,
            )

        painter.end()


@dataclass
class Slice:
    label: str
    value: int
    color: str


class DonutChart(ChartWidget):
    """Stock status distribution with a legend and a total in the middle."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, minimum_height=200)
        self._slices: list[Slice] = []
        self._center_label = "Products"

    def set_data(self, slices: list[Slice], *, center_label: str = "Products") -> None:
        self._slices = list(slices)
        self._center_label = center_label
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current = theme.current()
        total = sum(max(slice_.value, 0) for slice_ in self._slices)

        if total <= 0:
            self._paint_empty(painter)
            painter.end()
            return

        legend_width = 130
        diameter = min(self.height() - 20, self.width() - legend_width - 30)
        diameter = max(diameter, 60)
        rect = QRectF(
            14,
            (self.height() - diameter) / 2,
            diameter,
            diameter,
        )

        start_angle = 90 * 16
        for slice_ in self._slices:
            if slice_.value <= 0:
                continue
            span = int(360 * 16 * slice_.value / total)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(slice_.color))
            painter.drawPie(rect, start_angle, span)
            start_angle -= span

        hole = QRectF(
            rect.left() + diameter * 0.26,
            rect.top() + diameter * 0.26,
            diameter * 0.48,
            diameter * 0.48,
        )
        painter.setBrush(QColor(current.surface))
        painter.drawEllipse(hole)

        sizes = theme.font_sizes(theme.base_font_size())
        total_font = QFont()
        total_font.setPixelSize(sizes["h2"])
        total_font.setBold(True)
        painter.setFont(total_font)
        painter.setPen(QColor(current.text))
        painter.drawText(hole, Qt.AlignmentFlag.AlignCenter, f"{total:,}")

        legend_x = rect.right() + 18
        legend_font = QFont()
        legend_font.setPixelSize(sizes["small"])
        painter.setFont(legend_font)
        row_height = 22
        y = self.height() / 2 - (len(self._slices) * row_height) / 2
        for slice_ in self._slices:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(slice_.color))
            painter.drawRoundedRect(QRectF(legend_x, y + 4, 10, 10), 2, 2)
            painter.setPen(QColor(current.muted))
            painter.drawText(
                QRectF(legend_x + 16, y, max(self.width() - legend_x - 16, 40), row_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{slice_.label}  {slice_.value:,}",
            )
            y += row_height

        painter.end()


class BarChart(ChartWidget):
    """Simple horizontal bars, used for top-selling products."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, minimum_height=160)
        self._points: list[SeriesPoint] = []

    def set_data(self, points: list[SeriesPoint]) -> None:
        self._points = list(points)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current = theme.current()
        if not self._points:
            self._paint_empty(painter)
            painter.end()
            return

        sizes = theme.font_sizes(theme.base_font_size())
        font = QFont()
        font.setPixelSize(sizes["small"])
        painter.setFont(font)

        label_width = min(150, int(self.width() * 0.4))
        row_height = max(self.height() / len(self._points), 22)
        highest = max(float(point.value) for point in self._points) or 1.0

        for index, point in enumerate(self._points):
            top = index * row_height + 4
            painter.setPen(QColor(current.text))
            painter.drawText(
                QRectF(0, top, label_width - 8, row_height - 8),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                point.label,
            )
            track = QRectF(
                label_width,
                top + (row_height - 16) / 2,
                self.width() - label_width - 70,
                10,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(current.hover))
            painter.drawRoundedRect(track, 5, 5)
            width = track.width() * (float(point.value) / highest)
            painter.setBrush(QColor(current.primary))
            painter.drawRoundedRect(QRectF(track.left(), track.top(), max(width, 4), 10), 5, 5)
            painter.setPen(QColor(current.muted))
            painter.drawText(
                QRectF(track.right() + 6, top, 64, row_height - 8),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{point.value:,.0f}",
            )
        painter.end()


def stock_status_colors() -> dict[str, str]:
    current = theme.current()
    return {
        "In Stock": current.success,
        "Low Stock": current.warning,
        "Out of Stock": current.danger,
    }


def render_to_pixmap(widget: QWidget, size) -> QPixmap:
    """Snapshot a chart, used when exporting a report to PDF."""
    pixmap = QPixmap(size)
    widget.render(pixmap)
    return pixmap
