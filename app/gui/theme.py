from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    tokens: dict[str, str]
    stylesheet: str


BRAND_BLUE = {
    "50": "#EFF6FF",
    "100": "#DBEAFE",
    "200": "#BFDBFE",
    "300": "#93C5FD",
    "400": "#60A5FA",
    "500": "#3B82F6",
    "600": "#2563EB",
    "700": "#1D4ED8",
    "800": "#1E40AF",
    "900": "#1E3A8A",
}

VOICE_TEAL = {
    "50": "#F0FDFA",
    "100": "#CCFBF1",
    "200": "#99F6E4",
    "300": "#5EEAD4",
    "400": "#2DD4BF",
    "500": "#14B8A6",
    "600": "#0D9488",
    "700": "#0F766E",
    "800": "#115E59",
    "900": "#134E4A",
}

WARM_ACCENT = {
    "50": "#FFFBEB",
    "100": "#FEF3C7",
    "200": "#FDE68A",
    "300": "#FCD34D",
    "400": "#FBBF24",
    "500": "#F59E0B",
    "600": "#D97706",
    "700": "#B45309",
    "800": "#92400E",
    "900": "#78350F",
}

DARK_TOKENS = {
    "canvas": "#0A0F1C",
    "surface": "#111827",
    "surface_raised": "#172033",
    "surface_soft": "#1C273A",
    "input": "#0E1626",
    "overlay": "#111827F2",
    "border_subtle": "#223047",
    "border": "#304158",
    "border_strong": "#43546D",
    "focus": "#60A5FA",
    "text_primary": "#F4F7FB",
    "text_secondary": "#B8C3D6",
    "text_muted": "#8290A7",
    "text_disabled": "#586579",
    "text_inverse": "#0A0F1C",
    "primary": "#3B82F6",
    "primary_hover": "#60A5FA",
    "primary_pressed": "#2563EB",
    "secondary_hover": "#243249",
    "destructive": "#EF4444",
    "success": "#22C55E",
    "info": "#38BDF8",
    "warning": "#F59E0B",
    "error": "#F05252",
    "pending": "#60A5FA",
    "running": "#2DD4BF",
    "skipped": "#94A3B8",
    "favorite": "#FBBF24",
    "selected_row": "#203A63",
}
DARK_TOKENS.update(
    {
        "app": "#0B1220",
        "panel": DARK_TOKENS["surface"],
        "elevated": DARK_TOKENS["surface_raised"],
        "hover": DARK_TOKENS["secondary_hover"],
        "accent_gold": DARK_TOKENS["favorite"],
        "accent_teal": VOICE_TEAL["500"],
    }
)

LIGHT_TOKENS = {
    "canvas": "#F3F6FA",
    "surface": "#FFFFFF",
    "surface_raised": "#FFFFFF",
    "surface_soft": "#EAF0F7",
    "input": "#FFFFFF",
    "overlay": "#FFFFFFF2",
    "border_subtle": "#E2E8F0",
    "border": "#C8D2DF",
    "border_strong": "#94A3B8",
    "focus": "#2563EB",
    "text_primary": "#172033",
    "text_secondary": "#475569",
    "text_muted": "#718096",
    "text_disabled": "#A0AEC0",
    "text_inverse": "#FFFFFF",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_pressed": "#1E40AF",
    "secondary_hover": "#E7EEF7",
    "destructive": "#DC2626",
    "success": "#15803D",
    "info": "#0369A1",
    "warning": "#B45309",
    "error": "#B91C1C",
    "pending": "#2563EB",
    "running": "#0F9488",
    "skipped": "#64748B",
    "favorite": "#B7791F",
    "selected_row": "#DCEAFE",
}
LIGHT_TOKENS.update(
    {
        "app": "#F4F7FB",
        "panel": LIGHT_TOKENS["surface"],
        "elevated": LIGHT_TOKENS["surface_raised"],
        "hover": LIGHT_TOKENS["secondary_hover"],
        "accent_gold": LIGHT_TOKENS["favorite"],
        "accent_teal": LIGHT_TOKENS["running"],
    }
)

STATUS_COLORS = {
    "pending": DARK_TOKENS["pending"],
    "running": DARK_TOKENS["warning"],
    "completed": DARK_TOKENS["success"],
    "failed": "#EF4444",
    "skipped": DARK_TOKENS["skipped"],
}


def _stylesheet(tokens: dict[str, str]) -> str:
    return f"""
QWidget{{background:{tokens['app']};color:{tokens['text_primary']};font-size:13px;font-family:Segoe UI;selection-background-color:{tokens['selected_row']};}}
QWidget:focus{{outline:1px solid {tokens['focus']};}}
QToolTip{{background:{tokens['elevated']};color:{tokens['text_primary']};border:1px solid {tokens['border']};padding:5px;}}
QGroupBox{{background:{tokens['panel']};border:1px solid {tokens['border']};border-radius:8px;margin-top:10px;padding:10px 8px 8px 8px;font-weight:600;}}
QGroupBox::title{{color:{tokens['text_secondary']};subcontrol-origin:margin;left:10px;padding:0 4px;}}
QFrame#card{{background:{tokens['panel']};border:1px solid {tokens['border']};border-radius:8px;}}
QFrame#metricsStrip,QFrame#projectContextStrip,QFrame#generationActionBar{{background:transparent;border:0;}}
QFrame#metricPill{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:7px;}}
QLabel#metricCaption{{color:{tokens['text_secondary']};font-size:12px;font-weight:600;}}
QLabel#metricValue{{color:{tokens['text_primary']};font-size:15px;font-weight:800;}}
QLabel#compactSourceSummary,QLabel#compactOutputSummary,QLabel#projectContextBar{{color:{tokens['text_secondary']};font-weight:600;}}
QToolBar#mainToolbar{{background:{tokens['panel']};border:0;border-bottom:1px solid {tokens['border_subtle']};spacing:6px;padding:3px 8px;}}
QToolBar#mainToolbar QToolButton{{padding:5px 8px;min-height:24px;border-color:transparent;background:transparent;}}
QTabWidget::pane{{border:1px solid {tokens['border_subtle']};border-radius:7px;background:{tokens['panel']};}}
QTabBar::tab{{background:{tokens['elevated']};color:{tokens['text_secondary']};padding:6px 10px;border:1px solid {tokens['border_subtle']};border-bottom:0;border-top-left-radius:6px;border-top-right-radius:6px;}}
QTabBar::tab:selected{{color:{tokens['text_primary']};background:{tokens['panel']};border-color:{tokens['border']};}}
QDockWidget{{titlebar-close-icon:url(none);titlebar-normal-icon:url(none);}}
QLabel#title{{font-size:28px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#subtitle,QLabel#cardCaption{{color:{tokens['text_secondary']};}}
QLabel#cardValue{{font-size:20px;font-weight:700;color:{tokens['text_primary']};}}
QLabel#previewTitle{{font-size:20px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#statusBadge{{border-radius:6px;padding:3px 7px;font-weight:700;}}
QLineEdit,QComboBox,QPlainTextEdit,QTableWidget,QAbstractSpinBox{{background:{tokens['input']};color:{tokens['text_primary']};border:1px solid {tokens['border']};border-radius:6px;padding:5px;}}
QLineEdit:disabled,QComboBox:disabled,QPlainTextEdit:disabled,QAbstractSpinBox:disabled{{color:{tokens['text_disabled']};background:{tokens['panel']};}}
QPushButton,QToolButton{{background:{tokens['elevated']};color:{tokens['text_primary']};border:1px solid {tokens['border']};border-radius:6px;padding:6px 10px;font-weight:600;min-height:22px;}}
QPushButton:hover,QToolButton:hover{{background:{tokens['hover']};border-color:{tokens['primary']};}}
QPushButton:pressed,QToolButton:pressed{{background:{tokens['primary_pressed']};}}
QPushButton#primaryButton{{background:{tokens['primary']};color:{tokens['text_inverse']};border-color:{tokens['primary']};min-height:28px;}}
QPushButton#destructiveButton{{background:{tokens['destructive']};color:{tokens['text_inverse']};border-color:{tokens['destructive']};}}
QPushButton:disabled,QToolButton:disabled{{color:{tokens['text_disabled']};background:{tokens['panel']};border-color:{tokens['border']};}}
QHeaderView::section{{background:{tokens['elevated']};color:{tokens['text_secondary']};padding:7px;border:0;border-right:1px solid {tokens['border']};}}
QTableWidget{{gridline-color:{tokens['border']};alternate-background-color:{tokens['panel']};}}
QTableWidget::item:selected{{background:{tokens['selected_row']};color:{tokens['text_primary']};}}
QProgressBar{{background:{tokens['input']};border:1px solid {tokens['border']};border-radius:6px;text-align:center;}}
QProgressBar::chunk{{background:{tokens['accent_teal']};border-radius:5px;}}
QSlider::groove:horizontal{{height:4px;background:{tokens['border']};border-radius:2px;}}
QSlider::handle:horizontal{{width:14px;margin:-6px 0;background:{tokens['primary']};border-radius:7px;}}
QScrollBar:vertical{{background:{tokens['panel']};width:12px;}}
QScrollBar::handle:vertical{{background:{tokens['border']};border-radius:6px;min-height:28px;}}
QScrollBar:horizontal{{background:{tokens['panel']};height:12px;}}
QScrollBar::handle:horizontal{{background:{tokens['border']};border-radius:6px;min-width:28px;}}
QMenuBar,QMenu{{background:{tokens['panel']};color:{tokens['text_primary']};}}
QMenu::item:selected,QMenuBar::item:selected{{background:{tokens['hover']};}}
"""


DARK_STYLE = _stylesheet(DARK_TOKENS)
LIGHT_STYLE = _stylesheet(LIGHT_TOKENS)


class ThemeManager:
    def __init__(self) -> None:
        self.settings = QSettings("S Talking", "S Talking")

    def current(self) -> str:
        return str(self.settings.value("theme/name", "Dark"))

    def save(self, name: str) -> None:
        self.settings.setValue("theme/name", name)

    def tokens(self, name: str | None = None) -> dict[str, str]:
        selected = self.effective_name(name or self.current())
        return DARK_TOKENS if selected == "Dark" else LIGHT_TOKENS

    def stylesheet(self, name: str | None = None) -> str:
        return DARK_STYLE if self.effective_name(name or self.current()) == "Dark" else LIGHT_STYLE

    @staticmethod
    def effective_name(name: str) -> str:
        if name == "System":
            palette = QApplication.palette()
            return "Dark" if palette.window().color().lightness() < 128 else "Light"
        return "Dark" if name == "Dark" else "Light"
