from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for
from scripts.certify_three_theme_surface_coherence_roadmap2_a121 import (
    _runtime_window_palette_expectation,
    certify_window,
)


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_hotfix8_h2_dark_certifier_preserves_api_palette_but_expects_projected_runtime(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()

    qpalette = window.theme_manager.palette("Dark")
    semantic = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT)
    rendered_expected, api_window, effective = _runtime_window_palette_expectation(
        window, "Dark", qpalette, semantic
    )

    assert api_window == window.theme_manager.tokens("Dark")["app"].lower()
    assert rendered_expected == semantic.canvas.lower()
    assert effective == "Dark"
    assert QWidget.palette(window).color(QPalette.Window).name().lower() == rendered_expected
    window.close()


def test_hotfix8_h2_light_certifier_keeps_historical_qpalette_as_rendered_authority(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.apply_theme("Light")
    qt_app.processEvents()

    qpalette = window.theme_manager.palette("Light")
    semantic = palette_for(is_dark=False, concept_key=ACTIVE_CONCEPT)
    rendered_expected, api_window, effective = _runtime_window_palette_expectation(
        window, "Light", qpalette, semantic
    )

    assert effective == "Light"
    assert rendered_expected == api_window
    assert QWidget.palette(window).color(QPalette.Window).name().lower() == rendered_expected
    window.close()


def test_hotfix8_h2_a121_certifier_accepts_projected_dark_runtime_and_keeps_three_theme_evidence(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path / "runtime")
    result = certify_window(window, tmp_path / "evidence")
    qt_app.processEvents()

    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    dark_check = next(item for item in result["checks"] if item["name"] == "dark_qpalette_authority")
    assert dark_check["passed"] is True
    assert "effective=Dark" in dark_check["detail"]
    assert "api=#0b1220" in dark_check["detail"]
    assert "rendered_expected=#121413" in dark_check["detail"]
    assert {item["file"] for item in result["evidence"]} == {
        "theme-system.png",
        "theme-light.png",
        "theme-dark.png",
    }
    window.close()
