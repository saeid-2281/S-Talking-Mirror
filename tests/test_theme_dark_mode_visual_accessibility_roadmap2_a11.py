from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.interface_preferences import ContrastMode, FocusStyle
from app.gui.main import MainWindow
from app.gui.theme import DARK_TOKENS, LIGHT_TOKENS, STATUS_COLORS
from app.gui.theme_accessibility_v2 import (
    ThemeAccessibilityModernizer,
    assert_soft_professional_contrast_contract,
    contrast_ratio,
    soft_professional_contrast_audit,
    theme_accessibility_stylesheet,
)
from app.gui.visual_design_system_v2 import (
    ACTIVE_CONCEPT,
    SOFT_PROFESSIONAL_DARK,
    SOFT_PROFESSIONAL_LIGHT,
    palette_for,
)


BASELINE_A10 = "f9678ec33768437e6e9e30ab7a9fc79440f63f87"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    container = create_service_container(runtime)
    return MainWindow(create_application_context(container))


def test_a11_keeps_soft_professional_direction_and_certifies_dark_counterpart() -> None:
    assert ACTIVE_CONCEPT == "soft_professional"
    assert SOFT_PROFESSIONAL_LIGHT.canvas == "#F7F6F3"
    assert SOFT_PROFESSIONAL_LIGHT.primary == "#5271C6"
    assert SOFT_PROFESSIONAL_LIGHT.text_muted == "#6C726B"
    assert SOFT_PROFESSIONAL_LIGHT.warning == "#8F5F1D"
    assert SOFT_PROFESSIONAL_DARK.canvas == "#121413"
    assert SOFT_PROFESSIONAL_DARK.surface == "#181B19"
    assert SOFT_PROFESSIONAL_DARK.primary == "#89A1E3"


def test_a11_semantic_contrast_audit_passes_light_and_dark_contracts() -> None:
    assert_soft_professional_contrast_contract()
    for is_dark in (False, True):
        checks = soft_professional_contrast_audit(is_dark=is_dark)
        assert len(checks) == 10
        assert all(check.passed for check in checks)
        assert all(check.ratio >= check.minimum for check in checks)

    assert contrast_ratio("#FFFFFF", "#5271C6") >= 4.5
    assert contrast_ratio("#6C726B", "#F7F6F3") >= 4.5


def test_a11_preserves_legacy_theme_and_status_token_contracts() -> None:
    assert DARK_TOKENS["canvas"] == "#0A0F1C"
    assert LIGHT_TOKENS["canvas"] == "#F3F6FA"
    assert STATUS_COLORS["skipped"] == "#94A3B8"


def test_a11_stylesheet_is_light_dark_aware_without_mainwindow_background_takeover() -> None:
    light = theme_accessibility_stylesheet(is_dark=False)
    dark = theme_accessibility_stylesheet(is_dark=True)
    assert "Roadmap 2 A11" in light
    assert "Roadmap 2 A11" in dark
    assert SOFT_PROFESSIONAL_LIGHT.focus_ring in light
    assert SOFT_PROFESSIONAL_DARK.focus_ring in dark
    assert SOFT_PROFESSIONAL_LIGHT.surface in light
    assert SOFT_PROFESSIONAL_DARK.surface in dark
    assert "QMainWindow" not in light
    assert "QMainWindow" not in dark


def test_a11_focus_high_contrast_selection_and_status_states_have_non_color_only_cues() -> None:
    standard = theme_accessibility_stylesheet(is_dark=False)
    enhanced = theme_accessibility_stylesheet(is_dark=False, enhanced_focus=True)
    high = theme_accessibility_stylesheet(is_dark=False, high_contrast=True)

    assert "border:1px solid #5271C6" in standard
    assert "border:2px solid #5271C6" in enhanced
    assert "border-left:2px solid #5271C6" in standard
    assert "QLabel[status=\"success\"]" in standard
    assert "background:#EAF5EF" in standard
    assert "font-weight:700" in standard
    assert SOFT_PROFESSIONAL_LIGHT.text_secondary in high


def test_a11_mainwindow_installs_theme_accessibility_layer_and_rebuilds_complete_overlay() -> None:
    build_source = inspect.getsource(MainWindow.build)
    theme_source = inspect.getsource(MainWindow.apply_theme)
    preferences_source = inspect.getsource(MainWindow.apply_interface_preferences)

    assert "ThemeAccessibilityModernizer(self)" in build_source
    assert "theme_accessibility_modernizer.install()" in build_source
    assert "theme_accessibility_stylesheet" in theme_source
    assert "dialog_form_stylesheet" in theme_source
    assert "theme_accessibility_modernizer.apply_theme" in theme_source
    assert "theme_accessibility_modernizer.apply_preferences" in preferences_source
    assert "if properties_changed:" in preferences_source
    assert "self.setStyleSheet(self.theme_manager.stylesheet" in preferences_source
    assert "application.setStyleSheet(stylesheet)" in preferences_source


def test_a11_runtime_dark_theme_preserves_qpalette_authority_and_resolves_dark_mode(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    qt_app.processEvents()

    historical = window.theme_manager.tokens("Dark")["app"].lower()
    expected = palette_for(is_dark=True, concept_key=ACTIVE_CONCEPT).canvas.lower()
    assert window.theme_manager.palette("Dark").color(QPalette.Window).name().lower() == historical
    assert QWidget.palette(window).color(QPalette.Window).name().lower() == expected
    assert window.property("a11ThemeMode") == "dark"
    assert window.application_shell.property("a11ThemeMode") == "dark"
    assert window.property("a11ResolvedTheme") == "Dark"
    assert "Roadmap 2 A11" in QApplication.instance().styleSheet()
    assert SOFT_PROFESSIONAL_DARK.surface in QApplication.instance().styleSheet()
    window.close()


def test_a11_system_theme_uses_resolved_palette_not_theme_name_guess(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("System")
    qt_app.processEvents()

    palette = window.theme_manager.palette("System")
    expected = "dark" if palette.color(QPalette.Window).lightness() < 128 else "light"
    assert window.property("a11ThemeMode") == expected
    assert window.property("a11ResolvedTheme") == "System"
    window.close()


def test_a11_open_a10_dialog_inherits_theme_accessibility_state_and_form_geometry(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.apply_theme("Dark")
    dialog = QDialog(window)
    layout = QVBoxLayout(dialog)
    label = QLabel("Profile")
    field = QLineEdit()
    label.setBuddy(field)
    layout.addWidget(label)
    layout.addWidget(field)
    dialog.show()
    qt_app.processEvents()

    assert dialog.property("a10Modernized") is True
    assert dialog.property("a11ThemeMode") == "dark"
    assert dialog.property("a11ContrastMode") == "standard"
    assert field.minimumHeight() >= 34
    dialog.close()
    window.close()


def test_a11_live_interface_preferences_recompose_full_application_stylesheet(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    value = replace(
        window.interface_preferences,
        contrast=ContrastMode.HIGH,
        focus_style=FocusStyle.ENHANCED,
    )
    window.apply_interface_preferences(value, persist=False, announce=False)
    qt_app.processEvents()

    stylesheet = QApplication.instance().styleSheet()
    assert "Roadmap 2 A9.1" in stylesheet
    assert "Roadmap 2 A10" in stylesheet
    assert "Roadmap 2 A11" in stylesheet
    assert "border:2px solid" in stylesheet
    assert window.property("a11ContrastMode") == "high"
    assert window.property("a11FocusMode") == "enhanced"
    window.close()


def test_a11_theme_accessibility_modernizer_remains_presentation_only() -> None:
    source = inspect.getsource(ThemeAccessibilityModernizer)
    forbidden = (
        "run_preflight(",
        "start_generation(",
        "generation_controller.start(",
        "provider.setCurrent",
        "model.setCurrent",
        "voice.setText",
        "language.setCurrent",
        "apply_smart_provider_routing_recommendation(",
        "detect_language(",
        "save_project(",
    )
    for token in forbidden:
        assert token not in source


def test_a11_palette_resolution_stays_semantic_and_light_dark_are_distinct() -> None:
    light = palette_for(is_dark=False)
    dark = palette_for(is_dark=True)
    assert light.canvas != dark.canvas
    assert light.surface != dark.surface
    assert light.text_primary != dark.text_primary
    assert light.primary != dark.primary
    assert contrast_ratio(light.focus_ring, light.surface) >= 3.0
    assert contrast_ratio(dark.focus_ring, dark.surface) >= 3.0
