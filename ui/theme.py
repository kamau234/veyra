"""Design tokens and Qt stylesheet generation (blueprint section 4)."""

from __future__ import annotations

from dataclasses import dataclass

from core.paths import FONT_DIR

#: Fallbacks used when the bundled font cannot be registered.
FALLBACK_FAMILIES = (
    "Segoe UI",
    "Inter",
    "Roboto",
    "Helvetica Neue",
    "Arial",
    "sans-serif",
)

_registered_families: list[str] = []


def register_fonts() -> tuple[str, ...]:
    """Load the TTFs shipped in ``assets/fonts`` so text renders everywhere.

    Windows machines without the fonts named in the stylesheet (and headless
    render targets) fall back to boxes, so VEYRA carries its own family and
    puts it first in every rule. Registration is idempotent per process.
    """
    if not _registered_families:
        from PySide6.QtGui import QFontDatabase, QGuiApplication

        if QGuiApplication.instance() is None:
            return ()

        for path in sorted(FONT_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(path))
            if font_id >= 0:
                for family in QFontDatabase.applicationFontFamilies(font_id):
                    if family not in _registered_families:
                        _registered_families.append(family)
    return tuple(_registered_families)


def font_stack() -> str:
    """CSS font-family list: bundled family first, then system fallbacks."""
    families = list(register_fonts())
    families += [name for name in FALLBACK_FAMILIES if name not in families]
    quoted = [f'"{name}"' if name != "sans-serif" else name for name in families]
    return ", ".join(quoted)


def primary_family() -> str | None:
    """The bundled family name, or None when registration failed."""
    families = register_fonts()
    return families[0] if families else None


@dataclass(frozen=True)
class Theme:
    name: str
    app_background: str
    sidebar: str
    sidebar_text: str
    sidebar_muted: str
    sidebar_active: str
    surface: str
    surface_alt: str
    primary: str
    primary_hover: str
    primary_text: str
    success: str
    warning: str
    danger: str
    text: str
    muted: str
    border: str
    hover: str
    selected: str

    def badge_colors(self, status: str) -> tuple[str, str]:
        """(background, foreground) for a status badge."""
        mapping = {
            "success": (self.success, "#FFFFFF"),
            "warning": (self.warning, "#1F2937"),
            "danger": (self.danger, "#FFFFFF"),
            "info": (self.primary, "#FFFFFF"),
            "neutral": (self.hover, self.muted),
        }
        return mapping.get(status, mapping["neutral"])


LIGHT = Theme(
    name="Light",
    app_background="#F5F7FA",
    sidebar="#111827",
    sidebar_text="#E5E7EB",
    sidebar_muted="#9CA3AF",
    sidebar_active="#2563EB",
    surface="#FFFFFF",
    surface_alt="#F9FAFB",
    primary="#2563EB",
    primary_hover="#1D4ED8",
    primary_text="#FFFFFF",
    success="#16A34A",
    warning="#F59E0B",
    danger="#DC2626",
    text="#111827",
    muted="#6B7280",
    border="#E5E7EB",
    hover="#F3F4F6",
    selected="#DBEAFE",
)

DARK = Theme(
    name="Dark",
    app_background="#0B1220",
    sidebar="#070C16",
    sidebar_text="#E5E7EB",
    sidebar_muted="#94A3B8",
    sidebar_active="#2563EB",
    surface="#111827",
    surface_alt="#161F31",
    primary="#3B82F6",
    primary_hover="#2563EB",
    primary_text="#FFFFFF",
    success="#22C55E",
    warning="#F59E0B",
    danger="#EF4444",
    text="#F9FAFB",
    muted="#94A3B8",
    border="#1F2A3D",
    hover="#1B2436",
    selected="#1E3A5F",
)

THEMES = {"Light": LIGHT, "Dark": DARK}

#: Base UI font size in pixels per Settings option.
FONT_SCALE = {"Small": 12, "Normal": 13, "Large": 15}


def resolve_theme(name: str | None) -> Theme:
    """Map a settings value to a Theme; 'System' follows the OS preference."""
    key = (name or "").strip().capitalize()
    if key in THEMES:
        return THEMES[key]
    if key == "System":
        return DARK if _system_prefers_dark() else LIGHT
    return LIGHT


def _system_prefers_dark() -> bool:
    from PySide6.QtGui import QGuiApplication

    style_hints = QGuiApplication.styleHints()
    scheme = getattr(style_hints, "colorScheme", lambda: None)()
    return bool(scheme is not None and str(scheme).endswith("Dark"))


def font_sizes(base: int) -> dict[str, int]:
    return {
        "base": base,
        "small": max(base - 1, 9),
        "tiny": max(base - 2, 8),
        "h3": base + 1,
        "h2": base + 3,
        "h1": base + 7,
        "kpi": base + 11,
    }


def stylesheet(theme: Theme, font_size: str = "Normal") -> str:
    base = FONT_SCALE.get(font_size, FONT_SCALE["Normal"])
    sizes = font_sizes(base)
    radius = 8
    family = font_stack()

    return f"""
* {{
    font-family: {family};
    font-size: {sizes['base']}px;
    color: {theme.text};
}}

QWidget#AppRoot {{ background: {theme.app_background}; }}

/* ---------------- sidebar ---------------- */
QFrame#Sidebar {{ background: {theme.sidebar}; border: none; }}
QLabel#BrandTitle {{
    color: #FFFFFF; font-size: {sizes['h2']}px; font-weight: 700; letter-spacing: 2px;
}}
QLabel#BrandSubtitle {{ color: {theme.sidebar_muted}; font-size: {sizes['small']}px; }}
QLabel#SidebarSection {{
    color: {theme.sidebar_muted}; font-size: {sizes['tiny']}px; font-weight: 700;
    letter-spacing: 1px; padding: 10px 14px 4px 14px;
}}
QPushButton#NavButton {{
    background: transparent; color: {theme.sidebar_text}; border: none;
    border-radius: {radius}px; padding: 9px 12px; text-align: left;
    font-size: {sizes['base']}px; font-weight: 600;
}}
QPushButton#NavButton:hover {{ background: rgba(255, 255, 255, 0.07); }}
QPushButton#NavButton:checked {{
    background: {theme.sidebar_active}; color: #FFFFFF;
}}
QLabel#OwnerName {{ color: #FFFFFF; font-size: {sizes['base']}px; font-weight: 600; }}
QLabel#OwnerRole {{ color: {theme.sidebar_muted}; font-size: {sizes['small']}px; }}

/* ---------------- header ---------------- */
QFrame#Header {{ background: transparent; border: none; }}
QLabel#PageTitle {{ font-size: {sizes['h1']}px; font-weight: 700; color: {theme.text}; }}
QLabel#PageSubtitle {{ font-size: {sizes['small']}px; color: {theme.muted}; }}

/* ---------------- cards ---------------- */
QFrame#Card {{
    background: {theme.surface}; border: 1px solid {theme.border};
    border-radius: {radius + 2}px;
}}
QLabel#CardTitle {{ font-size: {sizes['h3']}px; font-weight: 700; color: {theme.text}; }}
QLabel#CardSubtitle {{ font-size: {sizes['small']}px; color: {theme.muted}; }}
QLabel#KpiValue {{ font-size: {sizes['kpi']}px; font-weight: 700; color: {theme.text}; }}
QLabel#KpiLabel {{
    font-size: {sizes['small']}px; color: {theme.muted}; font-weight: 600;
    letter-spacing: 0.3px;
}}
QLabel#KpiHint {{ font-size: {sizes['tiny']}px; color: {theme.muted}; }}
QFrame#KpiAccent {{ border: none; border-radius: 3px; }}
QLabel#MetricValue {{ font-size: {sizes['h3']}px; font-weight: 700; }}
QLabel#MetricLabel {{ font-size: {sizes['small']}px; color: {theme.muted}; }}
QLabel#EmptyState {{
    color: {theme.muted}; font-size: {sizes['base']}px; padding: 18px;
}}
QLabel#EmptyStateTitle {{
    color: {theme.text}; font-size: {sizes['h3']}px; font-weight: 700; padding-bottom: 2px;
}}

/* ---------------- inputs ---------------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QDateEdit {{
    background: {theme.surface}; color: {theme.text};
    border: 1px solid {theme.border}; border-radius: {radius - 2}px;
    padding: 6px 9px; selection-background-color: {theme.primary};
    min-height: {sizes['base'] + 10}px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus, QDateEdit:focus {{
    border: 1px solid {theme.primary};
}}
QLineEdit[invalid="true"], QSpinBox[invalid="true"], QDoubleSpinBox[invalid="true"],
QComboBox[invalid="true"], QTextEdit[invalid="true"] {{
    border: 1px solid {theme.danger}; background: {theme.surface};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {theme.muted}; background: {theme.surface_alt};
}}
QLabel#FieldLabel {{ font-weight: 600; color: {theme.text}; padding-bottom: 1px; }}
QLabel#FieldError {{ color: {theme.danger}; font-size: {sizes['small']}px; }}
QLabel#FieldHint {{ color: {theme.muted}; font-size: {sizes['small']}px; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {theme.surface}; color: {theme.text};
    border: 1px solid {theme.border}; selection-background-color: {theme.selected};
    outline: none;
}}
QCheckBox {{ spacing: 7px; color: {theme.text}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {theme.border}; background: {theme.surface};
}}
QCheckBox::indicator:checked {{ background: {theme.primary}; border-color: {theme.primary}; }}
QRadioButton {{ spacing: 7px; color: {theme.text}; }}
QRadioButton::indicator {{
    width: 15px; height: 15px; border-radius: 8px;
    border: 1px solid {theme.border}; background: {theme.surface};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {theme.primary}; background: {theme.surface};
}}

/* ---------------- buttons ---------------- */
QPushButton {{
    background: {theme.surface}; color: {theme.text};
    border: 1px solid {theme.border}; border-radius: {radius - 2}px;
    padding: 7px 14px; font-weight: 600; min-height: {sizes['base'] + 8}px;
}}
QPushButton:hover {{ background: {theme.hover}; }}
QPushButton:disabled {{ color: {theme.muted}; background: {theme.surface_alt}; border-color: {theme.border}; }}
QPushButton[variant="primary"] {{
    background: {theme.primary}; color: {theme.primary_text}; border: none;
}}
QPushButton[variant="primary"]:hover {{ background: {theme.primary_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {theme.border}; color: {theme.muted}; }}
QPushButton[variant="success"] {{ background: {theme.success}; color: #FFFFFF; border: none; }}
QPushButton[variant="danger"] {{ background: {theme.danger}; color: #FFFFFF; border: none; }}
QPushButton[variant="ghost"] {{ background: transparent; border: none; color: {theme.primary}; }}
QPushButton[variant="ghost"]:hover {{ background: {theme.hover}; }}
QPushButton[variant="quiet"] {{ background: {theme.surface_alt}; border: 1px solid {theme.border}; }}

/* ---------------- tables ---------------- */
QTableWidget, QTableView, QTreeWidget {{
    background: {theme.surface}; alternate-background-color: {theme.surface_alt};
    border: 1px solid {theme.border}; border-radius: {radius}px;
    gridline-color: {theme.border}; selection-background-color: {theme.selected};
    selection-color: {theme.text};
}}
QHeaderView::section {{
    background: {theme.surface_alt}; color: {theme.muted};
    padding: 8px 10px; border: none; border-bottom: 1px solid {theme.border};
    font-weight: 700; font-size: {sizes['small']}px;
}}
QTableWidget::item, QTableView::item {{ padding: 6px 8px; border: none; }}
QTableCornerButton::section {{ background: {theme.surface_alt}; border: none; }}

/* ---------------- badges, tiles, misc ---------------- */
QLabel#Badge {{ border-radius: 9px; padding: 2px 9px; font-size: {sizes['tiny']}px; font-weight: 700; }}
QFrame#ProductTile {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: {radius + 2}px;
}}
QFrame#ProductTile[disabled="true"] {{ background: {theme.surface_alt}; }}
QLabel#TileName {{ font-weight: 600; color: {theme.text}; }}
QLabel#TilePrice {{ font-weight: 700; color: {theme.primary}; }}
QLabel#TileStock {{ font-size: {sizes['small']}px; color: {theme.muted}; }}
QFrame#CartPanel {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: {radius + 2}px;
}}
QFrame#TotalsRow {{ background: {theme.surface_alt}; border-radius: {radius}px; }}
QLabel#TotalValue {{ font-size: {sizes['h1']}px; font-weight: 700; color: {theme.text}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {theme.border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {theme.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {theme.border}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QTabWidget::pane {{ border: 1px solid {theme.border}; border-radius: {radius}px; background: {theme.surface}; }}
QTabBar::tab {{
    background: transparent; color: {theme.muted}; padding: 8px 14px;
    border: none; border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {theme.primary}; border-bottom: 2px solid {theme.primary}; }}

QGroupBox {{
    border: 1px solid {theme.border}; border-radius: {radius}px; margin-top: 12px;
    padding: 12px 10px 10px 10px; font-weight: 700;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {theme.muted}; }}

QToolTip {{
    background: {theme.sidebar}; color: {theme.sidebar_text};
    border: 1px solid {theme.sidebar}; padding: 5px 8px; border-radius: 4px;
}}
QMenu {{
    background: {theme.surface}; border: 1px solid {theme.border};
    border-radius: {radius - 2}px; padding: 4px;
}}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {theme.selected}; }}

QFrame#Toast {{
    background: {theme.sidebar}; border-radius: {radius}px; border: 1px solid {theme.sidebar};
}}
QLabel#ToastLabel {{ color: #FFFFFF; font-size: {sizes['base']}px; padding: 2px 4px; }}
QFrame#Banner {{ border-radius: {radius}px; padding: 8px; }}
QLabel#BannerLabel {{ padding: 2px 4px; font-size: {sizes['base']}px; }}

QProgressBar {{
    border: 1px solid {theme.border}; border-radius: 5px; background: {theme.surface_alt};
    text-align: center; height: 10px;
}}
QProgressBar::chunk {{ background: {theme.primary}; border-radius: 4px; }}

QDialog {{ background: {theme.app_background}; }}
"""


def current() -> Theme:
    """The theme currently installed on the application (Light as a default)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    return getattr(app, "veyra_theme", LIGHT) if app else LIGHT


def base_font_size(font_size: str = "Normal") -> int:
    return FONT_SCALE.get(font_size, FONT_SCALE["Normal"])


def apply_theme(app, theme_name: str, font_size: str) -> Theme:
    """Install the stylesheet for a theme/font-size pair on the whole app."""
    theme = resolve_theme(theme_name)
    app.veyra_theme = theme
    app.veyra_font_size = font_size
    _apply_app_font(app, font_size)
    _apply_palette(app, theme)
    app.setStyleSheet(stylesheet(theme, font_size))
    return theme


def _apply_palette(app, theme: Theme) -> None:
    """Cover the surfaces the stylesheet does not reach (scroll viewports...)."""
    from PySide6.QtGui import QColor, QPalette

    palette = app.palette()
    roles = {
        QPalette.ColorRole.Window: theme.app_background,
        QPalette.ColorRole.WindowText: theme.text,
        QPalette.ColorRole.Base: theme.app_background,
        QPalette.ColorRole.AlternateBase: theme.surface_alt,
        QPalette.ColorRole.Text: theme.text,
        QPalette.ColorRole.Button: theme.surface,
        QPalette.ColorRole.ButtonText: theme.text,
        QPalette.ColorRole.Highlight: theme.primary,
        QPalette.ColorRole.HighlightedText: theme.primary_text,
        QPalette.ColorRole.ToolTipBase: theme.sidebar,
        QPalette.ColorRole.ToolTipText: theme.sidebar_text,
        QPalette.ColorRole.PlaceholderText: theme.muted,
        QPalette.ColorRole.Light: theme.border,
        QPalette.ColorRole.Mid: theme.border,
        QPalette.ColorRole.Dark: theme.sidebar,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    app.setPalette(palette)


def _apply_app_font(app, font_size: str) -> None:
    """Set the widget-level font too, for anything the stylesheet misses."""
    from PySide6.QtGui import QFont

    family = primary_family()
    if not family:
        return
    font = app.font()
    font.setFamily(family)
    font.setPixelSize(FONT_SCALE.get(font_size, FONT_SCALE["Normal"]))
    app.setFont(font)
