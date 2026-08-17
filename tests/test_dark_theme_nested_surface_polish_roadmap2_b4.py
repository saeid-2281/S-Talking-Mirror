from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QLineEdit

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme_accessibility_v2 import (
    THEME_NESTED_SURFACE_OBJECTS,
    ThemeAccessibilityModernizer,
    theme_surface_coherence_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_b4_nested_contract_targets_provider_and_monitor_cards() -> None:
    assert "collapsibleSection" in THEME_NESTED_SURFACE_OBJECTS
    assert "providerFieldRow" in THEME_NESTED_SURFACE_OBJECTS
    assert "selectedRowCard" in THEME_NESTED_SURFACE_OBJECTS
    assert "monitorHero" in THEME_NESTED_SURFACE_OBJECTS


def test_b4_overlay_styles_nested_and_control_properties() -> None:
    stylesheet = theme_surface_coherence_stylesheet(is_dark=True, concept_key=ACTIVE_CONCEPT)
    assert '[a124NestedSurface="true"]' in stylesheet
    assert '[a124ControlSurface="true"]' in stylesheet
    assert "QDockWidget#workspaceLeftDock" in stylesheet
    assert "QDockWidget#workspaceRightDock" in stylesheet


def test_b4_dark_overlay_uses_semantic_surfaces_not_legacy_navy() -> None:
    stylesheet = theme_surface_coherence_stylesheet(is_dark=True, concept_key=ACTIVE_CONCEPT)
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    assert f"background:{semantic.surface}" in stylesheet
    assert f"background:{semantic.surface_secondary}" in stylesheet
    assert "#0A0F1C" not in stylesheet
    assert "#071326" not in stylesheet


def test_b4_modernizer_recursively_tags_frames_and_inputs() -> None:
    source = inspect.getsource(ThemeAccessibilityModernizer._tag_nested_dock_surfaces)
    assert "root.findChildren(QWidget)" in source
    assert "QFrame" in source
    assert "QGroupBox" in source
    assert "QLineEdit" in source
    assert "QComboBox" in source
    assert "_set_control_surface" in source


def test_b4_dark_provider_frames_resolve_to_semantic_surface(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    frames = [
        child
        for child in window.left_tabs.findChildren(QFrame)
        if child.property("a124NestedSurface") is True
    ]
    assert frames
    assert all(
        child.palette().color(QPalette.ColorRole.Window).name().lower() == semantic.surface.lower()
        for child in frames
    )
    window.close()


def test_b4_dark_provider_inputs_use_secondary_surface(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    tagged = [
        child
        for child in window.left_tabs.findChildren(QLineEdit)
        if child.property("a124ControlSurface") is True
    ]
    assert tagged
    assert all(
        child.palette().color(QPalette.ColorRole.Base).name().lower()
        == semantic.surface_secondary.lower()
        for child in tagged
    )
    window.close()


def test_b4_right_inspector_uses_same_nested_surface_system(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()
    frames = [
        child
        for child in window.right_tabs.findChildren(QFrame)
        if child.property("a124NestedSurface") is True
    ]
    assert frames
    window.close()


def test_b4_nested_surface_properties_survive_three_themes(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    for theme_name in ("System", "Light", "Dark"):
        window.apply_theme(theme_name)
        qt_app.processEvents()
        frames = [
            child
            for child in window.left_tabs.findChildren(QFrame)
            if child.property("a124NestedSurface") is True
        ]
        assert frames
        assert all(child.property("a121SurfaceFamily") == "surface" for child in frames)
    window.close()

def test_b4_nested_polish_preserves_provider_scroll_canvas_contract(
    qt_app,
    tmp_path: Path,
) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()
    semantic = palette_for(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    page = window.left_tabs.widget(0)
    assert isinstance(page, QAbstractScrollArea)
    assert page.property("a121SurfaceFamily") == "canvas"
    assert page.property("a124NestedSurface") is not True
    assert (
        page.palette()
        .color(QPalette.ColorRole.Window)
        .name()
        .lower()
        == semantic.canvas.lower()
    )
    assert page.viewport().property("a121SurfaceFamily") == "canvas"
    window.close()


def test_b4_nested_polish_preserves_monitor_scroll_canvas_contract(
    qt_app,
    tmp_path: Path,
) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()
    semantic = palette_for(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    scroll = window.monitor_scroll
    assert isinstance(scroll, QAbstractScrollArea)
    assert scroll.property("a121SurfaceFamily") == "canvas"
    assert scroll.property("a124NestedSurface") is not True
    assert (
        scroll.palette()
        .color(QPalette.ColorRole.Window)
        .name()
        .lower()
        == semantic.canvas.lower()
    )
    assert scroll.viewport().property("a121SurfaceFamily") == "canvas"
    window.close()
