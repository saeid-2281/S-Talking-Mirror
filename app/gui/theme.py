from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
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
    "surface": "#111C31",
    "surface_raised": "#16233A",
    "surface_soft": "#1C2C46",
    "input": "#0F1B31",
    "overlay": "#0F1A2EF2",
    "border_subtle": "#28405F",
    "border": "#365170",
    "border_strong": "#4F6D8E",
    "focus": "#60A5FA",
    "text_primary": "#F8FAFC",
    "text_secondary": "#D3DDEB",
    "text_muted": "#9FB0C7",
    "text_disabled": "#62748F",
    "text_inverse": "#FFFFFF",
    "primary": "#3B82F6",
    "primary_hover": "#60A5FA",
    "primary_pressed": "#2563EB",
    "secondary_hover": "#223551",
    "destructive": "#EF4444",
    "success": "#22C55E",
    "info": "#38BDF8",
    "warning": "#F59E0B",
    "error": "#F87171",
    "pending": "#60A5FA",
    "running": "#2DD4BF",
    "skipped": "#94A3B8",
    "favorite": "#FBBF24",
    "selected_row": "#254D78",
    "selected_text": "#FFFFFF",
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
    "surface_soft": "#EEF4FB",
    "input": "#FFFFFF",
    "overlay": "#FFFFFFF2",
    "border_subtle": "#D9E2EF",
    "border": "#C3D0E0",
    "border_strong": "#94A7C0",
    "focus": "#2563EB",
    "text_primary": "#152235",
    "text_secondary": "#52627A",
    "text_muted": "#708199",
    "text_disabled": "#9AA9BC",
    "text_inverse": "#FFFFFF",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "primary_pressed": "#1E40AF",
    "secondary_hover": "#E9F0F9",
    "destructive": "#DC2626",
    "success": "#15803D",
    "info": "#0369A1",
    "warning": "#B45309",
    "error": "#B91C1C",
    "pending": "#2563EB",
    "running": "#0F9488",
    "skipped": "#64748B",
    "favorite": "#B7791F",
    "selected_row": "#CFE2FF",
    "selected_text": "#10233F",
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

GRAPHITE_TOKENS = {
    "canvas": "#16181C",
    "surface": "#202329",
    "surface_raised": "#292D34",
    "surface_soft": "#30353D",
    "input": "#1B1E23",
    "overlay": "#202329F2",
    "border_subtle": "#3B414B",
    "border": "#4A5260",
    "border_strong": "#687384",
    "focus": "#7AA2F7",
    "text_primary": "#F3F4F6",
    "text_secondary": "#D1D5DB",
    "text_muted": "#A7AFBC",
    "text_disabled": "#737B87",
    "text_inverse": "#FFFFFF",
    "primary": "#4F7FEA",
    "primary_hover": "#6C95F2",
    "primary_pressed": "#3E67C7",
    "secondary_hover": "#373C45",
    "destructive": "#F05252",
    "success": "#34C778",
    "info": "#55B6E8",
    "warning": "#E6A23C",
    "error": "#F47676",
    "pending": "#7AA2F7",
    "running": "#3CC8B4",
    "skipped": "#9AA3AF",
    "favorite": "#E6B85C",
    "selected_row": "#3B4F6B",
    "selected_text": "#FFFFFF",
}
GRAPHITE_TOKENS.update(
    {
        "app": "#191C21",
        "panel": GRAPHITE_TOKENS["surface"],
        "elevated": GRAPHITE_TOKENS["surface_raised"],
        "hover": GRAPHITE_TOKENS["secondary_hover"],
        "accent_gold": GRAPHITE_TOKENS["favorite"],
        "accent_teal": GRAPHITE_TOKENS["running"],
    }
)

STATUS_COLORS = {
    "pending": DARK_TOKENS["pending"],
    "running": DARK_TOKENS["warning"],
    "completed": DARK_TOKENS["success"],
    "failed": "#EF4444",
    "skipped": DARK_TOKENS["skipped"],
}


def _build_palette(tokens: dict[str, str]) -> QPalette:
    """Create a coherent application palette for all palette()-based rules.

    Several professional workspace rules intentionally rely on Qt palette roles
    so legacy widgets and new components stay visually aligned. Without
    explicitly updating the palette, those selectors can inherit low-contrast
    platform defaults, which caused unreadable captions and muddy surfaces in
    the screenshots reported by the user.
    """

    palette = QPalette()
    base = QColor(tokens["surface"])
    elevated = QColor(tokens["surface_raised"])
    soft = QColor(tokens["surface_soft"])
    input_color = QColor(tokens["input"])
    window = QColor(tokens["app"])
    text = QColor(tokens["text_primary"])
    secondary = QColor(tokens["text_secondary"])
    disabled = QColor(tokens["text_disabled"])
    primary = QColor(tokens["primary"])
    highlight = QColor(tokens["selected_row"])
    inverse = QColor(tokens["text_inverse"])
    selected_text = QColor(tokens["selected_text"])
    border = QColor(tokens["border"])
    border_subtle = QColor(tokens["border_subtle"])

    palette.setColor(QPalette.Window, window)
    palette.setColor(QPalette.WindowText, text)
    palette.setColor(QPalette.Base, base)
    palette.setColor(QPalette.AlternateBase, soft)
    palette.setColor(QPalette.ToolTipBase, elevated)
    palette.setColor(QPalette.ToolTipText, text)
    palette.setColor(QPalette.Text, text)
    palette.setColor(QPalette.Button, elevated)
    palette.setColor(QPalette.ButtonText, text)
    palette.setColor(QPalette.BrightText, inverse)
    palette.setColor(QPalette.Highlight, highlight)
    palette.setColor(QPalette.HighlightedText, selected_text)
    palette.setColor(QPalette.PlaceholderText, QColor(tokens["text_muted"]))
    palette.setColor(QPalette.Light, soft.lighter(108))
    palette.setColor(QPalette.Midlight, border_subtle)
    palette.setColor(QPalette.Mid, secondary)
    palette.setColor(QPalette.Dark, border.darker(130))
    palette.setColor(QPalette.Shadow, window.darker(160))
    palette.setColor(QPalette.Link, primary)
    palette.setColor(QPalette.LinkVisited, QColor(tokens["primary_pressed"]))
    palette.setColor(QPalette.Active, QPalette.Button, elevated)
    palette.setColor(QPalette.Active, QPalette.Base, input_color)
    palette.setColor(QPalette.Inactive, QPalette.Button, elevated)
    palette.setColor(QPalette.Inactive, QPalette.Base, input_color)
    palette.setColor(QPalette.Disabled, QPalette.Text, disabled)
    palette.setColor(QPalette.Disabled, QPalette.WindowText, disabled)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, disabled)
    palette.setColor(QPalette.Disabled, QPalette.Highlight, border_subtle)
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, selected_text)
    return palette


def _stylesheet(tokens: dict[str, str]) -> str:
    return f"""
QWidget{{background:{tokens['app']};color:{tokens['text_primary']};font-size:13px;font-family:Segoe UI;selection-background-color:{tokens['selected_row']};selection-color:{tokens['selected_text']};}}
QWidget:focus{{outline:1px solid {tokens['focus']};}}
QToolTip{{background:{tokens['elevated']};color:{tokens['text_primary']};border:1px solid {tokens['border']};padding:5px;}}
QGroupBox{{background:{tokens['panel']};border:1px solid {tokens['border']};border-radius:8px;margin-top:10px;padding:10px 8px 8px 8px;font-weight:600;}}
QGroupBox::title{{color:{tokens['text_secondary']};subcontrol-origin:margin;left:10px;padding:0 4px;}}
QFrame#card{{background:{tokens['panel']};border:1px solid {tokens['border']};border-radius:8px;}}
QFrame#metricsStrip,QFrame#projectContextStrip,QFrame#generationActionBar{{background:transparent;border:0;}}
QFrame#metricPill{{background:transparent;border:0;border-right:1px solid {tokens['border_subtle']};border-radius:0;}}
QFrame#metricPill[active="true"]{{background:{tokens['surface_soft']};border-radius:6px;border-right:1px solid {tokens['focus']};}}
QLabel#metricIcon{{color:{tokens['focus']};font-size:13px;font-weight:800;}}
QLabel#metricCaption{{color:{tokens['text_secondary']};font-size:11px;font-weight:600;}}
QLabel#metricValue{{color:{tokens['text_primary']};font-size:14px;font-weight:800;}}
QFrame#emptyState{{background:transparent;border:0;}}
QLabel#emptyTitle{{font-size:20px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#emptyHelper{{color:{tokens['text_secondary']};}}
QLabel#compactSourceSummary,QLabel#compactOutputSummary,QLabel#projectContextBar{{color:{tokens['text_secondary']};font-weight:600;}}
QToolBar#mainToolbar{{background:{tokens['panel']};border:0;border-bottom:1px solid {tokens['border_subtle']};spacing:6px;padding:3px 8px;}}
QToolBar#mainToolbar QToolButton{{padding:5px 8px;min-height:24px;min-width:34px;border-color:transparent;background:transparent;}}
QToolBar#mainToolbar QToolButton:hover{{background:{tokens['hover']};border-color:{tokens['border_strong']};}}
QToolBar#mainToolbar QToolButton:pressed{{background:{tokens['primary_pressed']};color:{tokens['text_inverse']};border-color:{tokens['primary_pressed']};}}
QToolBar#mainToolbar QToolButton:checked{{background:{tokens['surface_soft']};border-color:{tokens['primary']};color:{tokens['text_primary']};}}
QToolBar#mainToolbar QToolButton:focus{{border:1px solid {tokens['focus']};}}
QToolBar#mainToolbar QToolButton:disabled{{color:{tokens['text_disabled']};background:transparent;border-color:transparent;}}
QToolButton#toolbarOverflowButton{{padding:5px;min-width:28px;}}
QFrame#providerPanel{{border:0;background:transparent;margin:0;padding:0;}}
QScrollArea#providerScrollArea{{border:0;background:transparent;}}
QScrollArea#providerScrollArea > QWidget > QWidget{{background:transparent;}}
QFrame#providerSection{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:8px;margin:0 0 6px 0;}}
QToolButton#providerSectionHeader{{background:transparent;border:0;border-radius:7px;color:{tokens['text_primary']};font-size:12px;font-weight:700;text-align:left;padding:8px 10px;min-height:20px;}}
QToolButton#providerSectionHeader:hover{{background:{tokens['surface_soft']};}}
QWidget#providerSectionContent{{background:transparent;border:0;}}
QFrame#providerField{{background:transparent;border:0;}}
QLabel#providerFieldLabel{{color:{tokens['text_secondary']};font-size:11px;font-weight:650;padding:0 0 1px 1px;}}
QFrame#providerFieldEditorRow{{background:transparent;border:0;}}
QFrame#collapsibleSection{{background:{tokens['panel']};border:0;border-top:1px solid {tokens['border_subtle']};}}
QToolButton#sectionHeader{{background:transparent;border:0;color:{tokens['text_primary']};font-weight:700;text-align:left;padding:6px 4px;}}
QLabel#formLabel{{color:{tokens['text_secondary']};font-weight:600;font-size:11px;padding-left:1px;}}
QWidget#sectionContent{{background:transparent;border:0;}}
QFrame#providerFieldRow,QFrame#inlineFieldRow{{background:transparent;border:0;}}
QPushButton#connectionStatus{{background:{tokens['input']};border:1px solid {tokens['border_subtle']};border-radius:7px;padding:6px 10px;color:{tokens['text_primary']};text-align:left;font-weight:600;}}
QPushButton#connectionStatus:hover{{background:{tokens['hover']};border-color:{tokens['focus']};}}
QDialog#providerAccountsDialog{{background:{tokens['canvas']};}}
QFrame#providerAccountsHeader,QFrame#providerAccountsToolbar,QFrame#providerAccountDetails{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:8px;}}
QFrame#providerAccountsSummary{{background:{tokens['surface_soft']};border:1px solid {tokens['border_subtle']};border-radius:7px;}}
QLabel#summaryStrong{{font-size:12px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#summaryMuted{{font-size:11px;color:{tokens['text_secondary']};}}
QTableWidget#providerProfilesTable{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:8px;gridline-color:transparent;}}
QTableWidget#providerProfilesTable::item{{padding:7px 6px;border-bottom:1px solid {tokens['border_subtle']};}}
QTableWidget#providerProfilesTable::item:selected{{background:{tokens['selected_row']};color:{tokens['text_primary']};}}
QFrame#temporaryCredentialBanner{{background:{tokens['surface_soft']};border:1px solid {tokens['focus']};border-radius:7px;}}
QLabel#dialogTitle{{font-size:18px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#dialogSubtitle{{font-size:11px;color:{tokens['text_secondary']};}}
QLabel#sectionTitle,QLabel#accountName{{font-size:14px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#accountStatus{{background:{tokens['input']};border:1px solid {tokens['border_subtle']};border-radius:7px;padding:8px;color:{tokens['text_secondary']};}}
QFrame#providerAccountIdentity,QFrame#providerAccountQuotaCard,QFrame#providerAccountCatalogCard,QFrame#providerAccountMetadataCard{{background:{tokens['surface_soft']};border:1px solid {tokens['border_subtle']};border-radius:8px;}}
QLabel#accountStatusBadge{{border-radius:7px;padding:3px 8px;font-size:10px;font-weight:800;background:{tokens['elevated']};color:{tokens['text_secondary']};}}
QLabel#accountStatusBadge[status=active],QLabel#accountStatusBadge[status=success]{{background:{tokens['surface_soft']};color:{tokens['success']};border:1px solid {tokens['success']};}}
QLabel#accountStatusBadge[status=error]{{background:{tokens['surface_soft']};color:{tokens['error']};border:1px solid {tokens['error']};}}
QLabel#accountStatusBadge[status=info]{{background:{tokens['surface_soft']};color:{tokens['info']};border:1px solid {tokens['info']};}}
QLabel#accountStatusBadge[status=disabled]{{background:{tokens['elevated']};color:{tokens['text_disabled']};border:1px solid {tokens['border_subtle']};}}
QLabel#cardTitle{{font-size:11px;font-weight:800;color:{tokens['text_secondary']};}}
QLabel#cardValue{{font-size:12px;font-weight:800;color:{tokens['text_primary']};}}
QFrame#providerCatalogMetric{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:7px;}}
QLabel#catalogMetric{{font-size:18px;font-weight:850;color:{tokens['text_primary']};}}
QProgressBar#providerQuotaProgress{{background:{tokens['input']};border:0;border-radius:4px;}}
QProgressBar#providerQuotaProgress::chunk{{background:{tokens['primary']};border-radius:4px;}}
QLabel#failoverPreview{{background:{tokens['input']};border:1px solid {tokens['border_subtle']};border-radius:7px;padding:10px;color:{tokens['text_secondary']};}}
QDialog#generationOrchestrationDialog{{background:{tokens['canvas']};}}
QFrame#orchestrationHeader,QFrame#orchestrationToolbar,QFrame#orchestrationViewBar,QFrame#orchestrationFooter,QFrame#orchestrationPlanCard{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:8px;}}
QFrame#orchestrationRecommendation,QFrame#orchestrationPresetCard,QFrame#orchestrationAttentionSummary{{background:{tokens['surface_soft']};border:1px solid {tokens['border_subtle']};border-radius:8px;}}
QLabel#orchestrationProjectBadge{{background:{tokens['surface_soft']};border:1px solid {tokens['focus']};border-radius:7px;padding:5px 10px;font-size:11px;font-weight:800;color:{tokens['text_primary']};}}
QFrame#orchestrationMetricCard{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:8px;}}
QFrame#orchestrationMetricCard[status=success]{{border-color:{tokens['success']};}}
QFrame#orchestrationMetricCard[status=warning]{{border-color:{tokens['warning']};}}
QFrame#orchestrationMetricCard[status=error]{{border-color:{tokens['error']};}}
QLabel#orchestrationMetricTitle{{font-size:10px;font-weight:750;color:{tokens['text_secondary']};}}
QLabel#orchestrationMetricValue{{font-size:20px;font-weight:850;color:{tokens['text_primary']};}}
QLabel#orchestrationMetricDetail{{font-size:10px;color:{tokens['text_secondary']};}}
QLabel#summaryMuted[status=success]{{color:{tokens['success']};font-weight:650;}}
QLabel#summaryMuted[status=warning]{{color:{tokens['warning']};font-weight:650;}}
QLabel#summaryMuted[status=error]{{color:{tokens['error']};font-weight:650;}}
QTableWidget#orchestrationTable{{background:{tokens['panel']};border:1px solid {tokens['border_subtle']};border-radius:8px;gridline-color:transparent;}}
QTableWidget#orchestrationTable::item{{padding:5px 6px;border-bottom:1px solid {tokens['border_subtle']};}}
QTableWidget#orchestrationTable::item:selected{{background:{tokens['selected_row']};color:{tokens['text_primary']};}}
QTabWidget#orchestrationTabs::pane{{border:1px solid {tokens['border_subtle']};border-radius:8px;background:{tokens['panel']};}}
QTabWidget#orchestrationTabs QTabBar::tab{{min-width:120px;text-align:left;padding:8px 10px;}}
QTabWidget::pane{{border:1px solid {tokens['border_subtle']};border-radius:7px;background:{tokens['panel']};}}
QTabBar::tab{{background:{tokens['elevated']};color:{tokens['text_secondary']};padding:6px 10px;border:1px solid {tokens['border_subtle']};border-bottom:0;border-top-left-radius:6px;border-top-right-radius:6px;}}
QTabBar::tab:selected{{color:{tokens['text_primary']};background:{tokens['panel']};border-color:{tokens['border']};}}
QDockWidget{{titlebar-close-icon:url(none);titlebar-normal-icon:url(none);}}
QLabel#title{{font-size:28px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#subtitle,QLabel#cardCaption{{color:{tokens['text_secondary']};}}
QLabel#cardValue{{font-size:20px;font-weight:700;color:{tokens['text_primary']};}}
QLabel#previewTitle{{font-size:20px;font-weight:800;color:{tokens['text_primary']};}}
QLabel#statusBadge{{border-radius:6px;padding:3px 7px;font-weight:700;}}
QLineEdit,QComboBox,QPlainTextEdit,QTableWidget,QAbstractSpinBox{{background:{tokens['input']};color:{tokens['text_primary']};border:1px solid {tokens['border']};border-radius:6px;padding:6px 8px;min-height:22px;}}
QComboBox{{padding-right:28px;}}
QComboBox::drop-down{{subcontrol-origin:padding;subcontrol-position:top right;width:24px;border-left:1px solid {tokens['border_subtle']};}}
QComboBox QAbstractItemView{{background:{tokens['overlay']};color:{tokens['text_primary']};selection-background-color:{tokens['selected_row']};selection-color:{tokens['selected_text']};border:1px solid {tokens['border']};padding:4px;}}
QComboBox QAbstractItemView::item{{min-height:30px;padding:4px 8px;}}
QLineEdit:disabled,QComboBox:disabled,QPlainTextEdit:disabled,QAbstractSpinBox:disabled{{color:{tokens['text_disabled']};background:{tokens['panel']};}}
QPushButton,QToolButton{{background:{tokens['elevated']};color:{tokens['text_primary']};border:1px solid {tokens['border']};border-radius:6px;padding:6px 10px;font-weight:600;min-height:22px;}}
QPushButton:hover,QToolButton:hover{{background:{tokens['hover']};border-color:{tokens['primary']};}}
QPushButton:pressed,QToolButton:pressed{{background:{tokens['primary_pressed']};}}
QPushButton#primaryButton{{background:{tokens['primary']};color:{tokens['text_inverse']};border-color:{tokens['primary']};min-height:28px;}}
QPushButton#destructiveButton{{background:{tokens['destructive']};color:{tokens['text_inverse']};border-color:{tokens['destructive']};}}
QPushButton:disabled,QToolButton:disabled{{color:{tokens['text_disabled']};background:{tokens['panel']};border-color:{tokens['border']};}}
QHeaderView::section{{background:{tokens['elevated']};color:{tokens['text_secondary']};padding:7px;border:0;border-right:1px solid {tokens['border']};}}
QTableWidget{{gridline-color:{tokens['border']};alternate-background-color:{tokens['panel']};}}
QTableWidget::item:selected,QTableView::item:selected{{background:{tokens['selected_row']};color:{tokens['selected_text']};}}
QProgressBar{{background:{tokens['input']};border:1px solid {tokens['border']};border-radius:6px;text-align:center;}}
QProgressBar::chunk{{background:{tokens['accent_teal']};border-radius:5px;}}
QSlider::groove:horizontal{{height:4px;background:{tokens['border']};border-radius:2px;}}
QSlider::handle:horizontal{{width:14px;margin:-6px 0;background:{tokens['primary']};border-radius:7px;}}
QScrollBar:vertical{{background:{tokens['panel']};width:12px;}}
QScrollBar::handle:vertical{{background:{tokens['border']};border-radius:6px;min-height:28px;}}
QScrollBar:horizontal{{background:{tokens['panel']};height:12px;}}
QScrollBar::handle:horizontal{{background:{tokens['border']};border-radius:6px;min-width:28px;}}
QMenuBar{{background:{tokens['panel']};color:{tokens['text_primary']};padding:2px 6px;border-bottom:1px solid {tokens['border_subtle']};}}
QMenuBar::item{{background:transparent;padding:5px 10px;border-radius:5px;spacing:6px;}}
QMenuBar::item:selected,QMenuBar::item:pressed{{background:{tokens['hover']};color:{tokens['text_primary']};}}
QMenuBar::item:focus{{border:1px solid {tokens['focus']};}}
QMenu{{background:{tokens['overlay']};color:{tokens['text_primary']};border:1px solid {tokens['border']};padding:5px;}}
QMenu::item{{padding:6px 28px 6px 26px;border-radius:5px;}}
QMenu::item:selected{{background:{tokens['hover']};color:{tokens['text_primary']};}}
QMenu::item:pressed{{background:{tokens['surface_soft']};}}
QMenu::item:checked{{background:{tokens['surface_soft']};font-weight:700;}}
QMenu::item:disabled{{color:{tokens['text_disabled']};background:transparent;}}
QMenu::separator{{height:1px;background:{tokens['border_subtle']};margin:5px 8px;}}
QMenu::right-arrow{{width:8px;height:8px;}}
QMenu::icon{{padding-left:6px;}}
"""


DARK_STYLE = _stylesheet(DARK_TOKENS)
LIGHT_STYLE = _stylesheet(LIGHT_TOKENS)
GRAPHITE_STYLE = _stylesheet(GRAPHITE_TOKENS)


class ThemeManager:
    def __init__(self) -> None:
        self.settings = QSettings("S Talking", "S Talking")

    def current(self) -> str:
        return str(self.settings.value("theme/name", "Dark"))

    def save(self, name: str) -> None:
        self.settings.setValue("theme/name", name)

    @staticmethod
    def available_themes() -> tuple[str, ...]:
        return ("Dark", "Graphite", "Light", "System")

    def tokens(self, name: str | None = None) -> dict[str, str]:
        selected = self.effective_name(name or self.current())
        return {
            "Dark": DARK_TOKENS,
            "Graphite": GRAPHITE_TOKENS,
            "Light": LIGHT_TOKENS,
        }[selected]

    def palette(self, name: str | None = None) -> QPalette:
        return _build_palette(self.tokens(name))

    def stylesheet(self, name: str | None = None) -> str:
        selected = self.effective_name(name or self.current())
        return {
            "Dark": DARK_STYLE,
            "Graphite": GRAPHITE_STYLE,
            "Light": LIGHT_STYLE,
        }[selected]

    @staticmethod
    def effective_name(name: str) -> str:
        if name == "System":
            application = QApplication.instance()
            palette = application.style().standardPalette() if application is not None else QApplication.palette()
            return "Dark" if palette.window().color().lightness() < 128 else "Light"
        return name if name in {"Dark", "Graphite", "Light"} else "Dark"

# v0.19 product UI foundation additions are appended to both generated themes.
_PROVIDER_WORKSPACE_STYLE = r"""
QFrame#providerPanelHeader {
    border: 1px solid palette(midlight);
    border-radius: 9px;
    background: palette(base);
}
QLabel#panelTitle {
    font-size: 14px;
    font-weight: 800;
}
QLabel#panelSubtitle {
    font-size: 11px;
    color: palette(mid);
}
QFrame#providerPanel QCheckBox {
    spacing: 8px;
    min-height: 24px;
}
QFrame#providerPanel QPushButton#connectionStatus {
    text-align: left;
}
"""
DARK_STYLE += _PROVIDER_WORKSPACE_STYLE
LIGHT_STYLE += _PROVIDER_WORKSPACE_STYLE
GRAPHITE_STYLE += _PROVIDER_WORKSPACE_STYLE
DARK_STYLE += r"""
QDialog#voiceBrowserDialog,QDialog#pronunciationDictionaryDialog {
    background: palette(window);
}
QFrame#voiceContextCard,QFrame#voiceFilterCard,QFrame#dictionaryHeaderCard,QFrame#dictionaryActionCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QLabel#voiceDetailsTitle {
    font-size: 18px;
    font-weight: 800;
}
QPushButton#favoriteButton {
    font-size: 18px;
    min-width: 36px;
    max-width: 44px;
    padding: 3px;
}
QPushButton#primaryQuietButton {
    font-weight: 700;
}
QLabel#dictionaryCompatibility {
    padding: 7px 10px;
    border: 1px solid palette(midlight);
    border-radius: 7px;
    background: palette(base);
}
QFrame#dictionaryActionCard QPushButton {
    min-width: 120px;
}
QGroupBox#voiceAudioSettings {
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 700;
}
"""
LIGHT_STYLE += r"""
QDialog#voiceBrowserDialog,QDialog#pronunciationDictionaryDialog {
    background: palette(window);
}
QFrame#voiceContextCard,QFrame#voiceFilterCard,QFrame#dictionaryHeaderCard,QFrame#dictionaryActionCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QLabel#voiceDetailsTitle {
    font-size: 18px;
    font-weight: 800;
}
QPushButton#favoriteButton {
    font-size: 18px;
    min-width: 36px;
    max-width: 44px;
    padding: 3px;
}
QPushButton#primaryQuietButton {
    font-weight: 700;
}
QLabel#dictionaryCompatibility {
    padding: 7px 10px;
    border: 1px solid palette(midlight);
    border-radius: 7px;
    background: palette(base);
}
QFrame#dictionaryActionCard QPushButton {
    min-width: 120px;
}
QGroupBox#voiceAudioSettings {
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 700;
}
"""

GRAPHITE_STYLE += r"""
QDialog#voiceBrowserDialog,QDialog#pronunciationDictionaryDialog {
    background: palette(window);
}
QFrame#voiceContextCard,QFrame#voiceFilterCard,QFrame#dictionaryHeaderCard,QFrame#dictionaryActionCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QLabel#voiceDetailsTitle {
    font-size: 18px;
    font-weight: 800;
}
QPushButton#favoriteButton {
    font-size: 18px;
    min-width: 36px;
    max-width: 44px;
    padding: 3px;
}
QPushButton#primaryQuietButton {
    font-weight: 700;
}
QLabel#dictionaryCompatibility {
    padding: 7px 10px;
    border: 1px solid palette(midlight);
    border-radius: 7px;
    background: palette(base);
}
QFrame#dictionaryActionCard QPushButton {
    min-width: 120px;
}
QGroupBox#voiceAudioSettings {
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 700;
}
"""

_QUEUE_WORKSPACE_STYLE = r"""
QLineEdit#queueSearch {
    min-height: 32px;
    padding: 0 10px;
    border-radius: 7px;
}
QFrame#queueScopeSummary {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QLabel#queueVisibleSummary,QLabel#queueSelectedSummary,QLabel#queueActiveScope {
    padding: 0 2px;
    font-size: 12px;
}
QLabel#queueSelectedSummary[active="true"] {
    font-weight: 700;
}
QFrame#queueSummarySeparator {
    color: palette(midlight);
    max-width: 1px;
}
QTableWidget#queueTable {
    border: 1px solid palette(midlight);
    border-radius: 8px;
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    alternate-background-color: palette(alternate-base);
    outline: 0;
}
QTableWidget#queueTable::item {
    padding: 5px 8px;
    border: 0;
}
QTableWidget#queueTable::item:selected {
    font-weight: 600;
}
QHeaderView#queueHeader::section {
    min-height: 32px;
    padding: 5px 8px;
    border: 0;
    border-right: 1px solid palette(midlight);
    border-bottom: 1px solid palette(midlight);
    background: palette(button);
    font-weight: 700;
}
QHeaderView#queueHeader::section:hover {
    background: palette(midlight);
}
"""
DARK_STYLE += _QUEUE_WORKSPACE_STYLE
LIGHT_STYLE += _QUEUE_WORKSPACE_STYLE
GRAPHITE_STYLE += _QUEUE_WORKSPACE_STYLE

_QUEUE_PRO_STYLE = r"""
QFrame#queueWorkspace {
    background: transparent;
}
QFrame#queueWorkspaceHeading,QFrame#queueRangeBar,QFrame#queueCommandBar {
    background: palette(window);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QLabel#queueWorkspaceTitle {
    font-size: 15px;
    font-weight: 800;
}
QLabel#queueWorkspaceSubtitle {
    color: palette(mid);
    font-size: 11px;
}
QToolButton#queueColumnsButton {
    min-height: 30px;
    padding: 0 10px;
    border: 1px solid palette(midlight);
    border-radius: 7px;
}
QToolButton#queueColumnsButton:hover {
    background: palette(midlight);
}
QLabel#queueWorkspaceFooter {
    padding: 3px 9px;
    color: palette(mid);
    border-top: 1px solid palette(midlight);
    font-size: 11px;
}
"""
DARK_STYLE += _QUEUE_PRO_STYLE
LIGHT_STYLE += _QUEUE_PRO_STYLE
GRAPHITE_STYLE += _QUEUE_PRO_STYLE

# Provider Accounts 2.0 catalog state styles are injected by apply_theme.
CATALOG_STATE_QSS = r"""
QLabel#catalogStateBadge {
    min-width: 68px;
    padding: 3px 8px;
    border-radius: 9px;
    font-weight: 600;
}
QLabel#catalogStateBadge[state="fresh"] {
    background: rgba(16, 185, 129, 0.16);
    color: #34D399;
}
QLabel#catalogStateBadge[state="stale"] {
    background: rgba(245, 158, 11, 0.18);
    color: #FBBF24;
}
QLabel#catalogStateBadge[state="missing"] {
    background: rgba(100, 116, 139, 0.16);
    color: #94A3B8;
}
"""

DARK_STYLE += CATALOG_STATE_QSS
LIGHT_STYLE += CATALOG_STATE_QSS
GRAPHITE_STYLE += CATALOG_STATE_QSS

_VOICE_BROWSER_PRO_STYLE = r"""
QLabel#voiceResultsCount {
    color: palette(mid);
    font-weight: 700;
    padding: 0 6px;
}
QTableView#voiceCatalogTable {
    border: 1px solid palette(midlight);
    border-radius: 8px;
    background: palette(base);
    alternate-background-color: palette(alternate-base);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}
QTableView#voiceCatalogTable::item {
    border: none;
    padding: 5px 7px;
}
QTableView#voiceCatalogTable::item:hover:!selected {
    background: palette(midlight);
}
QTableView#voiceCatalogTable QHeaderView::section {
    min-height: 30px;
    padding: 5px 7px;
    border: none;
    border-bottom: 1px solid palette(midlight);
    font-weight: 700;
}
"""
DARK_STYLE += _VOICE_BROWSER_PRO_STYLE
LIGHT_STYLE += _VOICE_BROWSER_PRO_STYLE
GRAPHITE_STYLE += _VOICE_BROWSER_PRO_STYLE

# Phase 23 professional workspace shell. Appended after legacy rules so the
# modern shell can evolve without destabilizing dialogs that still depend on
# the original global selectors.
_PROFESSIONAL_WORKSPACE_STYLE = r"""
QWidget#applicationShell {
    background: palette(window);
}
QFrame#workspaceHero {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 11px;
}
QLabel#workspaceProjectTitle {
    font-size: 18px;
    font-weight: 850;
}
QLabel#workspaceProjectSubtitle {
    color: palette(mid);
    font-size: 11px;
    font-weight: 600;
}
QLabel#projectContextBar {
    color: palette(mid);
    font-size: 10px;
}
QFrame#projectContextStrip {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QPushButton#workspaceSecondaryAction {
    min-height: 26px;
    padding: 4px 9px;
    background: transparent;
}
QLabel#workspaceStatusBadge,
QLabel#generationStateBadge {
    min-height: 20px;
    padding: 3px 8px;
    border: 1px solid palette(midlight);
    border-radius: 9px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 10px;
    font-weight: 800;
}
QLabel#workspaceStatusBadge[tone="info"],
QLabel#generationStateBadge[tone="info"] {
    border-color: #3B82F6;
    color: #60A5FA;
    background: rgba(59, 130, 246, 0.11);
}
QLabel#workspaceStatusBadge[tone="success"],
QLabel#generationStateBadge[tone="success"] {
    border-color: #16A34A;
    color: #22C55E;
    background: rgba(34, 197, 94, 0.11);
}
QLabel#workspaceStatusBadge[tone="warning"],
QLabel#generationStateBadge[tone="warning"] {
    border-color: #D97706;
    color: #F59E0B;
    background: rgba(245, 158, 11, 0.12);
}
QLabel#workspaceStatusBadge[tone="error"],
QLabel#generationStateBadge[tone="error"] {
    border-color: #DC2626;
    color: #EF4444;
    background: rgba(239, 68, 68, 0.11);
}
QLabel#workspaceStatusBadge[tone="running"],
QLabel#generationStateBadge[tone="running"] {
    border-color: #0D9488;
    color: #2DD4BF;
    background: rgba(20, 184, 166, 0.12);
}
QFrame#metricsStrip {
    background: transparent;
    border: 0;
}
QFrame#metricPill {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QFrame#metricPill:hover {
    border-color: palette(highlight);
    background: palette(alternate-base);
}
QFrame#metricPill[active="true"] {
    border: 1px solid palette(highlight);
    background: palette(alternate-base);
}
QFrame#metricPill[tone="error"] {
    border-color: #DC2626;
}
QFrame#metricPill[tone="warning"] {
    border-color: #D97706;
}
QFrame#metricPill[tone="success"] {
    border-color: #16A34A;
}
QLabel#metricCaption {
    color: palette(mid);
    font-size: 9px;
    font-weight: 700;
}
QLabel#metricValue {
    font-size: 14px;
    font-weight: 850;
}
QFrame#generationActionBar {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 11px;
}
QPushButton#generationPrimaryAction {
    min-height: 30px;
    padding: 5px 14px;
    border-color: #2563EB;
    background: #2563EB;
    color: white;
    font-weight: 800;
}
QPushButton#generationPrimaryAction:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton#generationStopAction {
    color: #EF4444;
}
QPushButton#generationPreflightAction {
    background: transparent;
}
QFrame#generationProgressContext {
    background: transparent;
    border: 0;
}
QLabel#generationProgressLabel {
    color: palette(mid);
    font-size: 10px;
    font-weight: 650;
}
QFrame#generationProgressContext QProgressBar {
    min-height: 8px;
    max-height: 8px;
    border: 0;
    border-radius: 4px;
    text-align: center;
}
QTabWidget#activityTabs::pane {
    border-radius: 9px;
}
QFrame#queueWorkspace[density="compact"] QLabel#queueWorkspaceSubtitle {
    font-size: 10px;
}
"""
DARK_STYLE += _PROFESSIONAL_WORKSPACE_STYLE
LIGHT_STYLE += _PROFESSIONAL_WORKSPACE_STYLE
GRAPHITE_STYLE += _PROFESSIONAL_WORKSPACE_STYLE

# Phase 24 unified professional interface and accessibility contract.
_INTERFACE_ACCESSIBILITY_STYLE = r"""
QFrame#professionalDialogHeader,
QFrame#interfaceSettingsCard,
QFrame#interfacePreviewCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 11px;
}
QLabel#professionalDialogTitle {
    font-size: 18px;
    font-weight: 850;
}
QLabel#professionalDialogSubtitle,
QLabel#interfacePreviewBody,
QLabel#interfacePreviewShortcut,
QLabel#interfaceShortcutSummary {
    color: palette(mid);
    font-size: 11px;
}
QLabel#interfacePreviewTitle {
    font-size: 14px;
    font-weight: 800;
}
QLabel#interfacePreviewStatus {
    min-height: 20px;
    padding: 3px 8px;
    border: 1px solid #16A34A;
    border-radius: 9px;
    color: #22C55E;
    background: rgba(34, 197, 94, 0.11);
    font-size: 10px;
    font-weight: 800;
}
QLabel#interfacePreviewStatus[tone="info"] {
    border-color: #2563EB;
    color: #60A5FA;
    background: rgba(59, 130, 246, 0.11);
}
QFrame#interfacePreviewCard[contrastMode="high"] {
    border: 2px solid palette(highlight);
}
QFrame#interfacePreviewCard[focusMode="enhanced"] {
    border: 2px solid palette(highlight);
}
QFrame#interfacePreviewCard[textScale="110"] QLabel {
    font-size: 12px;
}
QFrame#interfacePreviewCard[textScale="125"] QLabel {
    font-size: 13px;
}
QMainWindow[textScale="110"] QWidget {
    font-size: 14px;
}
QMainWindow[textScale="125"] QWidget {
    font-size: 15px;
}
QMainWindow[contrastMode="high"] QFrame#workspaceHero,
QMainWindow[contrastMode="high"] QFrame#projectContextStrip,
QMainWindow[contrastMode="high"] QFrame#metricPill,
QMainWindow[contrastMode="high"] QFrame#generationActionBar,
QMainWindow[contrastMode="high"] QFrame#queueWorkspaceHeading,
QMainWindow[contrastMode="high"] QFrame#queueRangeBar,
QMainWindow[contrastMode="high"] QFrame#queueCommandBar,
QMainWindow[contrastMode="high"] QTableWidget#queueTable,
QMainWindow[contrastMode="high"] QTableView#queueTable {
    border: 2px solid palette(highlight);
}
QMainWindow[contrastMode="high"] QLabel#workspaceProjectSubtitle,
QMainWindow[contrastMode="high"] QLabel#projectContextBar,
QMainWindow[contrastMode="high"] QLabel#metricCaption,
QMainWindow[contrastMode="high"] QLabel#generationProgressLabel {
    color: palette(text);
}
QMainWindow[contrastMode="high"] QLineEdit,
QMainWindow[contrastMode="high"] QComboBox,
QMainWindow[contrastMode="high"] QAbstractSpinBox,
QMainWindow[contrastMode="high"] QPushButton,
QMainWindow[contrastMode="high"] QToolButton {
    border-width: 2px;
}
QMainWindow[focusMode="enhanced"] QLineEdit:focus,
QMainWindow[focusMode="enhanced"] QComboBox:focus,
QMainWindow[focusMode="enhanced"] QAbstractSpinBox:focus,
QMainWindow[focusMode="enhanced"] QPushButton:focus,
QMainWindow[focusMode="enhanced"] QToolButton:focus,
QMainWindow[focusMode="enhanced"] QTableView:focus,
QMainWindow[focusMode="enhanced"] QTableWidget:focus,
QMainWindow[focusMode="enhanced"] QTabWidget:focus {
    border: 2px solid palette(highlight);
    background: palette(alternate-base);
}
QLabel#accessibilityAnnouncer {
    background: transparent;
    border: 0;
    color: transparent;
}
"""
DARK_STYLE += _INTERFACE_ACCESSIBILITY_STYLE
LIGHT_STYLE += _INTERFACE_ACCESSIBILITY_STYLE
GRAPHITE_STYLE += _INTERFACE_ACCESSIBILITY_STYLE

# Phase 25 professional visual refresh focused on readability and clipped
# controls discovered in screenshot review.
_PHASE25_PRO_REFRESH_STYLE = r"""
QToolBar#mainToolbar {
    background: palette(window);
    border: 0;
    border-bottom: 1px solid palette(midlight);
    spacing: 8px;
    padding: 4px 10px;
}
QToolBar#mainToolbar QToolButton {
    min-height: 26px;
    padding: 6px 10px;
    border-radius: 8px;
}
QToolBar#mainToolbar QToolButton:hover {
    background: palette(alternate-base);
}
QTabBar::tab {
    min-height: 26px;
    padding: 7px 12px;
}
QTabBar::tab:selected {
    font-weight: 700;
}
QDockWidget {
    background: palette(window);
}
QDockWidget::title {
    padding: 6px 8px;
    background: palette(window);
    color: palette(window-text);
    border-bottom: 1px solid palette(midlight);
    text-align: left;
    font-weight: 700;
}
QFrame#workspaceHero,
QFrame#projectContextStrip,
QFrame#providerSection,
QFrame#queueWorkspaceHeading,
QFrame#queueRangeBar,
QFrame#queueCommandBar,
QFrame#generationActionBar,
QFrame#metricPill,
QFrame#queueScopeSummary,
QFrame#professionalDialogHeader,
QFrame#interfaceSettingsCard,
QFrame#interfacePreviewCard,
QFrame#sourcesWorkspaceHeader,
QFrame#sourcesActionBar {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QFrame#workspaceHero,
QFrame#generationActionBar,
QFrame#sourcesWorkspaceHeader,
QFrame#sourcesActionBar {
    border-color: palette(dark);
}
QLabel#workspaceProjectSubtitle,
QLabel#projectContextBar,
QLabel#queueWorkspaceSubtitle,
QLabel#metricCaption,
QLabel#generationProgressLabel,
QLabel#panelSubtitle,
QLabel#sourcesWorkspaceSubtitle,
QLabel#sourcesWorkspaceHelper {
    color: palette(mid);
}
QLabel#workspaceProjectTitle,
QLabel#queueWorkspaceTitle,
QLabel#panelTitle,
QLabel#sourcesWorkspaceTitle {
    color: palette(window-text);
    font-weight: 800;
}
QWidget#sourcesWorkspacePanel {
    background: transparent;
}
QPushButton#sourcesActionButton {
    min-height: 34px;
    padding: 6px 10px;
    text-align: left;
    border-radius: 8px;
    background: palette(alternate-base);
}
QPushButton#sourcesActionButton:hover {
    background: palette(button);
}
QPushButton#sourcesActionButton[primary="true"] {
    background: rgba(37, 99, 235, 0.12);
    border-color: #2563EB;
}
QPushButton#sourcesActionButton[primary="true"]:hover {
    background: rgba(37, 99, 235, 0.18);
}
QTableWidget#sourcesTable,
QTableWidget#queueTable,
QTableView#queueTable,
QTableWidget#providerProfilesTable {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    gridline-color: transparent;
}
QTableWidget#sourcesTable::item,
QTableWidget#queueTable::item,
QTableView#queueTable::item {
    padding: 6px 8px;
    border: none;
}
QHeaderView::section {
    background: palette(alternate-base);
    color: palette(window-text);
    padding: 7px 8px;
    border: 0;
    border-right: 1px solid palette(midlight);
    border-bottom: 1px solid palette(midlight);
    font-weight: 700;
}
QLineEdit,
QComboBox,
QPlainTextEdit,
QTableWidget,
QTableView,
QAbstractSpinBox {
    border-radius: 8px;
}
QLineEdit,
QComboBox,
QAbstractSpinBox {
    min-height: 24px;
}
QScrollBar:vertical,
QScrollBar:horizontal {
    background: transparent;
}
QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: palette(mid);
}
QMainWindow[contrastMode="high"] QFrame#sourcesWorkspaceHeader,
QMainWindow[contrastMode="high"] QFrame#sourcesActionBar,
QMainWindow[contrastMode="high"] QTableWidget#sourcesTable {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE25_PRO_REFRESH_STYLE
LIGHT_STYLE += _PHASE25_PRO_REFRESH_STYLE
GRAPHITE_STYLE += _PHASE25_PRO_REFRESH_STYLE

# Phase 26 queue command center, inspector and generation monitor refresh.
_PHASE26_OPERATIONAL_UI_STYLE = r"""
QFrame#queueCommandBar {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QLabel#queueCommandSectionLabel {
    min-width: 48px;
    color: palette(mid);
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
}
QPushButton#queuePrimaryAction {
    min-height: 30px;
    padding: 5px 12px;
    background: #2563EB;
    border-color: #2563EB;
    color: white;
    font-weight: 800;
}
QPushButton#queuePrimaryAction:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton#queueSecondaryAction,
QToolButton#queueActionMenu {
    min-height: 30px;
    padding: 5px 10px;
    background: palette(alternate-base);
    border-radius: 8px;
}
QPushButton#queueSecondaryAction:hover,
QToolButton#queueActionMenu:hover {
    background: palette(button);
    border-color: palette(highlight);
}
QFrame#queueInspectorHeader,
QFrame#queueInspectorCard,
QFrame#queueInspectorActions,
QFrame#monitorHero,
QFrame#monitorProgressCard,
QFrame#monitorOutputCard,
QFrame#monitorFailureCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QLabel#queueInspectorTitle,
QLabel#monitorTitle {
    color: palette(window-text);
    font-size: 15px;
    font-weight: 850;
}
QLabel#queueInspectorMeta,
QLabel#queueInspectorDetail,
QLabel#monitorSubtitle,
QLabel#monitorOutputPath,
QLabel#monitorMetricLabel {
    color: palette(mid);
}
QLabel#queueInspectorMeta,
QLabel#queueInspectorDetail,
QLabel#monitorSubtitle,
QLabel#monitorOutputPath {
    font-size: 11px;
}
QLabel#queueInspectorSectionTitle,
QLabel#monitorSectionTitle {
    color: palette(window-text);
    font-size: 11px;
    font-weight: 800;
}
QLabel#queueInspectorStatus,
QLabel#monitorStatusBadge {
    min-height: 22px;
    padding: 3px 8px;
    border: 1px solid palette(midlight);
    border-radius: 9px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 10px;
    font-weight: 850;
}
QLabel#queueInspectorStatus[tone="pending"],
QLabel#monitorStatusBadge[tone="info"] {
    border-color: #3B82F6;
    color: #60A5FA;
    background: rgba(59, 130, 246, 0.12);
}
QLabel#queueInspectorStatus[tone="running"],
QLabel#monitorStatusBadge[tone="running"] {
    border-color: #0D9488;
    color: #2DD4BF;
    background: rgba(20, 184, 166, 0.12);
}
QLabel#queueInspectorStatus[tone="completed"],
QLabel#monitorStatusBadge[tone="success"] {
    border-color: #16A34A;
    color: #22C55E;
    background: rgba(34, 197, 94, 0.12);
}
QLabel#queueInspectorStatus[tone="failed"],
QLabel#monitorStatusBadge[tone="error"] {
    border-color: #DC2626;
    color: #F87171;
    background: rgba(239, 68, 68, 0.12);
}
QLabel#queueInspectorStatus[tone="skipped"],
QLabel#monitorStatusBadge[tone="warning"] {
    border-color: #D97706;
    color: #FBBF24;
    background: rgba(245, 158, 11, 0.12);
}
QPushButton#queueInspectorAction,
QPushButton#monitorActionButton {
    min-height: 32px;
    text-align: center;
    border-radius: 8px;
    background: palette(alternate-base);
}
QPushButton#queueInspectorAction[primary="true"],
QPushButton#monitorPrimaryAction {
    background: #2563EB;
    border-color: #2563EB;
    color: white;
    font-weight: 800;
}
QPlainTextEdit#queueDetailsText,
QPlainTextEdit#queueRetryHistory,
QPlainTextEdit#monitorErrorDetails {
    background: palette(window);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    padding: 8px;
}
QPlainTextEdit#queueDetailsText {
    min-height: 180px;
}
QWidget#generationMonitorPanel {
    background: transparent;
}
QLabel#monitorPercent {
    color: palette(window-text);
    font-weight: 800;
}
QProgressBar#monitorProgress {
    min-height: 9px;
    max-height: 9px;
    border: 0;
    border-radius: 4px;
}
QProgressBar#monitorProgress::chunk {
    background: #3B82F6;
    border-radius: 4px;
}
QTabWidget#monitorSectionTabs::pane {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QTabWidget#monitorSectionTabs QTabBar::tab {
    min-width: 0;
    padding: 7px 8px;
    font-size: 10px;
}
QLabel#monitorMetricLabel {
    font-size: 10px;
    font-weight: 700;
}
QLabel#monitorMetricValue {
    color: palette(window-text);
    font-size: 11px;
    font-weight: 700;
}
QPushButton#monitorMoreDetails {
    min-height: 28px;
    background: transparent;
}
QDialog {
    background: palette(window);
}
QDialog QGroupBox {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
}
QDialog QGroupBox::title {
    color: palette(window-text);
    font-weight: 800;
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
}
QDialog QDialogButtonBox {
    background: transparent;
    border-top: 1px solid palette(midlight);
    padding-top: 8px;
}
QDialog QTabWidget::pane {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
}
QMainWindow[contrastMode="high"] QFrame#queueInspectorHeader,
QMainWindow[contrastMode="high"] QFrame#queueInspectorCard,
QMainWindow[contrastMode="high"] QFrame#queueInspectorActions,
QMainWindow[contrastMode="high"] QFrame#monitorHero,
QMainWindow[contrastMode="high"] QFrame#monitorProgressCard,
QMainWindow[contrastMode="high"] QFrame#monitorOutputCard,
QMainWindow[contrastMode="high"] QFrame#monitorFailureCard,
QMainWindow[contrastMode="high"] QFrame#queueCommandBar {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE26_OPERATIONAL_UI_STYLE
LIGHT_STYLE += _PHASE26_OPERATIONAL_UI_STYLE
GRAPHITE_STYLE += _PHASE26_OPERATIONAL_UI_STYLE

# Phase 27 responsive workspace hierarchy. These selectors only change
# presentation at resolved breakpoints; all business controls remain available.
_PHASE27_RESPONSIVE_WORKSPACE_STYLE = r"""
QMainWindow[responsiveMode="compact"] QFrame#workspaceHero {
    border-radius: 8px;
}
QMainWindow[responsiveMode="compact"] QLabel#workspaceProjectTitle {
    font-size: 15px;
}
QMainWindow[responsiveMode="compact"] QFrame#metricPill {
    min-width: 70px;
}
QMainWindow[responsiveMode="compact"] QLabel#metricCaption {
    font-size: 8px;
}
QMainWindow[responsiveMode="compact"] QToolBar#mainToolbar QToolButton {
    min-width: 32px;
    padding: 5px;
}
QFrame#queueWorkspace[responsiveMode="standard"] QFrame#queueCommandBar,
QFrame#queueWorkspace[responsiveMode="compact"] QFrame#queueCommandBar {
    padding: 0;
}
QFrame#queueWorkspace[responsiveMode="compact"] QLineEdit#queueSearch {
    min-width: 160px;
}
QFrame#queueWorkspace[responsiveMode="compact"] QComboBox#queueStatusFilter {
    min-width: 92px;
    max-width: 112px;
}
QFrame#queueWorkspace[responsiveMode="compact"] QComboBox#queueSourceFilter {
    min-width: 150px;
}
QFrame#queueWorkspace[responsiveMode="compact"] QComboBox#queueScopeSelector,
QFrame#queueWorkspace[responsiveMode="compact"] QComboBox#queueOrderSelector {
    min-width: 118px;
}
QToolButton#queueMoreActionsButton {
    min-height: 28px;
    padding: 5px 10px;
    border-radius: 8px;
    font-weight: 700;
}
QFrame#sourcesActionBar[columns="2"] QPushButton#sourcesActionButton {
    min-height: 36px;
}
QFrame#queueInspectorHeader[responsiveMode="compact"] {
    border-radius: 8px;
}
QFrame#queueInspectorCard[responsiveMode="compact"],
QFrame#queueInspectorActions[responsiveMode="compact"] {
    border-radius: 8px;
}
QFrame#queueInspectorActions[responsiveMode="compact"] QPushButton {
    min-height: 32px;
    padding-left: 6px;
    padding-right: 6px;
}
QTabWidget#monitorSectionTabs[responsiveMode="compact"] QTabBar::tab {
    min-width: 88px;
    padding-left: 7px;
    padding-right: 7px;
}
QMainWindow[responsiveMode="compact"] QDockWidget::title {
    padding-top: 4px;
    padding-bottom: 4px;
}
"""
DARK_STYLE += _PHASE27_RESPONSIVE_WORKSPACE_STYLE
LIGHT_STYLE += _PHASE27_RESPONSIVE_WORKSPACE_STYLE
GRAPHITE_STYLE += _PHASE27_RESPONSIVE_WORKSPACE_STYLE

# Phase 28 dialog and settings UX. Dialog content scrolls independently while
# primary actions remain in a stable footer outside the scroll area.
_PHASE28_DIALOG_WORKSPACE_STYLE = r"""
QWidget#dialogWorkspace {
    background: palette(window);
}
QScrollArea#dialogBodyScroll {
    background: transparent;
    border: 0;
}
QScrollArea#dialogBodyScroll > QWidget > QWidget#dialogBody {
    background: transparent;
}
QFrame#dialogStickyFooter {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QFrame#dialogSection,
QFrame#dialogStatusCard,
QFrame#setupProgressCard,
QFrame#setupStepRail {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QLabel#dialogSectionTitle,
QLabel#dialogStatusTitle,
QLabel#setupProgressLabel {
    color: palette(window-text);
    font-size: 13px;
    font-weight: 800;
}
QLabel#dialogSectionSubtitle,
QLabel#dialogStatusDetail,
QLabel#setupProviderSummary {
    color: palette(mid);
    font-size: 11px;
}
QFrame#dialogStatusCard[tone="success"] {
    border-color: #16A34A;
    background: rgba(34, 197, 94, 0.08);
}
QFrame#dialogStatusCard[tone="warning"] {
    border-color: #D97706;
    background: rgba(245, 158, 11, 0.08);
}
QFrame#dialogStatusCard[tone="error"] {
    border-color: #DC2626;
    background: rgba(239, 68, 68, 0.08);
}
QFrame#dialogStatusCard[tone="info"] {
    border-color: #2563EB;
    background: rgba(59, 130, 246, 0.08);
}
QPushButton#dialogPrimaryAction {
    min-height: 32px;
    padding: 6px 14px;
    background: #2563EB;
    border-color: #2563EB;
    color: white;
    font-weight: 800;
}
QPushButton#dialogPrimaryAction:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QFrame#setupWorkflow {
    background: transparent;
    border: 0;
}
QLabel#setupStepLabel {
    min-height: 30px;
    padding: 4px 8px;
    border-radius: 7px;
    color: palette(mid);
    font-weight: 650;
}
QLabel#setupStepLabel[active="true"] {
    color: palette(window-text);
    background: palette(alternate-base);
    border: 1px solid palette(highlight);
    font-weight: 800;
}
QLabel#setupStepLabel[complete="true"] {
    color: #22C55E;
}
QProgressBar#setupProgressBar {
    min-height: 8px;
    max-height: 8px;
    border: 0;
    border-radius: 4px;
    background: palette(alternate-base);
}
QProgressBar#setupProgressBar::chunk {
    background: #2563EB;
    border-radius: 4px;
}
QWidget#setupPage {
    background: transparent;
}
QPushButton#preflightToolAction {
    min-height: 34px;
    text-align: left;
    padding-left: 10px;
}
QTableWidget#preflightIssuesTable,
QTableWidget#preflightFixesTable {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    gridline-color: transparent;
}
QTableWidget#preflightIssuesTable::item,
QTableWidget#preflightFixesTable::item {
    padding: 6px 8px;
    border: 0;
}
QDialog[contrastMode="high"] QFrame#dialogSection,
QDialog[contrastMode="high"] QFrame#dialogStatusCard,
QDialog[contrastMode="high"] QFrame#dialogStickyFooter,
QDialog[contrastMode="high"] QFrame#setupProgressCard,
QDialog[contrastMode="high"] QFrame#setupStepRail {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE28_DIALOG_WORKSPACE_STYLE
LIGHT_STYLE += _PHASE28_DIALOG_WORKSPACE_STYLE
GRAPHITE_STYLE += _PHASE28_DIALOG_WORKSPACE_STYLE

_PHASE28_SOURCE_IMPORT_STYLE = r"""
QPushButton#sourceImportToolAction {
    min-height: 34px;
    padding: 6px 10px;
    text-align: left;
    border-radius: 8px;
    background: palette(alternate-base);
}
QPushButton#sourceImportToolAction:hover {
    background: palette(button);
    border-color: palette(highlight);
}
QTableWidget#sourceImportTable {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    gridline-color: transparent;
}
QTableWidget#sourceImportTable::item {
    padding: 6px 8px;
    border: 0;
}
"""
DARK_STYLE += _PHASE28_SOURCE_IMPORT_STYLE
LIGHT_STYLE += _PHASE28_SOURCE_IMPORT_STYLE
GRAPHITE_STYLE += _PHASE28_SOURCE_IMPORT_STYLE

# Phase 29 notification, empty-state and feedback experience.
_PHASE29_FEEDBACK_UX_STYLE = r"""
QFrame#professionalEmptyState,
QFrame#emptyState,
QFrame#notificationEmptyState {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 12px;
}
QLabel#professionalEmptyStateIcon {
    min-height: 38px;
    color: palette(highlight);
}
QLabel#professionalEmptyStateTitle {
    color: palette(window-text);
    font-size: 17px;
    font-weight: 850;
}
QLabel#professionalEmptyStateMessage {
    color: palette(mid);
    font-size: 11px;
}
QPushButton#professionalEmptyStateAction,
QPushButton#professionalEmptyStatePrimary {
    min-height: 32px;
    padding: 5px 11px;
    border-radius: 8px;
}
QPushButton#professionalEmptyStatePrimary {
    background: #2563EB;
    border-color: #2563EB;
    color: white;
    font-weight: 800;
}
QPushButton#professionalEmptyStatePrimary:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QFrame#inlineFeedbackBar {
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QFrame#inlineFeedbackBar[tone="success"] {
    border-color: #16A34A;
    background: rgba(34, 197, 94, 0.08);
}
QFrame#inlineFeedbackBar[tone="warning"] {
    border-color: #D97706;
    background: rgba(245, 158, 11, 0.08);
}
QFrame#inlineFeedbackBar[tone="error"] {
    border-color: #DC2626;
    background: rgba(239, 68, 68, 0.08);
}
QFrame#inlineFeedbackBar[tone="info"] {
    border-color: #2563EB;
    background: rgba(59, 130, 246, 0.08);
}
QLabel#inlineFeedbackMessage {
    color: palette(window-text);
    font-size: 11px;
    font-weight: 650;
}
QFrame#notificationCenterHeader,
QFrame#notificationFilterBar,
QFrame#notificationFooter {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QLabel#notificationCenterTitle {
    color: palette(window-text);
    font-size: 17px;
    font-weight: 850;
}
QLabel#notificationCenterSubtitle {
    color: palette(mid);
    font-size: 11px;
}
QLabel#notificationBadge {
    min-height: 22px;
    padding: 3px 8px;
    border: 1px solid palette(midlight);
    border-radius: 10px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 10px;
    font-weight: 800;
}
QLabel#notificationBadge[active="true"] {
    border-color: #2563EB;
    color: #60A5FA;
    background: rgba(59, 130, 246, 0.10);
}
QLineEdit#notificationSearch {
    min-width: 180px;
}
QComboBox#notificationSeverityFilter,
QComboBox#notificationViewFilter {
    min-width: 120px;
}
QListWidget#notificationList {
    background: transparent;
    border: 0;
    outline: 0;
}
QListWidget#notificationList::item {
    background: transparent;
    border: 0;
    padding: 0;
}
QListWidget#notificationList::item:selected {
    background: transparent;
}
QFrame#notificationCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QFrame#notificationCard:hover {
    border-color: palette(highlight);
    background: palette(alternate-base);
}
QFrame#notificationCard[unread="true"] {
    border-left: 3px solid #2563EB;
}
QFrame#notificationCard[severity="success"] {
    border-left-color: #16A34A;
}
QFrame#notificationCard[severity="warning"] {
    border-left-color: #D97706;
}
QFrame#notificationCard[severity="error"] {
    border-left-color: #DC2626;
}
QLabel#notificationUnreadDot {
    color: #60A5FA;
    font-size: 9px;
}
QLabel#notificationCardTitle {
    color: palette(window-text);
    font-size: 12px;
    font-weight: 800;
}
QLabel#notificationCardTimestamp {
    color: palette(mid);
    font-size: 9px;
}
QLabel#notificationCardMessage {
    color: palette(mid);
    font-size: 11px;
}
QToolButton#notificationCardAction,
QPushButton#notificationPrimaryAction {
    min-height: 30px;
    padding: 5px 9px;
    border-color: #2563EB;
    background: rgba(37, 99, 235, 0.10);
    font-weight: 750;
}
QToolButton#notificationCardAction:hover,
QPushButton#notificationPrimaryAction:hover {
    background: rgba(37, 99, 235, 0.18);
}
QMainWindow[contrastMode="high"] QFrame#notificationCenterHeader,
QMainWindow[contrastMode="high"] QFrame#notificationFilterBar,
QMainWindow[contrastMode="high"] QFrame#notificationFooter,
QMainWindow[contrastMode="high"] QFrame#notificationCard,
QMainWindow[contrastMode="high"] QFrame#inlineFeedbackBar,
QMainWindow[contrastMode="high"] QFrame#professionalEmptyState,
QMainWindow[contrastMode="high"] QFrame#emptyState,
QMainWindow[contrastMode="high"] QFrame#notificationEmptyState {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE29_FEEDBACK_UX_STYLE
LIGHT_STYLE += _PHASE29_FEEDBACK_UX_STYLE
GRAPHITE_STYLE += _PHASE29_FEEDBACK_UX_STYLE

# Phase 30 operational history, reports and activity timeline experience.
_PHASE30_OPERATIONAL_HISTORY_STYLE = r"""
QFrame#activityTimelineHeader,
QFrame#activityTimelineFilterBar,
QFrame#activityEventCard,
QFrame#historyMetricCard,
QFrame#reportMetricCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QLabel#activityTimelineTitle {
    color: palette(window-text);
    font-size: 15px;
    font-weight: 850;
}
QLabel#activityTimelineSubtitle,
QLabel#activityEventMessage,
QLabel#activityEventTimestamp,
QLabel#historyMetricCaption,
QLabel#reportMetricCaption,
QLabel#historySummaryText,
QLabel#reportContextText,
QLabel#reportPathLabel,
QLabel#reportHtmlPathLabel {
    color: palette(mid);
    font-size: 10px;
}
QLabel#activityTimelineCount,
QLabel#activityEventCategory {
    min-height: 20px;
    padding: 3px 8px;
    border: 1px solid palette(midlight);
    border-radius: 9px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 9px;
    font-weight: 800;
}
QLabel#activityEventTitle {
    color: palette(window-text);
    font-size: 11px;
    font-weight: 800;
}
QLabel#activityEventIcon {
    min-width: 18px;
}
QFrame#activityEventCard:hover {
    border-color: palette(highlight);
    background: palette(alternate-base);
}
QFrame#activityEventCard[category="generation"],
QLabel#activityEventCategory[category="generation"] {
    border-left-color: #0D9488;
}
QFrame#activityEventCard[category="preflight"],
QLabel#activityEventCategory[category="preflight"] {
    border-left-color: #D97706;
}
QFrame#activityEventCard[category="report"],
QLabel#activityEventCategory[category="report"] {
    border-left-color: #2563EB;
}
QListWidget#activityTimelineList {
    background: transparent;
    border: 0;
    outline: 0;
}
QListWidget#activityTimelineList::item {
    background: transparent;
    border: 0;
    padding: 0;
}
QListWidget#activityTimelineList::item:selected {
    background: transparent;
}
QPlainTextEdit#activityTimelineDetails,
QPlainTextEdit#generationHistoryDetails {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
    padding: 8px;
}
QComboBox#activityCategoryFilter {
    min-width: 125px;
}
QLineEdit#activitySearch,
QLineEdit#historySearch {
    min-width: 220px;
}
QTableWidget#generationHistoryTable {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
    gridline-color: transparent;
}
QTableWidget#generationHistoryTable::item {
    padding: 6px 8px;
    border: 0;
}
QFrame#historyMetricCard,
QFrame#reportMetricCard {
    background: palette(alternate-base);
    border-radius: 8px;
}
QFrame#reportMetricCard[tone="error"] {
    border-color: #DC2626;
    background: rgba(239, 68, 68, 0.08);
}
QFrame#reportMetricCard[tone="warning"] {
    border-color: #D97706;
    background: rgba(245, 158, 11, 0.08);
}
QLabel#historyMetricValue,
QLabel#reportMetricValue {
    color: palette(window-text);
    font-size: 18px;
    font-weight: 850;
}
QPushButton#historyToolAction {
    min-height: 34px;
    padding: 6px 10px;
    text-align: left;
    border-radius: 8px;
    background: palette(alternate-base);
}
QPushButton#historyToolAction:hover {
    border-color: palette(highlight);
    background: palette(button);
}
QLabel#historyStatusLabel {
    color: palette(mid);
    font-size: 10px;
}
QPushButton#historyOpenReportButton,
QPushButton#historyExportButton,
QPushButton#reportPrimaryAction {
    min-height: 32px;
    padding: 5px 12px;
    border-color: #2563EB;
    background: #2563EB;
    color: white;
    font-weight: 800;
}
QPushButton#historyOpenReportButton:hover,
QPushButton#historyExportButton:hover,
QPushButton#reportPrimaryAction:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QLabel#reportPathLabel,
QLabel#reportHtmlPathLabel {
    padding: 8px 10px;
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    color: palette(window-text);
}
QMainWindow[contrastMode="high"] QFrame#activityTimelineHeader,
QMainWindow[contrastMode="high"] QFrame#activityTimelineFilterBar,
QMainWindow[contrastMode="high"] QFrame#activityEventCard,
QMainWindow[contrastMode="high"] QPlainTextEdit#activityTimelineDetails,
QDialog[contrastMode="high"] QTableWidget#generationHistoryTable,
QDialog[contrastMode="high"] QFrame#historyMetricCard,
QDialog[contrastMode="high"] QFrame#reportMetricCard {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE30_OPERATIONAL_HISTORY_STYLE
LIGHT_STYLE += _PHASE30_OPERATIONAL_HISTORY_STYLE
GRAPHITE_STYLE += _PHASE30_OPERATIONAL_HISTORY_STYLE

# Phase 31 provider workspace and voice configuration UX.
_PHASE31_PROVIDER_WORKSPACE_STYLE = r"""
QFrame#providerPanelHeader,
QFrame#providerOverviewCard,
QFrame#providerSection {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QFrame#providerPanelHeader {
    border-color: palette(dark);
}
QFrame#providerOverviewCard {
    border-color: palette(dark);
}
QLabel#providerOverviewIcon {
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 7px;
}
QLabel#providerOverviewName {
    color: palette(window-text);
    font-size: 14px;
    font-weight: 850;
}
QLabel#providerOverviewMode,
QLabel#providerOverviewCaption,
QLabel#providerSectionDescription {
    color: palette(mid);
    font-size: 10px;
}
QLabel#providerOverviewCaption {
    font-weight: 700;
}
QLabel#providerOverviewValue {
    color: palette(window-text);
    font-size: 11px;
    font-weight: 650;
}
QFrame#providerCapabilityHost {
    background: transparent;
    border: 0;
}
QLabel#providerCapabilityBadge {
    min-height: 18px;
    padding: 2px 6px;
    color: palette(window-text);
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    font-size: 9px;
    font-weight: 700;
}
QLabel#providerReadinessBadge {
    min-height: 20px;
    padding: 3px 8px;
    color: palette(mid);
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#providerReadinessBadge[tone="success"] {
    color: #22C55E;
    background: rgba(34, 197, 94, 0.10);
    border-color: #16A34A;
}
QLabel#providerReadinessBadge[tone="warning"] {
    color: #F59E0B;
    background: rgba(245, 158, 11, 0.11);
    border-color: #D97706;
}
QLabel#providerReadinessBadge[tone="error"] {
    color: #EF4444;
    background: rgba(239, 68, 68, 0.10);
    border-color: #DC2626;
}
QLabel#providerReadinessBadge[tone="running"] {
    color: #2DD4BF;
    background: rgba(20, 184, 166, 0.11);
    border-color: #0D9488;
}
QLabel#providerNextStep {
    padding: 7px 8px;
    color: palette(window-text);
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    font-size: 10px;
    font-weight: 650;
}
QLabel#providerSectionDescription {
    padding: 0 0 3px 0;
}
QFrame#providerSection QFrame#providerField {
    background: transparent;
    border: 0;
}
QFrame#providerSection QLineEdit,
QFrame#providerSection QComboBox,
QFrame#providerSection QAbstractSpinBox {
    min-height: 26px;
}
QFrame#providerSection QPushButton#connectionStatus {
    min-height: 52px;
    max-height: 52px;
    padding: 7px 10px;
    background: palette(alternate-base);
    border-color: palette(midlight);
}
QMainWindow[contrastMode="high"] QFrame#providerPanelHeader,
QMainWindow[contrastMode="high"] QFrame#providerOverviewCard,
QMainWindow[contrastMode="high"] QFrame#providerSection,
QMainWindow[contrastMode="high"] QLabel#providerNextStep {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE31_PROVIDER_WORKSPACE_STYLE
LIGHT_STYLE += _PHASE31_PROVIDER_WORKSPACE_STYLE
GRAPHITE_STYLE += _PHASE31_PROVIDER_WORKSPACE_STYLE

# Phase 90 provider intelligence and voice-selection decision surface.
_PHASE90_PROVIDER_INTELLIGENCE_STYLE = r"""
QFrame#providerIntelligenceCard {
    background: palette(base);
    border: 1px solid palette(dark);
    border-radius: 10px;
}
QFrame#providerIntelligenceCard QLabel#providerOverviewValue[tone="success"] {
    color: #22C55E;
}
QFrame#providerIntelligenceCard QLabel#providerOverviewValue[tone="warning"] {
    color: #F59E0B;
}
QFrame#providerIntelligenceCard QLabel#providerOverviewValue[tone="error"] {
    color: #EF4444;
}
QFrame#providerIntelligenceCard QLabel#providerOverviewValue[tone="neutral"] {
    color: palette(mid);
}
QFrame#providerIntelligenceCard QPushButton#primaryQuietButton,
QFrame#providerIntelligenceCard QPushButton#secondaryQuietButton {
    min-height: 28px;
}
QMainWindow[contrastMode="high"] QFrame#providerIntelligenceCard {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE90_PROVIDER_INTELLIGENCE_STYLE
LIGHT_STYLE += _PHASE90_PROVIDER_INTELLIGENCE_STYLE
GRAPHITE_STYLE += _PHASE90_PROVIDER_INTELLIGENCE_STYLE

# Phase 32 audio output, playback and file handoff UX.
_PHASE32_OUTPUT_PLAYBACK_STYLE = r"""
QWidget#outputPlaybackWorkspace {
    background: transparent;
}
QFrame#outputWorkspaceHeader,
QFrame#outputPlayerCard,
QFrame#outputFileCard,
QFrame#outputReviewCard,
QFrame#outputLogHeader,
QFrame#audioPlayerHeader,
QFrame#audioTransportBar {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QFrame#outputWorkspaceHeader,
QFrame#outputPlayerCard,
QFrame#outputFileCard,
QFrame#outputReviewCard {
    border-color: palette(dark);
}
QLabel#outputWorkspaceTitle {
    color: palette(window-text);
    font-size: 14px;
    font-weight: 850;
}
QLabel#outputWorkspaceSubtitle,
QLabel#outputFileMetadata,
QLabel#audioTimeLabel,
QLabel#audioControlLabel {
    color: palette(mid);
    font-size: 10px;
}
QLabel#outputSectionTitle {
    color: palette(window-text);
    font-size: 11px;
    font-weight: 800;
}
QLabel#outputWorkspaceStatus,
QLabel#audioPlayerStatus {
    min-height: 20px;
    padding: 3px 8px;
    color: palette(mid);
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#outputWorkspaceStatus[tone="success"],
QLabel#audioPlayerStatus[tone="success"] {
    color: #22C55E;
    background: rgba(34, 197, 94, 0.10);
    border-color: #16A34A;
}
QLabel#outputWorkspaceStatus[tone="running"],
QLabel#audioPlayerStatus[tone="running"] {
    color: #2DD4BF;
    background: rgba(20, 184, 166, 0.11);
    border-color: #0D9488;
}
QLabel#outputWorkspaceStatus[tone="warning"],
QLabel#audioPlayerStatus[tone="warning"] {
    color: #F59E0B;
    background: rgba(245, 158, 11, 0.11);
    border-color: #D97706;
}
QLabel#outputWorkspaceStatus[tone="error"],
QLabel#audioPlayerStatus[tone="error"] {
    color: #EF4444;
    background: rgba(239, 68, 68, 0.10);
    border-color: #DC2626;
}
QLabel#audioPlayerFilename,
QLabel#outputFilePath {
    color: palette(window-text);
    font-weight: 700;
}
QLabel#outputFilePath {
    padding: 7px 8px;
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QPushButton#audioPrimaryAction,
QPushButton#outputFileAction[primary="true"] {
    background: #2563EB;
    border-color: #2563EB;
    color: white;
    font-weight: 800;
}
QPushButton#audioPrimaryAction:hover,
QPushButton#outputFileAction[primary="true"]:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton#audioStopAction {
    color: #EF4444;
}
QPushButton#outputFileAction {
    min-height: 32px;
    padding: 5px 8px;
    text-align: left;
}
QPushButton#outputQuietAction {
    min-height: 26px;
    padding: 3px 8px;
    background: transparent;
}

QComboBox#outputReviewFilter,
QComboBox#outputReviewSelector,
QComboBox#outputExportScope,
QComboBox#outputExportPreset {
    min-height: 28px;
}
QPlainTextEdit#outputActivityLog {
    min-height: 64px;
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
    padding: 7px;
}
QSlider#audioSeekSlider::groove:horizontal,
QSlider#audioVolumeSlider::groove:horizontal {
    height: 5px;
    background: palette(midlight);
    border-radius: 2px;
}
QSlider#audioSeekSlider::handle:horizontal,
QSlider#audioVolumeSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0;
    background: #3B82F6;
    border: 1px solid #60A5FA;
    border-radius: 7px;
}
QMainWindow[contrastMode="high"] QFrame#outputWorkspaceHeader,
QMainWindow[contrastMode="high"] QFrame#outputPlayerCard,
QMainWindow[contrastMode="high"] QFrame#outputFileCard,
QMainWindow[contrastMode="high"] QFrame#outputReviewCard,
QMainWindow[contrastMode="high"] QFrame#audioPlayerHeader,
QMainWindow[contrastMode="high"] QFrame#audioTransportBar,
QMainWindow[contrastMode="high"] QPlainTextEdit#outputActivityLog {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _PHASE32_OUTPUT_PLAYBACK_STYLE
LIGHT_STYLE += _PHASE32_OUTPUT_PLAYBACK_STYLE
GRAPHITE_STYLE += _PHASE32_OUTPUT_PLAYBACK_STYLE

# Phase 33 Text Studio preparation and batch-editing workspace.
_TEXT_STUDIO_PREPARATION_STYLE = r"""
QWidget#textStudioWorkspace {
    background: palette(window);
}
QFrame#textStudioWorkspaceHeader,
QFrame#textStudioSourcesPanel,
QFrame#textStudioChunksPanel,
QFrame#textStudioEditorPanel,
QFrame#textStudioWorkspaceOptions,
QFrame#textStudioQualityPanel {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QFrame#textStudioWorkspaceHeader {
    border-color: palette(dark);
}
QLabel#workspaceTitle,
QLabel#textStudioQualityTitle {
    color: palette(window-text);
    font-size: 15px;
    font-weight: 800;
}
QLabel#workspaceSubtitle,
QLabel#textStudioQualitySubtitle,
QLabel#textStudioQualityDetail,
QLabel#textStudioWorkspaceMetrics {
    color: palette(mid);
}
QLabel#textStudioQualityStatus {
    min-height: 22px;
    padding: 3px 9px;
    border: 1px solid palette(midlight);
    border-radius: 10px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 10px;
    font-weight: 800;
}
QLabel#textStudioQualityStatus[tone="success"] {
    border-color: #16A34A;
    color: #22C55E;
    background: rgba(34, 197, 94, 0.11);
}
QLabel#textStudioQualityStatus[tone="warning"] {
    border-color: #D97706;
    color: #F59E0B;
    background: rgba(245, 158, 11, 0.12);
}
QLabel#textStudioQualityStatus[tone="error"] {
    border-color: #DC2626;
    color: #EF4444;
    background: rgba(239, 68, 68, 0.11);
}
QFrame#textStudioQualityMetric {
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QLabel#textStudioQualityMetricCaption {
    color: palette(mid);
    font-size: 9px;
    font-weight: 700;
}
QLabel#textStudioQualityMetricValue {
    color: palette(window-text);
    font-size: 14px;
    font-weight: 850;
}
QLineEdit#textStudioFindText,
QLineEdit#textStudioReplaceText {
    min-width: 130px;
}
QTreeWidget#textStudioDocumentExplorer,
QTableWidget#textStudioChunkTable {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    alternate-background-color: palette(alternate-base);
    gridline-color: transparent;
}
QTableWidget#textStudioChunkTable::item,
QTreeWidget#textStudioDocumentExplorer::item {
    padding: 5px 7px;
}
QMainWindow[contrastMode="high"] QFrame#textStudioWorkspaceHeader,
QMainWindow[contrastMode="high"] QFrame#textStudioQualityPanel,
QMainWindow[contrastMode="high"] QFrame#textStudioSourcesPanel,
QMainWindow[contrastMode="high"] QFrame#textStudioChunksPanel,
QMainWindow[contrastMode="high"] QFrame#textStudioEditorPanel {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _TEXT_STUDIO_PREPARATION_STYLE
LIGHT_STYLE += _TEXT_STUDIO_PREPARATION_STYLE
GRAPHITE_STYLE += _TEXT_STUDIO_PREPARATION_STYLE

# Phase 34 batch planning and preflight decision surface.
_BATCH_GENERATION_PLANNING_STYLE = r"""
QWidget#batchPlanSummary {
    background: transparent;
}
QFrame#batchPlanMetricCard {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 9px;
    min-height: 70px;
}
QFrame#batchPlanMetricCard[tone="success"] {
    border-color: #16A34A;
}
QFrame#batchPlanMetricCard[tone="warning"] {
    border-color: #D97706;
}
QFrame#batchPlanMetricCard[tone="error"] {
    border-color: #DC2626;
}
QLabel#batchPlanMetricTitle {
    color: palette(mid);
    font-size: 10px;
    font-weight: 700;
}
QLabel#batchPlanMetricValue {
    color: palette(window-text);
    font-size: 16px;
    font-weight: 850;
}
QLabel#batchPlanMetricDetail {
    color: palette(mid);
    font-size: 10px;
}
QFrame#batchPlanReasonCard {
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QLabel#batchPlanReason {
    color: palette(window-text);
    font-size: 11px;
}
QLabel#batchPlanReason[tone="success"] {
    color: #22C55E;
}
QLabel#batchPlanReason[tone="warning"] {
    color: #F59E0B;
}
QLabel#batchPlanReason[tone="error"] {
    color: #EF4444;
}
QTableWidget#batchPlanScenarioTable {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    gridline-color: transparent;
}
QTableWidget#batchPlanScenarioTable::item {
    padding: 6px 8px;
    border: 0;
}
QMainWindow[contrastMode="high"] QFrame#batchPlanMetricCard,
QMainWindow[contrastMode="high"] QFrame#batchPlanReasonCard,
QMainWindow[contrastMode="high"] QTableWidget#batchPlanScenarioTable {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _BATCH_GENERATION_PLANNING_STYLE
LIGHT_STYLE += _BATCH_GENERATION_PLANNING_STYLE
GRAPHITE_STYLE += _BATCH_GENERATION_PLANNING_STYLE

# Phase 35 safe launch review and explicit risk acknowledgement.
_GENERATION_LAUNCH_REVIEW_STYLE = r"""
QDialog#generationLaunchDialog QFrame#generationLaunchAcknowledgements {
    background: palette(alternate-base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QCheckBox#generationLaunchAcknowledgement {
    color: palette(window-text);
    spacing: 8px;
    min-height: 26px;
}
QCheckBox#generationLaunchAcknowledgement::indicator {
    width: 17px;
    height: 17px;
}
QTableWidget#generationLaunchChecklist,
QTableWidget#generationLaunchExistingOutputs {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 8px;
    gridline-color: transparent;
    alternate-background-color: palette(alternate-base);
}
QTableWidget#generationLaunchChecklist::item,
QTableWidget#generationLaunchExistingOutputs::item {
    padding: 6px 8px;
    border: 0;
}
QFrame#generationLaunchTools {
    background: transparent;
    border: 0;
}
QPushButton#generationLaunchCopyAction {
    min-height: 32px;
}
QLabel#generationLaunchNoAcknowledgement {
    color: #22C55E;
    font-weight: 700;
}
QMainWindow[contrastMode="high"] QFrame#generationLaunchAcknowledgements,
QMainWindow[contrastMode="high"] QTableWidget#generationLaunchChecklist,
QMainWindow[contrastMode="high"] QTableWidget#generationLaunchExistingOutputs {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _GENERATION_LAUNCH_REVIEW_STYLE
LIGHT_STYLE += _GENERATION_LAUNCH_REVIEW_STYLE
GRAPHITE_STYLE += _GENERATION_LAUNCH_REVIEW_STYLE


# Phase 51 visual-system hardening: selected-row contrast, balanced controls,
# consistent disclosure affordances, and modern cross-theme surfaces.
_PHASE51_VISUAL_SYSTEM_STYLE = r"""
QAbstractItemView {
    background: palette(base);
    color: palette(text);
    alternate-background-color: palette(alternate-base);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
    outline: 0;
}
QAbstractItemView::item:selected,
QAbstractItemView::item:selected:active,
QAbstractItemView::item:selected:!active,
QTableWidget::item:selected,
QTableView::item:selected,
QTreeView::item:selected,
QListView::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QAbstractItemView::item:hover:!selected {
    background: palette(midlight);
    color: palette(text);
}
QTableView#voiceCatalogTable::item:selected,
QTableView#queueTable::item:selected,
QTableWidget#queueTable::item:selected,
QTableWidget#sourcesTable::item:selected,
QTableWidget#providerProfilesTable::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
    font-weight: 650;
}
QHeaderView::section {
    color: palette(window-text);
}
QPushButton,
QToolButton {
    icon-size: 16px;
}
QPushButton:disabled,
QToolButton:disabled {
    color: palette(mid);
}
QToolButton#providerSectionHeader,
QToolButton#sectionHeader {
    min-height: 32px;
    padding: 4px 10px;
    border: 0;
    border-radius: 8px;
    text-align: left;
    icon-size: 14px;
}
QToolButton#providerSectionHeader:hover,
QToolButton#sectionHeader:hover {
    background: palette(alternate-base);
}
QToolButton#providerSectionHeader:checked,
QToolButton#sectionHeader:checked {
    background: palette(base);
}
QFrame#generationActionBar QPushButton {
    min-height: 28px;
    max-height: 30px;
    padding: 3px 11px;
    margin: 0;
}
QFrame#generationActionBar QPushButton#generationPrimaryAction {
    padding: 3px 14px;
}
QFrame#generationActionBar QLabel#workspaceStatusBadge {
    min-height: 26px;
    max-height: 28px;
    padding-top: 0;
    padding-bottom: 0;
}
QToolButton::menu-indicator {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 5px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
}
QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}
QFrame#voiceContextCard,
QFrame#voiceFilterCard,
QFrame#providerSection,
QFrame#queueWorkspaceHeading,
QFrame#queueRangeBar,
QFrame#queueCommandBar,
QFrame#generationActionBar,
QFrame#workspaceHero,
QFrame#projectContextStrip {
    border-color: palette(midlight);
}
QFrame#voiceContextCard,
QFrame#voiceFilterCard {
    border-radius: 10px;
}
QDialog#voiceBrowserDialog QLineEdit,
QDialog#voiceBrowserDialog QComboBox,
QDialog#voiceBrowserDialog QPushButton,
QDialog#voiceBrowserDialog QToolButton {
    min-height: 26px;
}
"""
DARK_STYLE += _PHASE51_VISUAL_SYSTEM_STYLE
LIGHT_STYLE += _PHASE51_VISUAL_SYSTEM_STYLE
GRAPHITE_STYLE += _PHASE51_VISUAL_SYSTEM_STYLE

# Phase 59 certification rules are deliberately shared across all themes so
# keyboard focus, selection and target-size contracts do not drift by palette.
_PHASE59_CERTIFICATION_STYLE = r"""
QMainWindow[focusMode="enhanced"] QAbstractButton:focus,
QMainWindow[focusMode="enhanced"] QAbstractItemView:focus,
QMainWindow[focusMode="enhanced"] QComboBox:focus,
QMainWindow[focusMode="enhanced"] QLineEdit:focus,
QMainWindow[focusMode="enhanced"] QAbstractSpinBox:focus,
QDialog[focusMode="enhanced"] QAbstractButton:focus,
QDialog[focusMode="enhanced"] QAbstractItemView:focus,
QDialog[focusMode="enhanced"] QComboBox:focus,
QDialog[focusMode="enhanced"] QLineEdit:focus,
QDialog[focusMode="enhanced"] QAbstractSpinBox:focus {
    border: 2px solid palette(highlight);
    padding: 4px;
}
QMenu::item:selected,
QComboBox QAbstractItemView::item:selected,
QListView::item:selected,
QTreeView::item:selected,
QTableView::item:selected,
QTableWidget::item:selected {
    background: palette(highlight);
    color: palette(highlighted-text);
}
QToolButton[accessibleIconOnly="true"],
QPushButton[accessibleIconOnly="true"] {
    min-width: 32px;
    min-height: 32px;
    padding: 4px;
}
QDialog#uxAccessibilityCertificationDialog QTabWidget::pane {
    border: 1px solid palette(midlight);
    border-radius: 8px;
}
QDialog#uxAccessibilityCertificationDialog QTableWidget {
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}
QMainWindow[contrastMode="high"] QMenu::item:selected,
QMainWindow[contrastMode="high"] QAbstractItemView::item:selected {
    border: 1px solid palette(highlighted-text);
}
"""
DARK_STYLE += _PHASE59_CERTIFICATION_STYLE
LIGHT_STYLE += _PHASE59_CERTIFICATION_STYLE
GRAPHITE_STYLE += _PHASE59_CERTIFICATION_STYLE

# Phase 91 Text / Source / Batch Preparation UX 2.0.
_TEXT_BATCH_PREPARATION_PHASE91_STYLE = r"""
QFrame#textBatchPreparationPanel {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}
QLabel#textBatchPreparationTitle {
    color: palette(window-text);
    font-size: 14px;
    font-weight: 800;
}
QLabel#textBatchPreparationSubtitle,
QLabel#textBatchPreparationDetail {
    color: palette(mid);
}
QLabel#textBatchPreparationStatus {
    min-height: 22px;
    padding: 3px 9px;
    border: 1px solid palette(midlight);
    border-radius: 10px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 10px;
    font-weight: 800;
}
QLabel#textBatchPreparationStatus[tone="success"] {
    border-color: #16A34A;
    color: #22C55E;
    background: rgba(34, 197, 94, 0.11);
}
QLabel#textBatchPreparationStatus[tone="warning"] {
    border-color: #D97706;
    color: #F59E0B;
    background: rgba(245, 158, 11, 0.12);
}
QLabel#textBatchPreparationStatus[tone="error"] {
    border-color: #DC2626;
    color: #EF4444;
    background: rgba(239, 68, 68, 0.11);
}
QLabel#textBatchPreparationStage {
    min-height: 24px;
    padding: 3px 7px;
    border: 1px solid palette(midlight);
    border-radius: 8px;
    background: palette(alternate-base);
    color: palette(mid);
    font-size: 10px;
    font-weight: 750;
}
QLabel#textBatchPreparationStage[status="pass"] {
    border-color: #16A34A;
    color: #22C55E;
}
QLabel#textBatchPreparationStage[status="warning"] {
    border-color: #D97706;
    color: #F59E0B;
}
QLabel#textBatchPreparationStage[status="block"] {
    border-color: #DC2626;
    color: #EF4444;
}
QPushButton#textBatchPreparationPrimary {
    min-height: 30px;
    padding: 4px 12px;
    font-weight: 800;
}
QMainWindow[contrastMode="high"] QFrame#textBatchPreparationPanel {
    border: 2px solid palette(highlight);
}
"""
DARK_STYLE += _TEXT_BATCH_PREPARATION_PHASE91_STYLE
LIGHT_STYLE += _TEXT_BATCH_PREPARATION_PHASE91_STYLE
GRAPHITE_STYLE += _TEXT_BATCH_PREPARATION_PHASE91_STYLE
