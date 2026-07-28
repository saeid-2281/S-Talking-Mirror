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
QComboBox QAbstractItemView{{background:{tokens['overlay']};color:{tokens['text_primary']};selection-background-color:{tokens['selected_row']};border:1px solid {tokens['border']};padding:4px;}}
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
QTableWidget::item:selected{{background:{tokens['selected_row']};color:{tokens['text_primary']};}}
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
