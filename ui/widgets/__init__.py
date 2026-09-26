"""Reusable UI building blocks shared by every page."""

from ui.widgets.badge import StatusBadge, status_kind
from ui.widgets.banner import Banner
from ui.widgets.busy import BusyOverlay
from ui.widgets.card import Card, KpiCard, MetricRow
from ui.widgets.charts import DonutChart, LineChart
from ui.widgets.fields import (
    Field,
    IntSpin,
    MoneySpin,
    SearchInput,
    TextArea,
)
from ui.widgets.images import avatar_pixmap, product_pixmap
from ui.widgets.table import DataTable
from ui.widgets.toast import ToastHost

__all__ = [
    "Banner",
    "BusyOverlay",
    "Card",
    "DataTable",
    "DonutChart",
    "Field",
    "IntSpin",
    "KpiCard",
    "LineChart",
    "MetricRow",
    "MoneySpin",
    "SearchInput",
    "StatusBadge",
    "TextArea",
    "ToastHost",
    "avatar_pixmap",
    "product_pixmap",
    "status_kind",
]
