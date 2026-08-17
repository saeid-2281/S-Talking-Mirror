from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme_accessibility_v2 import (
    THEME_SURFACE_CANVAS_OBJECTS,
    THEME_SURFACE_COHERENCE_THEMES,
    THEME_SURFACE_RAISED_OBJECTS,
    theme_accessibility_stylesheet,
    theme_surface_coherence_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for
from scripts.certify_three_theme_surface_coherence_roadmap2_a121 import (
    CERTIFICATION_VERSION,
    EXPECTED_BASELINE_COMMIT,
    EXPECTED_THEME_SET,
    EXPECTED_THEMES,
    certify_window,
)


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_a121_locks_to_official_a12_hotfix1_baseline() -> None:
    assert EXPECTED_BASELINE_COMMIT == "babacdadda12663ac5d3d5bbcfe8514fcb65a8ee"
    assert CERTIFICATION_VERSION == "roadmap2-a12.1-v1"


def test_a121_program_exposes_exact_system_light_dark_public_theme_contract(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    available = frozenset(window.theme_manager.available_themes())
    public = frozenset(window.theme_actions)
    assert public == EXPECTED_THEME_SET
    assert EXPECTED_THEME_SET.issubset(available)
    assert frozenset(THEME_SURFACE_COHERENCE_THEMES) == EXPECTED_THEME_SET
    assert public.issubset(available)
    window.close()


def test_a121_final_overlay_targets_major_canvas_and_raised_surfaces() -> None:
    assert "applicationShell" in THEME_SURFACE_CANVAS_OBJECTS
    assert "workspaceLeftDock" in THEME_SURFACE_CANVAS_OBJECTS
    assert "generationMonitorDock" in THEME_SURFACE_CANVAS_OBJECTS
    assert "leftWorkspaceTabs" in THEME_SURFACE_CANVAS_OBJECTS
    assert "rightInspectorTabs" in THEME_SURFACE_CANVAS_OBJECTS
    assert "providerScrollArea" in THEME_SURFACE_CANVAS_OBJECTS
    assert "monitorScroll" in THEME_SURFACE_CANVAS_OBJECTS
    assert "providerSection" in THEME_SURFACE_RAISED_OBJECTS
    assert "selectedRowCard" in THEME_SURFACE_RAISED_OBJECTS
    assert "monitorHero" in THEME_SURFACE_RAISED_OBJECTS


def test_a121_dark_coherence_uses_one_soft_professional_surface_family() -> None:
    palette = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    stylesheet = theme_surface_coherence_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    assert f"background:{palette.canvas}" in stylesheet
    assert f"background:{palette.surface}" in stylesheet
    assert "#0A0F1C" not in stylesheet
    assert "#071326" not in stylesheet
    assert "Roadmap 2 A12.1" in stylesheet


def test_a121_light_coherence_uses_one_soft_professional_surface_family() -> None:
    palette = palette_for(is_dark=False, concept_key=ACTIVE_CONCEPT)
    stylesheet = theme_surface_coherence_stylesheet(
        is_dark=False,
        concept_key=ACTIVE_CONCEPT,
    )
    assert f"background:{palette.canvas}" in stylesheet
    assert f"background:{palette.surface}" in stylesheet
    assert "QScrollArea#providerScrollArea > QWidget > QWidget" in stylesheet
    assert "QScrollArea#monitorScroll > QWidget > QWidget" in stylesheet


def test_a121_accessibility_overlay_appends_surface_coherence_last() -> None:
    complete = theme_accessibility_stylesheet(
        is_dark=True,
        concept_key=ACTIVE_CONCEPT,
    )
    assert complete.index("Roadmap 2 A12.1") > complete.index("Roadmap 2 A11")


def test_a121_runtime_tags_same_surface_families_across_all_three_themes(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    for theme_name in EXPECTED_THEMES:
        window.apply_theme(theme_name)
        qt_app.processEvents()
        palette = window.theme_manager.palette(theme_name)
        expected_mode = (
            "dark"
            if palette.color(QPalette.ColorRole.Window).lightness() < 128
            else "light"
        )
        assert window.property("a11ThemeMode") == expected_mode
        assert window.application_shell.property("a121SurfaceFamily") == "canvas"
        assert window.left_dock.property("a121SurfaceFamily") == "canvas"
        assert window.right_dock.property("a121SurfaceFamily") == "canvas"
        assert window.left_tabs.property("a121SurfaceFamily") == "canvas"
        assert window.right_tabs.property("a121SurfaceFamily") == "canvas"
        assert window.queue_workspace.property("a121SurfaceFamily") == "surface"
        assert window.selected_row_panel.property("a121SurfaceFamily") == "surface"
    window.close()


def test_a121_preserves_qpalette_and_three_theme_authority(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    for theme_name in EXPECTED_THEMES:
        window.apply_theme(theme_name)
        qt_app.processEvents()
        api_palette = window.theme_manager.palette(theme_name)
        api_expected = window.theme_manager.tokens(theme_name)["app"].lower()
        assert api_palette.color(QPalette.ColorRole.Window).name().lower() == api_expected

        effective = window.theme_manager.effective_name(theme_name)
        expected_name = api_expected
        if effective == "Dark":
            expected_name = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT).canvas.lower()
        actual = QWidget.palette(window).color(QPalette.ColorRole.Window)
        assert actual.name().lower() == expected_name
        assert window.property("a11ResolvedTheme") == theme_name
    window.close()


def test_a121_is_presentation_only_and_does_not_add_workflow_authority() -> None:
    source = inspect.getsource(
        __import__(
            "app.gui.theme_accessibility_v2",
            fromlist=["theme_surface_coherence_stylesheet"],
        )
    )
    for token in (
        "start_generation(",
        "run_preflight(",
        "apply_smart_routing(",
        "setCurrentText(",
        "provider_changed(",
        "voice_changed(",
        "model_changed(",
        "language_changed(",
    ):
        assert token not in source


def test_a121_runtime_certifier_writes_three_theme_evidence(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path / "runtime")
    output = tmp_path / "evidence"
    result = certify_window(window, output)
    qt_app.processEvents()

    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert len(result["evidence"]) == 3
    assert {item["file"] for item in result["evidence"]} == {
        "theme-system.png",
        "theme-light.png",
        "theme-dark.png",
    }
    for item in result["evidence"]:
        path = output / item["file"]
        assert path.is_file()
        assert path.stat().st_size > 10_000
    window.close()
