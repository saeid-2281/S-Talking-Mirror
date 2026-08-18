"""Roadmap 2 A11 theme, dark-mode, and visual-accessibility contract.

A11 is presentation-only.  ``ThemeManager`` remains the QApplication/QPalette
and Light/Dark/System authority.  This layer certifies the selected Soft
Professional semantic palette, adds explicit contrast/focus/state semantics,
and propagates the resolved theme/accessibility mode to existing surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFontDialog,
    QFrame,
    QGroupBox,
    QLineEdit,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from app.gui.visual_design_system_v2 import (
    ACTIVE_CONCEPT,
    COMPONENTS,
    TYPOGRAPHY,
    SemanticPalette,
    palette_for,
)


THEME_SURFACE_COHERENCE_THEMES = ("System", "Light", "Dark")
THEME_SURFACE_CANVAS_OBJECTS = (
    "applicationShell",
    "workspaceLeftDock",
    "workspaceRightDock",
    "generationMonitorDock",
    "notificationCenterDock",
    "textStudioDock",
    "leftWorkspaceTabs",
    "rightInspectorTabs",
    "providerScrollArea",
    "monitorScroll",
)
THEME_NESTED_SURFACE_OBJECTS = (
    "collapsibleSection",
    "sectionContent",
    "providerFieldRow",
    "providerSection",
    "selectedRowCard",
    "monitorHero",
    "monitorProgressCard",
    "monitorOutputCard",
    "monitorFailureCard",
)


THEME_SURFACE_RAISED_OBJECTS = (
    "providerSection",
    "collapsibleSection",
    "selectedRowCard",
    "monitorHero",
    "monitorProgressCard",
    "monitorOutputCard",
    "monitorFailureCard",
)


WCAG_AA_NORMAL_TEXT = 4.5
WCAG_UI_COMPONENT = 3.0


@dataclass(frozen=True)
class ContrastCheck:
    name: str
    foreground: str
    background: str
    ratio: float
    minimum: float

    @property
    def passed(self) -> bool:
        return self.ratio >= self.minimum


def _rgb_component(value: int) -> float:
    channel = value / 255.0
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """Return WCAG relative luminance for a ``#RRGGBB`` color."""

    value = str(color).strip()
    if len(value) != 7 or not value.startswith("#"):
        raise ValueError(f"Expected #RRGGBB color, got {color!r}")
    try:
        red = int(value[1:3], 16)
        green = int(value[3:5], 16)
        blue = int(value[5:7], 16)
    except ValueError as exc:
        raise ValueError(f"Expected #RRGGBB color, got {color!r}") from exc
    return (
        0.2126 * _rgb_component(red)
        + 0.7152 * _rgb_component(green)
        + 0.0722 * _rgb_component(blue)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    """Return WCAG contrast ratio for two semantic colors."""

    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _text_on_soft_color(palette: SemanticPalette, *, is_dark: bool) -> str:
    # In the light theme the primary hover tone is intentionally used for text
    # on the tinted primary-soft surface.  The product primary remains unchanged
    # for filled actions, while small text clears AA contrast.
    return palette.primary if is_dark else palette.primary_hover


def soft_professional_contrast_audit(*, is_dark: bool) -> tuple[ContrastCheck, ...]:
    """Return the A11 AA/UI contrast evidence for the selected product palette."""

    palette = palette_for(is_dark=is_dark, concept_key=ACTIVE_CONCEPT)
    semantic_primary_text = _text_on_soft_color(palette, is_dark=is_dark)
    pairs = (
        ("text-primary/surface", palette.text_primary, palette.surface, WCAG_AA_NORMAL_TEXT),
        ("text-secondary/surface", palette.text_secondary, palette.surface, WCAG_AA_NORMAL_TEXT),
        ("text-muted/canvas", palette.text_muted, palette.canvas, WCAG_AA_NORMAL_TEXT),
        ("primary-action/inverse", palette.text_inverse, palette.primary, WCAG_AA_NORMAL_TEXT),
        ("primary-soft/text", semantic_primary_text, palette.primary_soft, WCAG_AA_NORMAL_TEXT),
        ("success-soft/text", palette.success, palette.success_soft, WCAG_AA_NORMAL_TEXT),
        ("warning-soft/text", palette.warning, palette.warning_soft, WCAG_AA_NORMAL_TEXT),
        ("danger-soft/text", palette.danger, palette.danger_soft, WCAG_AA_NORMAL_TEXT),
        ("info-soft/text", palette.info, palette.info_soft, WCAG_AA_NORMAL_TEXT),
        ("focus-ring/surface", palette.focus_ring, palette.surface, WCAG_UI_COMPONENT),
    )
    return tuple(
        ContrastCheck(name, foreground, background, contrast_ratio(foreground, background), minimum)
        for name, foreground, background, minimum in pairs
    )


def assert_soft_professional_contrast_contract() -> None:
    failures = [
        check
        for is_dark in (False, True)
        for check in soft_professional_contrast_audit(is_dark=is_dark)
        if not check.passed
    ]
    if failures:
        detail = ", ".join(f"{item.name}={item.ratio:.2f}" for item in failures)
        raise AssertionError(f"Soft Professional A11 contrast contract failed: {detail}")


class ThemeAccessibilityModernizer(QObject):
    """Propagate resolved theme/accessibility state without owning business logic."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.owner = owner
        self._installed = False
        self._is_dark = False
        self._theme_name = "Light"
        self._high_contrast = False
        self._enhanced_focus = False
        self._reduced_motion = False

    def install(self) -> None:
        application = QApplication.instance()
        if application is None or self._installed:
            return
        assert_soft_professional_contrast_contract()
        application.installEventFilter(self)
        self._installed = True
        preferences = getattr(self.owner, "interface_preferences", None)
        if preferences is not None:
            self.apply_preferences(preferences, refresh=False)
        self.refresh_surfaces()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Show and isinstance(watched, QDialog):
            if not isinstance(watched, (QFileDialog, QFontDialog)):
                self._apply_properties(watched)
        return False

    def apply_theme(self, name: str, *, is_dark: bool) -> None:
        self._theme_name = str(name or "System")
        self._is_dark = bool(is_dark)
        self.refresh_surfaces()

    def apply_preferences(self, preferences, *, refresh: bool = True) -> None:  # noqa: ANN001
        contrast = getattr(getattr(preferences, "contrast", None), "value", "standard")
        focus_style = getattr(getattr(preferences, "focus_style", None), "value", "standard")
        self._high_contrast = str(contrast).casefold() == "high"
        self._enhanced_focus = str(focus_style).casefold() == "enhanced"
        self._reduced_motion = bool(getattr(preferences, "reduce_motion", False))
        if refresh:
            self.refresh_surfaces()

    def refresh_surfaces(self) -> None:
        self._apply_properties(self.owner)
        application_shell = getattr(self.owner, "application_shell", None)
        if isinstance(application_shell, QWidget):
            self._apply_properties(application_shell)
        application = QApplication.instance()
        if application is None:
            return
        for widget in application.topLevelWidgets():
            if isinstance(widget, QDialog) and not isinstance(widget, (QFileDialog, QFontDialog)):
                self._apply_properties(widget)
        self._apply_surface_coherence_properties()

    def _set_surface_family(self, widget: QWidget, family: str) -> None:
        """Apply one semantic surface family to a structural runtime root.

        A12.1 originally tagged the dock roots but only styled a subset of
        object names.  Real runtime screenshots showed that tab pages and
        scroll-area viewports could therefore retain the legacy navy palette.
        B2 makes the semantic property authoritative and repolishes only when
        the family is first attached.
        """

        changed = widget.property("a121SurfaceFamily") != family
        widget.setProperty("a121SurfaceFamily", family)
        widget.setProperty("a121ThemeSet", "System|Light|Dark")

        semantic = palette_for(is_dark=self._is_dark, concept_key=ACTIVE_CONCEPT)
        background = semantic.canvas if family == "canvas" else semantic.surface
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(background))
        if isinstance(widget, QAbstractScrollArea):
            palette.setColor(QPalette.ColorRole.Base, QColor(background))
        widget.setPalette(palette)
        widget.setAutoFillBackground(True)

        if changed:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
        widget.update()

    def _tag_tab_pages(self, tabs: QWidget | None) -> None:
        if not isinstance(tabs, QTabWidget):
            return
        selected_row = getattr(self.owner, "selected_row_panel", None)
        for index in range(tabs.count()):
            page = tabs.widget(index)
            if not isinstance(page, QWidget):
                continue
            family = "surface" if page is selected_row else "canvas"
            self._set_surface_family(page, family)
            if isinstance(page, QAbstractScrollArea):
                viewport = page.viewport()
                if isinstance(viewport, QWidget):
                    self._set_surface_family(viewport, family)
                content = page.widget() if hasattr(page, "widget") else None
                if isinstance(content, QWidget):
                    self._set_surface_family(content, family)

    def _apply_surface_coherence_properties(self) -> None:
        for attribute in (
            "application_shell",
            "left_dock",
            "right_dock",
            "monitor_dock",
            "notification_dock",
            "text_studio_dock",
            "left_tabs",
            "right_tabs",
            "provider_panel",
            "monitor_scroll",
        ):
            widget = getattr(self.owner, attribute, None)
            if isinstance(widget, QWidget):
                self._set_surface_family(widget, "canvas")
        for attribute in (
            "queue_workspace",
            "selected_row_panel",
        ):
            widget = getattr(self.owner, attribute, None)
            if isinstance(widget, QWidget):
                self._set_surface_family(widget, "surface")

        # The actual Provider workspace is a scroll-area page supplied by the
        # extracted ProviderWorkspace widget, not necessarily owner.provider_scroll.
        # Enumerating pages closes the gap that remained visible in Dark mode.
        self._tag_tab_pages(getattr(self.owner, "left_tabs", None))
        self._tag_tab_pages(getattr(self.owner, "right_tabs", None))
        self._tag_nested_dock_surfaces(getattr(self.owner, "left_tabs", None))
        self._tag_nested_dock_surfaces(getattr(self.owner, "right_tabs", None))

    def _set_control_surface(self, widget: QWidget) -> None:
        changed = widget.property("a124ControlSurface") is not True
        widget.setProperty("a124ControlSurface", True)
        semantic = palette_for(is_dark=self._is_dark, concept_key=ACTIVE_CONCEPT)
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(semantic.surface_secondary))
        palette.setColor(QPalette.ColorRole.Window, QColor(semantic.surface_secondary))
        palette.setColor(QPalette.ColorRole.Text, QColor(semantic.text_primary))
        widget.setPalette(palette)
        if changed:
            style = widget.style()
            if style is not None:
                style.unpolish(widget)
                style.polish(widget)
        widget.update()

    def _tag_nested_dock_surfaces(self, root: QWidget | None) -> None:
        if not isinstance(root, QWidget):
            return
        for child in root.findChildren(QWidget):
            object_name = child.objectName()
            preserve_canvas = (
                isinstance(child, QAbstractScrollArea)
                or child.property("a121SurfaceFamily") == "canvas"
            )
            if not preserve_canvas:
                if object_name in THEME_NESTED_SURFACE_OBJECTS:
                    child.setProperty("a124NestedSurface", True)
                    self._set_surface_family(child, "surface")
                if (
                    isinstance(child, (QFrame, QGroupBox))
                    and object_name != "integratedDockTitle"
                ):
                    child.setProperty("a124NestedSurface", True)
                    self._set_surface_family(child, "surface")
            if isinstance(
                child,
                (QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit),
            ):
                self._set_control_surface(child)

    def _apply_properties(self, widget: QWidget) -> None:
        widget.setProperty("a11ThemeMode", "dark" if self._is_dark else "light")
        widget.setProperty("a11ResolvedTheme", self._theme_name)
        widget.setProperty("a11ContrastMode", "high" if self._high_contrast else "standard")
        widget.setProperty("a11FocusMode", "enhanced" if self._enhanced_focus else "standard")
        widget.setProperty("a11ReducedMotion", self._reduced_motion)



def theme_surface_coherence_stylesheet(
    *,
    is_dark: bool,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Return the final A12.1 three-theme surface reconciliation overlay."""

    palette = palette_for(is_dark=is_dark, concept_key=concept_key)
    return f"""
/* Roadmap 2 A12.1 — Three-Theme Surface Coherence */
/* Roadmap 2 B2 — Runtime structural roots use the semantic property itself. */
*[a121SurfaceFamily="canvas"] {{
    background:{palette.canvas};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
*[a121SurfaceFamily="surface"] {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QWidget#applicationShell,
QDockWidget#workspaceLeftDock,
QDockWidget#workspaceRightDock,
QDockWidget#generationMonitorDock,
QDockWidget#notificationCenterDock,
QDockWidget#textStudioDock,
QTabWidget#leftWorkspaceTabs,
QTabWidget#rightInspectorTabs,
QScrollArea#providerScrollArea,
QScrollArea#monitorScroll {{
    background:{palette.canvas};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QTabWidget#leftWorkspaceTabs::pane,
QTabWidget#rightInspectorTabs::pane {{
    background:{palette.canvas};
    border-color:{palette.border};
}}
QScrollArea#providerScrollArea > QWidget > QWidget,
QScrollArea#monitorScroll > QWidget > QWidget {{
    background:{palette.canvas};
    color:{palette.text_primary};
}}
QFrame#providerPanel {{
    background:{palette.canvas};
    color:{palette.text_primary};
}}
QFrame#providerSection,
QFrame#collapsibleSection,
QFrame#selectedRowCard,
QGroupBox#selectedRowCard,
QFrame#monitorHero,
QFrame#monitorProgressCard,
QFrame#monitorOutputCard,
QFrame#monitorFailureCard {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QWidget#monitorSectionPage {{
    background:{palette.canvas};
    color:{palette.text_primary};
}}
QFrame#integratedDockTitle {{
    background:transparent;
    color:{palette.text_secondary};
    border:0;
}}
QDockWidget#workspaceLeftDock *[a124NestedSurface="true"],
QDockWidget#workspaceRightDock *[a124NestedSurface="true"] {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QDockWidget#workspaceLeftDock *[a124ControlSurface="true"],
QDockWidget#workspaceRightDock *[a124ControlSurface="true"] {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border};
    selection-background-color:{palette.primary_soft};
    selection-color:{palette.text_primary};
}}
QDockWidget#workspaceLeftDock QToolButton#sectionHeader,
QDockWidget#workspaceRightDock QToolButton#sectionHeader {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
""".strip()



DARK_THEME_LEGACY_SURFACE_COLORS = (
    "#0B1220",
    "#0F1B31",
    "#1C2C46",
    "#111827",
    "#172033",
    "#071326",
    "#0A0F1C",
)


def dark_theme_completion_stylesheet(
    *,
    is_dark: bool,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Return the final dark-only Soft Professional surface completion layer.

    A12.1/B2/B4 established semantic surface families, but real B5 runtime
    evidence still showed broad legacy navy slabs in the Provider workspace,
    queue command rows, selected-row inspector, and Generation Monitor.  This
    last layer uses explicit high-specificity selectors for those structural
    hosts.  Small semantic action/status accents remain palette-driven.
    """

    if not is_dark:
        return ""

    palette = palette_for(is_dark=True, concept_key=concept_key)
    return f"""
/* Roadmap 2 B6 Hotfix 2 — Dark Theme Completion / Legacy Navy Surface Removal */
QWidget#applicationShell,
QDockWidget#workspaceLeftDock,
QDockWidget#workspaceRightDock,
QDockWidget#generationMonitorDock,
QDockWidget#notificationCenterDock,
QDockWidget#textStudioDock,
QTabWidget#leftWorkspaceTabs,
QTabWidget#rightInspectorTabs,
QScrollArea#providerScrollArea,
QScrollArea#monitorScroll,
QWidget#monitorSectionPage {{
    background:{palette.canvas};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QTabWidget#leftWorkspaceTabs::pane,
QTabWidget#rightInspectorTabs::pane {{
    background:{palette.canvas};
    border:1px solid {palette.border};
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab,
QTabWidget#rightInspectorTabs QTabBar::tab {{
    background:{palette.canvas};
    color:{palette.text_secondary};
    border-color:{palette.border};
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab:selected,
QTabWidget#rightInspectorTabs QTabBar::tab:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border_strong};
}}
QFrame#providerPanel,
QFrame#providerSection,
QFrame#collapsibleSection,
QFrame#selectedRowCard,
QGroupBox#selectedRowCard,
QFrame#monitorHero,
QFrame#monitorProgressCard,
QFrame#monitorOutputCard,
QFrame#monitorFailureCard,
QFrame#queueWorkspace,
QFrame#sourcesWorkspacePanel {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QFrame#queueWorkspaceHeading,
QFrame#queueRangeBar,
QFrame#queueCommandBar,
QFrame#sourcesWorkspaceHeader,
QFrame#sourcesActionBar,
QFrame#projectContextStrip,
QFrame#metricsStrip {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QFrame#providerFieldRow,
QWidget#sectionContent {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QPushButton#connectionStatus {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border:1px solid {palette.border};
}}
QPushButton#connectionStatus:hover {{
    background:{palette.surface};
    border-color:{palette.border_strong};
}}
QDockWidget#workspaceLeftDock QToolButton#sectionHeader:checked,
QDockWidget#workspaceRightDock QToolButton#sectionHeader:checked {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QTableView,
QTableWidget,
QListView,
QTreeView,
QPlainTextEdit,
QTextEdit {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
    selection-background-color:{palette.surface_secondary};
    selection-color:{palette.text_primary};
}}
QAbstractItemView::item:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-left:2px solid {palette.border_strong};
}}
QLineEdit,
QComboBox,
QAbstractSpinBox {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border};
    selection-background-color:{palette.surface};
    selection-color:{palette.text_primary};
}}
""".strip()


def ux_reality_reconciliation_stylesheet(
    *,
    is_dark: bool,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Final Soft Professional shell layer used after real-screen review.

    B6 Hotfix 2 removed known legacy navy literals, but manual review exposed
    uncovered inspector/account surfaces plus brittle menu and toolbar states.
    This layer is intentionally presentation-only and applies after every older
    stylesheet so historical QSS cannot reintroduce large technical-blue slabs.
    """

    palette = palette_for(is_dark=is_dark, concept_key=concept_key)
    common = f"""
/* Roadmap 2 B6 Hotfix 3 — UX Reality Reconciliation / Soft Professional Shell */
QMenuBar {{
    background:{palette.surface};
    color:{palette.text_primary};
    border:0;
    border-bottom:1px solid {palette.border};
    padding:3px 8px;
}}
QMenuBar::item {{
    background:transparent;
    color:{palette.text_primary};
    border:1px solid transparent;
    border-radius:7px;
    margin:1px 2px;
    padding:5px 10px;
}}
QMenuBar::item:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QMenuBar::item:pressed {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border_strong};
}}
QMenuBar::item:focus {{
    border-color:transparent;
}}
QMenu {{
    background:{palette.surface};
    color:{palette.text_primary};
    border:1px solid {palette.border};
    padding:5px;
}}
QMenu::item {{
    background:transparent;
    color:{palette.text_primary};
    border:1px solid transparent;
    border-radius:6px;
    margin:1px 2px;
    padding:6px 28px 6px 26px;
}}
QMenu::item:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QMenu::item:pressed, QMenu::item:checked {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
}}
QToolBar#mainToolbar {{
    background:{palette.surface};
    border:0;
    border-bottom:1px solid {palette.border};
    spacing:6px;
    padding:4px 10px;
}}
QToolBar#mainToolbar QToolButton {{
    background:transparent;
    color:{palette.text_primary};
    border:1px solid transparent;
    border-radius:8px;
    min-height:32px;
    padding:3px 9px;
}}
QToolBar#mainToolbar QToolButton:hover {{
    background:{palette.surface_secondary};
    border-color:{palette.border};
}}
QToolBar#mainToolbar QToolButton:pressed {{
    background:{palette.surface_secondary};
    border-color:{palette.border_strong};
}}
QToolButton#toolbarOverflowButton {{
    min-width:36px;
    min-height:32px;
    padding:4px;
}}
QFrame#workspaceHero,
QFrame#projectContextStrip,
QFrame#metricsStrip,
QFrame#queueWorkspace,
QFrame#queueWorkspaceHeading,
QFrame#queueRangeBar,
QFrame#queueCommandBar,
QFrame#queuePlanningRow,
QFrame#queueWorkspaceFooter,
QFrame#queueInspectorHeader,
QFrame#queueInspectorCard,
QFrame#queueInspectorActions,
QFrame#providerPanel,
QFrame#providerSection,
QFrame#collapsibleSection,
QFrame#monitorHero,
QFrame#monitorProgressCard,
QFrame#monitorOutputCard,
QFrame#monitorFailureCard {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QFrame#workspaceHero {{
    border:1px solid {palette.border};
    border-radius:12px;
}}
QFrame#queueInspectorCard,
QFrame#providerSection,
QFrame#collapsibleSection,
QFrame#monitorProgressCard,
QFrame#monitorOutputCard,
QFrame#monitorFailureCard {{
    border:1px solid {palette.border};
    border-radius:10px;
}}
QPlainTextEdit#queueDetailsText,
QPlainTextEdit#queueRetryHistory {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border:1px solid {palette.border};
    border-radius:8px;
}}
QDialog#providerAccountsDialog,
QDialog#providerAccountsDialog QWidget#qt_scrollarea_viewport,
QScrollArea#providerAccountDetailsScroll,
QWidget#providerAccountDetailsContent {{
    background:{palette.canvas};
    color:{palette.text_primary};
}}
QFrame#providerAccountsHeader,
QFrame#providerAccountsToolbar,
QFrame#providerAccountDetails {{
    background:{palette.surface};
    color:{palette.text_primary};
    border:1px solid {palette.border};
}}
QFrame#providerAccountsSummary,
QFrame#providerAccountIdentity,
QFrame#providerAccountQuotaCard,
QFrame#providerAccountCatalogCard,
QFrame#providerAccountMetadataCard {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border:1px solid {palette.border};
}}
QFrame#providerCatalogMetric {{
    background:{palette.surface};
    color:{palette.text_primary};
    border:1px solid {palette.border};
}}
QFrame#providerAccountDetailsActions {{
    background:{palette.surface};
    border:0;
}}
QLabel#accountStatus {{
    background:{palette.surface};
    color:{palette.text_secondary};
    border:1px solid {palette.border};
}}
QFrame#projectPathNotice {{
    background:{palette.warning_soft};
    color:{palette.text_primary};
    border:1px solid {palette.warning};
    border-radius:10px;
}}
QLabel#projectPathNoticeTitle {{
    color:{palette.text_primary};
    font-weight:800;
}}
QLabel#projectPathNoticeMessage {{
    color:{palette.text_secondary};
}}
QPushButton#projectPathNoticeAction,
QPushButton#projectPathNoticeDismiss {{
    background:{palette.surface};
    color:{palette.text_primary};
    border:1px solid {palette.border};
    border-radius:7px;
}}
QPushButton#projectPathNoticeAction:hover,
QPushButton#projectPathNoticeDismiss:hover {{
    background:{palette.surface_secondary};
    border-color:{palette.border_strong};
}}
""".strip()

    if not is_dark:
        return common

    dark_completion = f"""
/* B6 Hotfix 3 manual Dark review: broad accent-soft surfaces stay neutral. */
QTabWidget#leftWorkspaceTabs QTabBar::tab:selected,
QTabWidget#rightInspectorTabs QTabBar::tab:selected,
QAbstractItemView::item:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border_strong};
}}
QLabel#workspaceStatusBadge[tone="neutral"] {{
    background:{palette.surface_secondary};
    color:{palette.text_secondary};
    border-color:{palette.border};
}}
QToolButton#sectionHeader:checked,
QPushButton#connectionStatus,
QFrame#queueScopeSummary {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
""".strip()
    return common + "\n" + dark_completion




def manual_visual_acceptance_stylesheet(
    *,
    is_dark: bool,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Final pixel-level reconciliation after B6 Hotfix 3 manual screenshot review.

    The legacy theme still assigns a background to every QWidget. Child labels
    and the Provider Accounts table therefore retained exact legacy navy/base
    colors even when their structural parents had already moved to the
    Soft Professional semantic palette. This layer is deliberately last and
    uses object-specific selectors so passive text becomes transparent while
    real controls, statuses and selections retain semantic surfaces.
    """

    palette = palette_for(is_dark=is_dark, concept_key=concept_key)
    return f"""
/* Roadmap 2 B6 Hotfix 3 Hotfix 6 — Manual Visual Acceptance Reconciliation */
QFrame#workspaceHero QLabel,
QFrame#projectContextStrip QLabel,
QFrame#metricsStrip QLabel,
QFrame#queueWorkspaceHeading QLabel,
QFrame#queueRangeBar QLabel,
QFrame#queueCommandBar QLabel,
QFrame#queueScopeSummary QLabel,
QFrame#generationActionBar QLabel,
QFrame#queueWorkspaceFooter QLabel,
QFrame#queueInspectorHeader QLabel,
QFrame#queueInspectorCard QLabel,
QFrame#queueInspectorActions QLabel {{
    background:transparent;
}}

QDialog#providerAccountsDialog QLabel {{
    background:transparent;
}}
QDialog#providerAccountsDialog QWidget#providerAccountsAccountsPage,
QDialog#providerAccountsDialog QStackedWidget#providerAccountsTableStack,
QDialog#providerAccountsDialog QWidget#providerAccountsEmptyState {{
    background:{palette.canvas};
    color:{palette.text_primary};
}}
QFrame#providerAccountsCenterSummary {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border:1px solid {palette.border};
    border-radius:8px;
}}
QTabWidget#providerAccountsTabs::pane {{
    background:{palette.canvas};
    border:1px solid {palette.border};
}}
QTabWidget#providerAccountsTabs QTabBar {{
    background:{palette.canvas};
}}
QTabWidget#providerAccountsTabs QTabBar::tab {{
    background:{palette.surface};
    color:{palette.text_secondary};
    border:1px solid {palette.border};
    padding:7px 10px;
}}
QTabWidget#providerAccountsTabs QTabBar::tab:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border_strong};
}}
QSplitter#providerAccountsSplitter {{
    background:{palette.canvas};
}}
QSplitter#providerAccountsSplitter::handle {{
    background:{palette.border};
}}
QTableWidget#providerProfilesTable {{
    background:{palette.surface};
    alternate-background-color:{palette.surface_secondary};
    color:{palette.text_primary};
    border:1px solid {palette.border};
    border-radius:8px;
    gridline-color:transparent;
    selection-background-color:{palette.surface_secondary};
    selection-color:{palette.text_primary};
}}
QTableWidget#providerProfilesTable QWidget#qt_scrollarea_viewport {{
    background:{palette.surface};
    color:{palette.text_primary};
}}
QTableWidget#providerProfilesTable::item {{
    background:transparent;
    color:{palette.text_primary};
    border-bottom:1px solid {palette.border};
}}
QTableWidget#providerProfilesTable::item:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-left:2px solid {palette.primary};
}}
QHeaderView#providerProfilesHeader::section {{
    background:{palette.surface_secondary};
    color:{palette.text_secondary};
    border:0;
    border-bottom:1px solid {palette.border_strong};
    padding:5px 7px;
    font-weight:700;
}}
QDialog#providerAccountsDialog QScrollBar:horizontal,
QDialog#providerAccountsDialog QScrollBar:vertical {{
    background:{palette.canvas};
    border:0;
}}
QDialog#providerAccountsDialog QScrollBar::handle:horizontal,
QDialog#providerAccountsDialog QScrollBar::handle:vertical {{
    background:{palette.border_strong};
    border:0;
    border-radius:5px;
    min-width:34px;
    min-height:34px;
}}
QDialog#providerAccountsDialog QScrollBar::add-line,
QDialog#providerAccountsDialog QScrollBar::sub-line {{
    width:0;
    height:0;
}}

QDialog#providerAccountsDialog QLabel#accountStatus {{
    background:{palette.surface};
    color:{palette.text_secondary};
    border:1px solid {palette.border};
    border-radius:8px;
}}
QDialog#providerAccountsDialog QLabel#accountStatusBadge {{
    background:{palette.surface};
    color:{palette.text_secondary};
    border:1px solid {palette.border};
}}
QDialog#providerAccountsDialog QLabel#accountStatusBadge[status="active"],
QDialog#providerAccountsDialog QLabel#accountStatusBadge[status="success"] {{
    background:{palette.success_soft};
    color:{palette.success};
    border-color:{palette.success};
}}
QDialog#providerAccountsDialog QLabel#accountStatusBadge[status="error"] {{
    background:{palette.danger_soft};
    color:{palette.danger};
    border-color:{palette.danger};
}}
QDialog#providerAccountsDialog QLabel#accountStatusBadge[status="info"] {{
    background:{palette.info_soft};
    color:{palette.info};
    border-color:{palette.info};
}}

QPushButton[primary="true"],
QPushButton#primaryButton,
QPushButton#startGenerationButton,
QPushButton#generationPrimaryAction,
QPushButton#professionalEmptyStatePrimary {{
    background:{palette.primary};
    color:{palette.text_inverse};
    border-color:{palette.primary};
}}
QPushButton[primary="true"]:hover,
QPushButton#primaryButton:hover,
QPushButton#startGenerationButton:hover,
QPushButton#generationPrimaryAction:hover,
QPushButton#professionalEmptyStatePrimary:hover {{
    background:{palette.primary_hover};
    color:{palette.text_inverse};
    border-color:{palette.primary_hover};
}}

QLabel#workspaceStatusBadge[tone="info"],
QLabel#generationStateBadge[tone="info"] {{
    background:{palette.info_soft};
    color:{palette.info};
    border-color:{palette.info};
}}
QLabel#workspaceStatusBadge[tone="success"],
QLabel#generationStateBadge[tone="success"] {{
    background:{palette.success_soft};
    color:{palette.success};
    border-color:{palette.success};
}}
QLabel#workspaceStatusBadge[tone="warning"],
QLabel#generationStateBadge[tone="warning"] {{
    background:{palette.warning_soft};
    color:{palette.warning};
    border-color:{palette.warning};
}}
QLabel#workspaceStatusBadge[tone="error"],
QLabel#generationStateBadge[tone="error"] {{
    background:{palette.danger_soft};
    color:{palette.danger};
    border-color:{palette.danger};
}}

/* Roadmap 2 B6 Hotfix 3 Hotfix 7 — Main Shell Legacy Surface Drain */
QWidget#applicationShell,
QWidget#activityWorkspace,
QTabWidget#activityWorkspace {{
    background:{palette.canvas};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QFrame#workspaceHero,
QFrame#projectContextStrip,
QFrame#generationActionBar,
QFrame#providerPanelHeader,
QFrame#providerOverviewCard,
QFrame#providerIntelligenceCard,
QFrame#queueWorkspaceHeading,
QFrame#queueRangeBar,
QFrame#queueCommandBar,
QFrame#queuePlanningRow,
QFrame#queueWorkspaceFooter,
QFrame#queueInspectorHeader,
QFrame#queueInspectorCard,
QFrame#queueInspectorActions {{
    background:{palette.surface};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QFrame#metricPill,
QFrame#queueScopeSummary,
QWidget#generationJourney,
QWidget#generationJourneySteps {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border};
}}
QFrame#metricPill[active="true"] {{
    background:{palette.primary_soft};
    color:{palette.text_primary};
    border-color:{palette.primary};
}}
QFrame#providerPanelHeader QLabel,
QFrame#providerOverviewCard QLabel,
QFrame#providerIntelligenceCard QLabel,
QFrame#generationActionBar QLabel,
QFrame#metricPill QLabel {{
    background:transparent;
}}
QLabel#providerOverviewIcon,
QLabel#providerCapabilityBadge,
QLabel#providerReadinessBadge,
QLabel#providerNextStep {{
    background:{palette.surface_secondary};
    color:{palette.text_secondary};
    border-color:{palette.border};
}}
QLabel#providerReadinessBadge[tone="success"] {{
    background:{palette.success_soft};
    color:{palette.success};
    border-color:{palette.success};
}}
QLabel#providerReadinessBadge[tone="warning"] {{
    background:{palette.warning_soft};
    color:{palette.warning};
    border-color:{palette.warning};
}}
QLabel#providerReadinessBadge[tone="error"] {{
    background:{palette.danger_soft};
    color:{palette.danger};
    border-color:{palette.danger};
}}
QLabel#providerReadinessBadge[tone="running"] {{
    background:{palette.info_soft};
    color:{palette.info};
    border-color:{palette.info};
}}
QTabWidget#activityTabs::pane,
QTabWidget#activityWorkspace::pane {{
    background:{palette.canvas};
    border:1px solid {palette.border};
}}
QTabWidget#activityTabs QTabBar::tab,
QTabWidget#activityWorkspace QTabBar::tab {{
    background:{palette.canvas};
    color:{palette.text_secondary};
    border-color:{palette.border};
}}
QTabWidget#activityTabs QTabBar::tab:selected,
QTabWidget#activityWorkspace QTabBar::tab:selected {{
    background:{palette.surface_secondary};
    color:{palette.text_primary};
    border-color:{palette.border_strong};
}}
QStatusBar {{
    background:{palette.surface};
    color:{palette.text_secondary};
    border-top:1px solid {palette.border};
}}
QStatusBar QLabel,
QStatusBar QPushButton {{
    background:transparent;
}}

/* Explicitly outrank historical ID/property selectors that still paint #2563EB. */
QPushButton#queuePrimaryAction,
QPushButton#queueInspectorAction[primary="true"],
QPushButton#monitorPrimaryAction,
QPushButton#sourcesActionButton[primary="true"],
QPushButton#dialogPrimaryAction,
QPushButton#historyOpenReportButton,
QPushButton#historyExportButton,
QPushButton#reportPrimaryAction,
QPushButton#audioPrimaryAction,
QPushButton#outputFileAction[primary="true"] {{
    background:{palette.primary};
    color:{palette.text_inverse};
    border-color:{palette.primary};
}}
QPushButton#queuePrimaryAction:hover,
QPushButton#queueInspectorAction[primary="true"]:hover,
QPushButton#monitorPrimaryAction:hover,
QPushButton#sourcesActionButton[primary="true"]:hover,
QPushButton#dialogPrimaryAction:hover,
QPushButton#historyOpenReportButton:hover,
QPushButton#historyExportButton:hover,
QPushButton#reportPrimaryAction:hover,
QPushButton#audioPrimaryAction:hover,
QPushButton#outputFileAction[primary="true"]:hover {{
    background:{palette.primary_hover};
    color:{palette.text_inverse};
    border-color:{palette.primary_hover};
}}
""".strip()



def soft_professional_vertical_rhythm_stylesheet(
    *,
    is_dark: bool,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Final B6 portable-acceptance typography and control-rhythm layer.

    The A8 concept defines one compact desktop type scale (11/12/13/14/18)
    and 34px compact controls. Historical component styles accumulated 9, 10,
    11, 12 and 13px body/control text plus 26/30/32/34px controls.  That drift
    reads as visual noise on a large monitor even when every individual widget
    remains usable.  This layer normalizes the real main shell without touching
    dialogs, generation authority or density semantics.
    """

    palette = palette_for(is_dark=is_dark, concept_key=concept_key)
    t = TYPOGRAPHY
    control = COMPONENTS.control_compact_height
    return f"""
/* Roadmap 2 B6 Hotfix 3 Hotfix 9 — Vertical Rhythm & Typography Unification */
QMenuBar,
QToolBar#mainToolbar QToolButton,
QFrame#generationActionBar QPushButton,
QWidget#queueWorkspace QPushButton,
QWidget#queueWorkspace QToolButton,
QWidget#queueWorkspace QLineEdit,
QWidget#queueWorkspace QComboBox,
QDockWidget#workspaceLeftDock QPushButton,
QDockWidget#workspaceLeftDock QToolButton,
QDockWidget#workspaceLeftDock QLineEdit,
QDockWidget#workspaceLeftDock QComboBox,
QDockWidget#workspaceLeftDock QAbstractSpinBox,
QDockWidget#workspaceRightDock QPushButton,
QDockWidget#workspaceRightDock QToolButton,
QDockWidget#workspaceRightDock QLineEdit,
QDockWidget#workspaceRightDock QComboBox,
QDockWidget#workspaceRightDock QAbstractSpinBox {{
    font-family:{t.family};
    font-size:{t.body}px;
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab,
QTabWidget#rightInspectorTabs QTabBar::tab,
QTabWidget#activityTabs QTabBar::tab {{
    font-family:{t.family};
    font-size:{t.body}px;
    font-weight:{t.medium_weight};
}}
QLabel#workspaceProjectTitle {{
    font-family:{t.family};
    font-size:{t.title}px;
    font-weight:{t.bold_weight};
}}
QLabel#queueWorkspaceTitle,
QLabel#panelTitle {{
    font-family:{t.family};
    font-size:{t.section}px;
    font-weight:{t.bold_weight};
}}
QLabel#workspaceProjectSubtitle,
QLabel#queueWorkspaceSubtitle,
QLabel#panelSubtitle,
QLabel#generationProgressLabel,
QLabel#metricCaption,
QLabel#cardCaption,
QLabel#queueCommandSectionLabel,
QLabel#formLabel {{
    font-family:{t.family};
    font-size:{t.caption}px;
    font-weight:{t.regular_weight};
}}
QLabel#metricValue,
QLabel#cardValue,
QLabel#queueVisibleSummary,
QLabel#queueSelectedSummary,
QLabel#queueActiveScope,
QLabel#generationStateBadge,
QStatusBar {{
    font-family:{t.family};
    font-size:{t.label}px;
}}
QFrame#generationActionBar QPushButton,
QWidget#queueWorkspace QPushButton,
QWidget#queueWorkspace QToolButton,
QWidget#queueWorkspace QLineEdit,
QWidget#queueWorkspace QComboBox {{
    min-height:{control}px;
    max-height:{control}px;
    padding-top:0;
    padding-bottom:0;
}}
QFrame#generationActionBar QPushButton,
QWidget#queueWorkspace QPushButton,
QWidget#queueWorkspace QToolButton {{
    font-weight:{t.medium_weight};
}}
QFrame#generationActionBar QPushButton[primary="true"],
QPushButton#queuePrimaryAction,
QWidget#emptyState QPushButton[primary="true"] {{
    font-weight:{t.semibold_weight};
}}
QLabel#generationStateBadge {{
    min-height:{control}px;
    max-height:{control}px;
    padding:0 9px;
    border-radius:8px;
    font-weight:{t.semibold_weight};
}}
QToolButton#queueActionMenu {{
    min-width:{control}px;
    padding-left:7px;
    padding-right:7px;
}}
QFrame#queueCommandBar {{
    background:{palette.surface_secondary};
}}
""".strip()

def theme_accessibility_stylesheet(
    *,
    is_dark: bool,
    high_contrast: bool = False,
    enhanced_focus: bool = False,
    concept_key: str = ACTIVE_CONCEPT,
) -> str:
    """Return the final A11 Light/Dark accessibility overlay."""

    palette = palette_for(is_dark=is_dark, concept_key=concept_key)
    semantic_primary_text = _text_on_soft_color(palette, is_dark=is_dark)
    focus_width = 2 if enhanced_focus else 1
    boundary = palette.text_secondary if high_contrast else palette.border_strong
    muted = palette.text_secondary if high_contrast else palette.text_muted

    return f"""
/* Roadmap 2 A11 — Theme, Dark Mode & Visual Accessibility */
QToolTip {{
    background:{palette.surface}; color:{palette.text_primary};
    border:1px solid {boundary}; border-radius:6px; padding:5px 7px;
}}
QMenu::item:disabled, QToolButton:disabled, QPushButton:disabled {{
    color:{muted}; background:transparent;
}}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled,
QPlainTextEdit:disabled, QTextEdit:disabled {{
    background:{palette.surface_secondary}; color:{muted}; border-color:{palette.border};
}}
QPushButton:focus, QToolButton:focus {{
    border:{focus_width}px solid {palette.focus_ring};
}}
QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus, QTableView:focus, QTreeView:focus, QListView:focus {{
    border:{focus_width}px solid {palette.focus_ring};
}}
QAbstractItemView::item:selected {{
    background:{palette.primary_soft}; color:{palette.text_primary};
    border-left:2px solid {palette.primary};
}}
QLabel#queueFocusBadge, QPushButton#queuePrimaryAction {{
    color:{semantic_primary_text};
}}
QLabel#metricCaption, QLabel#cardCaption, QLabel#queueWorkspaceSubtitle,
QLabel#queueCommandSectionLabel, QLabel#formLabel, QStatusBar {{
    color:{muted};
}}
QLabel[status="success"], QLabel[state="completed"] {{
    color:{palette.success}; background:{palette.success_soft};
    border:1px solid {palette.success}; border-radius:6px; font-weight:700;
}}
QLabel[status="warning"], QLabel[state="running"] {{
    color:{palette.warning}; background:{palette.warning_soft};
    border:1px solid {palette.warning}; border-radius:6px; font-weight:700;
}}
QLabel[status="danger"], QLabel[state="failed"] {{
    color:{palette.danger}; background:{palette.danger_soft};
    border:1px solid {palette.danger}; border-radius:6px; font-weight:700;
}}
QLabel[status="info"] {{
    color:{palette.info}; background:{palette.info_soft};
    border:1px solid {palette.info}; border-radius:6px; font-weight:700;
}}
QFrame#providerSection, QFrame#collapsibleSection, QFrame#selectedRowCard,
QGroupBox#selectedRowCard, QDialog[a10Modernized="true"] QGroupBox[visualRole="formSection"] {{
    border-color:{boundary};
}}
""".strip() + "\n" + theme_surface_coherence_stylesheet(
        is_dark=is_dark,
        concept_key=concept_key,
    ) + "\n" + dark_theme_completion_stylesheet(
        is_dark=is_dark,
        concept_key=concept_key,
    ) + "\n" + ux_reality_reconciliation_stylesheet(
        is_dark=is_dark,
        concept_key=concept_key,
    ) + "\n" + manual_visual_acceptance_stylesheet(
        is_dark=is_dark,
        concept_key=concept_key,
    ) + "\n" + soft_professional_vertical_rhythm_stylesheet(
        is_dark=is_dark,
        concept_key=concept_key,
    )
