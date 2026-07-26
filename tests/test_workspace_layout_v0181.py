from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QGroupBox, QTabWidget, QToolBar

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path) -> MainWindow:
    app = _app()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    app.processEvents()
    return window


def test_main_toolbar_uses_shared_menu_actions(tmp_path: Path) -> None:
    window = _window(tmp_path)

    toolbar = window.findChild(QToolBar, "mainToolbar")
    assert toolbar is window.main_toolbar
    assert 38 <= toolbar.maximumHeight() <= 42
    assert window.actions_by_name["New Project"] in toolbar.actions()
    assert window.actions_by_name["Open Project"] in toolbar.actions()
    assert window.actions_by_name["Save"] in toolbar.actions()
    assert window.actions_by_name["Start Generation"] in toolbar.actions()
    assert window.actions_by_name["Run Preflight"] in toolbar.actions()
    assert all(not action.icon().isNull() for action in toolbar.actions() if not action.isSeparator())
    window.close()


def test_compact_project_and_metric_strips_replace_tall_cards(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert window.project_context_frame.maximumHeight() <= 52
    assert window.metrics_strip.maximumHeight() <= 54
    assert {"files", "chars", "pending", "running", "done", "failed", "skipped", "quota", "eta"}.issubset(window.cards)
    visible_sources_groups = [box for box in window.findChildren(QGroupBox) if box.title() == "Project sources" and box.isVisible()]
    assert visible_sources_groups == []
    assert window.source_summary.sizePolicy().horizontalPolicy().name in {"Ignored", "Expanding"}
    assert window.output_summary.sizePolicy().horizontalPolicy().name in {"Ignored", "Expanding"}
    window.close()


def test_left_and_right_workspaces_are_docked_tabs(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert isinstance(window.left_dock, QDockWidget)
    assert isinstance(window.right_dock, QDockWidget)
    assert isinstance(window.left_tabs, QTabWidget)
    assert isinstance(window.right_tabs, QTabWidget)
    assert [window.left_tabs.tabText(i) for i in range(window.left_tabs.count())] == ["Provider", "Sources"]
    assert [window.right_tabs.tabText(i) for i in range(window.right_tabs.count())] == ["Selected Row", "Generation Monitor"]
    assert window.sources_dock is window.left_dock
    assert window.monitor_dock is window.right_dock
    window.close()


def test_activity_area_is_collapsible_tabbed_output(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert isinstance(window.activity_tabs, QTabWidget)
    assert window.activity_tabs.maximumHeight() <= 176
    assert [window.activity_tabs.tabText(i) for i in range(window.activity_tabs.count())] == ["Activity", "Output", "Errors"]
    assert window.generation_action_bar.maximumHeight() <= 44
    window.close()


def test_provider_controls_have_practical_minimum_widths(tmp_path: Path) -> None:
    window = _window(tmp_path)

    for widget in [window.provider, window.api_profile, window.model, window.language, window.voice]:
        assert widget.minimumWidth() >= 180
    window.close()


def test_workspace_presets_change_dock_geometry_and_activity(tmp_path: Path) -> None:
    window = _window(tmp_path)

    window.apply_workspace_preset("Focus Mode")
    assert not window.left_dock.isVisible()
    assert not window.right_dock.isVisible()
    focus_activity_height = window.activity_tabs.maximumHeight()

    window.apply_workspace_preset("Wide")
    assert window.left_dock.isVisible()
    assert window.right_dock.isVisible()
    assert window.right_tabs.currentIndex() == 1
    assert window.activity_tabs.maximumHeight() > focus_activity_height

    window.apply_workspace_preset("Compact")
    assert not window.left_dock.isVisible()
    assert not window.right_dock.isVisible()
    assert window.activity_tabs.maximumHeight() < 176
    window.close()


def test_project_menu_has_sections_and_submenus(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert any(action.isSeparator() for action in window.project_menu.actions())
    assert window.project_menu.findChild(type(window.project_menu), "Import") is None
    submenu_titles = {action.menu().title() for action in window.project_menu.actions() if action.menu()}
    assert {"Import", "Export"}.issubset(submenu_titles)
    assert window.main_toolbar.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    window.close()
