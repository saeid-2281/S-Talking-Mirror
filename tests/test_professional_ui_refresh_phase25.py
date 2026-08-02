from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QFrame, QGridLayout, QPushButton, QWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme import ThemeManager


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase25_theme_manager_exposes_coherent_palette() -> None:
    manager = ThemeManager()
    dark_tokens = manager.tokens("Dark")
    light_tokens = manager.tokens("Light")
    dark_palette = manager.palette("Dark")
    light_palette = manager.palette("Light")

    assert dark_palette.color(QPalette.Window).name().lower() == dark_tokens["app"].lower()
    assert dark_palette.color(QPalette.Midlight).name().lower() == dark_tokens["border_subtle"].lower()
    assert light_palette.color(QPalette.Window).name().lower() == light_tokens["app"].lower()
    assert light_palette.color(QPalette.Mid).name().lower() == light_tokens["text_secondary"].lower()


def test_phase25_main_window_applies_palette_when_theme_changes(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.apply_theme("Dark")
    assert QWidget.palette(window).color(QPalette.Window).name().lower() == window.theme_manager.tokens("Dark")["app"].lower()

    window.apply_theme("Light")
    assert QWidget.palette(window).color(QPalette.Window).name().lower() == window.theme_manager.tokens("Light")["app"].lower()


def test_phase25_sources_workspace_uses_multiline_action_grid(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    action_card = window.left_tabs.findChild(QFrame, "sourcesActionBar")
    assert action_card is not None
    assert isinstance(action_card.layout(), QGridLayout)
    assert action_card.layout().columnCount() == 3
    assert action_card.layout().rowCount() >= 3

    buttons = action_card.findChildren(QPushButton, "sourcesActionButton")
    labels = {button.text() for button in buttons}
    assert {
        "Add files",
        "Add text",
        "Refresh",
        "Replace",
        "Remove",
        "Open folder",
        "Move up",
        "Move down",
        "View report",
    }.issubset(labels)
    assert all(button.minimumHeight() >= 34 for button in buttons)


def test_phase25_sources_table_uses_professional_object_name(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert window.sources_table.objectName() == "sourcesTable"
    assert window.sources_table.alternatingRowColors() is True
    assert window.sources_table.showGrid() is False
