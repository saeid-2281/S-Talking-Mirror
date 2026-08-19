from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QAbstractItemView

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.interface_preferences_dialog import InterfacePreferencesDialog
from app.gui.interface_preferences import (
    ContrastMode,
    FocusStyle,
    InterfacePreferences,
    normalize_contrast,
    normalize_focus_style,
    normalize_text_scale,
)
from app.gui.main import MainWindow


class MemorySettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.synced = False

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.synced = True


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase24_interface_preferences_normalize_and_summarize() -> None:
    assert normalize_contrast("HIGH") is ContrastMode.HIGH
    assert normalize_contrast("unexpected") is ContrastMode.STANDARD
    assert normalize_focus_style("enhanced") is FocusStyle.ENHANCED
    assert normalize_text_scale("113%") == 110
    assert normalize_text_scale("bad") == 100

    summary = InterfacePreferences(
        contrast=ContrastMode.HIGH,
        text_scale=125,
        focus_style=FocusStyle.ENHANCED,
        reduce_motion=True,
        announce_status=False,
    ).summary()
    assert "High contrast" in summary
    assert "Text 125%" in summary
    assert "Enhanced focus" in summary
    assert "Status announcements off" in summary


def test_phase24_interface_preferences_round_trip_without_qt_window() -> None:
    settings = MemorySettings()
    expected = InterfacePreferences(
        contrast=ContrastMode.HIGH,
        text_scale=110,
        focus_style=FocusStyle.ENHANCED,
        reduce_motion=True,
        announce_status=False,
    )

    expected.save(settings)
    restored = InterfacePreferences.from_settings(settings)

    assert restored == expected
    assert settings.synced is True
    assert restored.stylesheet_properties() == {
        "contrastMode": "high",
        "textScale": "110",
        "focusMode": "enhanced",
        "reduceMotion": "true",
    }


def test_phase24_interface_preferences_dialog_edits_value_object(qt_app) -> None:
    initial = InterfacePreferences(
        contrast=ContrastMode.HIGH,
        text_scale=125,
        focus_style=FocusStyle.ENHANCED,
        reduce_motion=True,
        announce_status=False,
    )
    dialog = InterfacePreferencesDialog(initial)
    dialog.show()
    qt_app.processEvents()

    assert dialog.windowTitle() == "Interface & Accessibility"
    assert dialog.contrast_combo.currentData() == "high"
    assert dialog.text_scale_combo.currentData() == 125
    assert dialog.focus_combo.currentData() == "enhanced"
    assert dialog.reduce_motion_checkbox.isChecked() is True
    assert dialog.announce_status_checkbox.isChecked() is False
    assert dialog.preferences() == initial

    dialog.restore_defaults()
    assert dialog.preferences() == InterfacePreferences.defaults()
    dialog.close()


def test_phase24_main_applies_and_persists_accessibility_properties(qt_app, tmp_path: Path) -> None:
    settings = QSettings("S Talking", "S Talking")
    for key in (
        "interface/contrast",
        "interface/text_scale",
        "interface/focus_style",
        "interface/reduce_motion",
        "interface/announce_status",
    ):
        settings.remove(key)

    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()
    value = InterfacePreferences(
        contrast=ContrastMode.HIGH,
        text_scale=110,
        focus_style=FocusStyle.ENHANCED,
        reduce_motion=True,
        announce_status=True,
    )

    window.apply_interface_preferences(value, persist=True)
    qt_app.processEvents()

    assert window.property("contrastMode") == "high"
    assert window.property("textScale") == "110"
    assert window.property("focusMode") == "enhanced"
    assert window.property("reduceMotion") == "true"
    assert window.table.verticalScrollMode() == QAbstractItemView.ScrollPerItem
    assert window.high_contrast_action.isChecked() is True
    assert window.enhanced_focus_action.isChecked() is True
    assert int(settings.value("interface/text_scale")) == 110
    window.close()
    for key in (
        "interface/contrast",
        "interface/text_scale",
        "interface/focus_style",
        "interface/reduce_motion",
        "interface/announce_status",
    ):
        settings.remove(key)


def test_phase24_keyboard_navigation_actions_focus_major_regions(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert window.actions_by_name["Interface settings"].shortcut().toString() == "Ctrl+Alt+I"
    assert window.actions_by_name["Focus provider panel"].shortcut().toString() == "Ctrl+1"
    assert window.actions_by_name["Focus generation queue"].shortcut().toString() == "Ctrl+2"
    assert window.actions_by_name["Focus generation controls"].shortcut().toString() == "Ctrl+5"

    assert window.focus_workspace_region("queue") is True
    qt_app.processEvents()
    assert window.queue_search.hasFocus()

    assert window.focus_workspace_region("generation") is True
    qt_app.processEvents()
    if window.queue_workspace.minimal_accordion_active:
        assert window.startb.isHidden()
        assert window.dry_run_button.isHidden()
        assert window.metrics_strip.action_buttons["Start Generation"].hasFocus()
    else:
        assert window.startb.isEnabled() is False
        assert window.dry_run_button.hasFocus()
    window.close()


def test_phase24_generation_state_updates_accessible_announcer(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.apply_interface_preferences(InterfacePreferences.defaults(), announce=False)
    window.generation_status_strip.set_generation_state("Running", "Two jobs queued")
    qt_app.processEvents()

    assert window.accessibility_announcer.objectName() == "accessibilityAnnouncer"
    assert "Running" in window.accessibility_announcer.accessibleDescription()
    assert "Two jobs queued" in window.accessibility_announcer.accessibleDescription()
    window.close()


def test_phase24_theme_contains_accessibility_and_dialog_contract() -> None:
    source = Path("app/gui/theme.py").read_text(encoding="utf-8")

    for selector in (
        "QFrame#professionalDialogHeader",
        "QFrame#interfacePreviewCard",
        'QMainWindow[contrastMode="high"]',
        'QMainWindow[focusMode="enhanced"]',
        'QMainWindow[textScale="125"]',
        "QLabel#accessibilityAnnouncer",
    ):
        assert selector in source
