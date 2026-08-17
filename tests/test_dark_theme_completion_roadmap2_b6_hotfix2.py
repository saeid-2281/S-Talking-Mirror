from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme_accessibility_v2 import (
    DARK_THEME_LEGACY_SURFACE_COLORS,
    dark_theme_completion_stylesheet,
    theme_accessibility_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_hotfix2_completion_layer_is_dark_only() -> None:
    assert dark_theme_completion_stylesheet(is_dark=False) == ""
    assert "Dark Theme Completion" in dark_theme_completion_stylesheet(is_dark=True)


def test_hotfix2_completion_targets_real_legacy_surface_hosts() -> None:
    stylesheet = dark_theme_completion_stylesheet(is_dark=True)
    for selector in (
        "QDockWidget#workspaceLeftDock",
        "QDockWidget#workspaceRightDock",
        "QTabWidget#leftWorkspaceTabs",
        "QTabWidget#rightInspectorTabs",
        "QFrame#providerSection",
        "QFrame#queueWorkspace",
        "QFrame#selectedRowCard",
        "QFrame#monitorHero",
        "QPushButton#connectionStatus",
    ):
        assert selector in stylesheet


def test_hotfix2_completion_has_no_legacy_navy_literal() -> None:
    stylesheet = dark_theme_completion_stylesheet(is_dark=True).upper()
    assert all(color.upper() not in stylesheet for color in DARK_THEME_LEGACY_SURFACE_COLORS)


def test_hotfix2_dark_selection_uses_neutral_surface_not_primary_soft() -> None:
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    stylesheet = dark_theme_completion_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    assert f"selection-background-color:{semantic.surface_secondary}" in stylesheet
    assert f"border-left:2px solid {semantic.border_strong}" in stylesheet
    assert f"selection-background-color:{semantic.primary_soft}" not in stylesheet


def test_hotfix2_connection_status_uses_soft_professional_control_surface() -> None:
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    stylesheet = dark_theme_completion_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    connection_rule = stylesheet.split("QPushButton#connectionStatus {", 1)[1].split("}", 1)[0]
    assert f"background:{semantic.surface_secondary}" in connection_rule
    assert f"color:{semantic.text_primary}" in connection_rule
    assert f"border:1px solid {semantic.border}" in connection_rule


def test_hotfix2_completion_is_the_last_accessibility_overlay() -> None:
    stylesheet = theme_accessibility_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    completion_index = stylesheet.rfind("Roadmap 2 B6 Hotfix 2")
    coherence_index = stylesheet.rfind("Roadmap 2 A12.1")
    assert completion_index > coherence_index >= 0
    assert stylesheet.rstrip().endswith("}")


def test_hotfix2_runtime_major_roots_keep_semantic_dark_families(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)

    canvas_roots = (
        window.application_shell,
        window.left_dock,
        window.right_dock,
        window.left_tabs,
        window.right_tabs,
        window.monitor_scroll,
    )
    for widget in canvas_roots:
        assert widget.property("a121SurfaceFamily") == "canvas"
        assert (
            widget.palette().color(QPalette.ColorRole.Window).name().lower()
            == semantic.canvas.lower()
        )

    assert window.queue_workspace.property("a121SurfaceFamily") == "surface"
    assert window.selected_row_panel.property("a121SurfaceFamily") == "surface"
    window.close()


def test_hotfix2_three_theme_authority_remains_public_and_palette_driven(
    qt_app,
    tmp_path: Path,
) -> None:
    window = _window(tmp_path)
    for theme_name in ("System", "Light", "Dark"):
        window.apply_theme(theme_name)
        qt_app.processEvents()
        assert window.left_dock.property("a121ThemeSet") == "System|Light|Dark"
        assert window.right_dock.property("a121ThemeSet") == "System|Light|Dark"
    window.close()
