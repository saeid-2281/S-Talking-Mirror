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
    QDialog,
    QFileDialog,
    QFontDialog,
    QTabWidget,
    QWidget,
)

from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, SemanticPalette, palette_for


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
    )
