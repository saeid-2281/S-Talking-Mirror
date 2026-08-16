from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QAbstractScrollArea

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme_accessibility_v2 import (
    ThemeAccessibilityModernizer,
    theme_surface_coherence_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(
                RuntimeConfig.from_root(tmp_path)
            )
        )
    )


def test_b2_theme_overlay_styles_dynamic_canvas_surface_families() -> None:
    stylesheet = theme_surface_coherence_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    assert '*[a121SurfaceFamily="canvas"]' in stylesheet
    assert '*[a121SurfaceFamily="surface"]' in stylesheet


def test_b2_modernizer_enumerates_runtime_tab_pages_and_scroll_viewports() -> None:
    source = inspect.getsource(ThemeAccessibilityModernizer)
    assert "_tag_tab_pages" in source
    assert ".viewport()" in source
    assert 'getattr(self.owner, "left_tabs", None)' in source
    assert 'getattr(self.owner, "right_tabs", None)' in source


def test_b2_dark_semantic_overlay_does_not_reintroduce_legacy_blue_canvas() -> None:
    stylesheet = theme_surface_coherence_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    assert "#0A0F1C" not in stylesheet
    assert "#071326" not in stylesheet


def test_b2_dark_dock_roots_resolve_to_same_semantic_canvas(
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
    for widget in (
        window.application_shell,
        window.left_dock,
        window.right_dock,
        window.left_tabs,
        window.right_tabs,
    ):
        assert widget.property("a121SurfaceFamily") == "canvas"
        actual = widget.palette().color(QPalette.ColorRole.Window)
        assert actual.name().lower() == semantic.canvas.lower()
    window.close()


def test_b2_dark_provider_page_viewport_and_content_share_canvas(
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
    assert page.property("a121SurfaceFamily") == "canvas"
    if isinstance(page, QAbstractScrollArea):
        assert page.viewport().property("a121SurfaceFamily") == "canvas"
        actual = page.viewport().palette().color(QPalette.ColorRole.Window)
        assert actual.name().lower() == semantic.canvas.lower()
        content = page.widget()
        assert content is not None
        assert content.property("a121SurfaceFamily") == "canvas"
    window.close()


def test_b2_dark_selected_row_is_semantic_surface_not_legacy_dock_canvas(
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
    assert (
        window.selected_row_panel.property("a121SurfaceFamily")
        == "surface"
    )
    actual = window.selected_row_panel.palette().color(
        QPalette.ColorRole.Window
    )
    assert actual.name().lower() == semantic.surface.lower()
    window.close()


def test_b2_monitor_scroll_viewport_and_content_are_semantic_canvas(
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
    assert scroll.property("a121SurfaceFamily") == "canvas"
    assert scroll.viewport().property("a121SurfaceFamily") == "canvas"
    actual = scroll.viewport().palette().color(
        QPalette.ColorRole.Window
    )
    assert actual.name().lower() == semantic.canvas.lower()
    assert scroll.widget() is not None
    assert scroll.widget().property("a121SurfaceFamily") == "canvas"
    window.close()


def test_b2_surface_contract_remains_structural_across_system_light_dark(
    qt_app,
    tmp_path: Path,
) -> None:
    window = _window(tmp_path)
    for theme_name in ("System", "Light", "Dark"):
        window.apply_theme(theme_name)
        qt_app.processEvents()
        assert window.left_dock.property("a121SurfaceFamily") == "canvas"
        assert window.right_dock.property("a121SurfaceFamily") == "canvas"
        assert (
            window.selected_row_panel.property("a121SurfaceFamily")
            == "surface"
        )
    window.close()
