from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_workspace_layout_presets_exist_and_toggle_panels(tmp_path: Path) -> None:
    app = _app()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    app.processEvents()

    assert {"Compact", "Standard", "Wide", "Focus Mode"}.issubset(window.layout_actions)
    window.apply_workspace_preset("Focus Mode", save=True)

    assert window.provider_panel.isVisible() is False
    assert window.selected_row_panel.isVisible() is False
    assert window.monitor_dock.isVisible() is False

    window.apply_workspace_preset("Wide", save=True)

    assert window.provider_panel.isVisible() is True
    assert window.selected_row_panel.isVisible() is True
    assert window.monitor_dock.isVisible() is True
    window.close()


def test_project_menu_is_sectioned_with_core_shortcuts(tmp_path: Path) -> None:
    _app()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))

    assert any(action.isSeparator() for action in window.project_menu.actions())
    assert window.actions_by_name["New Project"].shortcut().toString() == "Ctrl+N"
    assert window.actions_by_name["Open Project"].shortcut().toString() == "Ctrl+O"
    assert window.actions_by_name["Restore Default Layout"].text() == "Restore Default Layout"
    window.close()


def test_legacy_layout_state_is_ignored_for_v018(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    _app()
    settings = QSettings("S Talking", "S Talking")
    settings.clear()
    settings.setValue("main_window/layout_version", "v017")
    settings.setValue("main_window/layout_preset", "Focus Mode")

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))

    assert window.layout_actions["Standard"].isChecked()
    assert window.provider_panel.isVisibleTo(window)
    window.close()
    settings.clear()
