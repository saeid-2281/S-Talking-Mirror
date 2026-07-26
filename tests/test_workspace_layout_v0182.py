from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.models.project_source import ProjectSource, SourceType


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path) -> MainWindow:
    app = _app()
    QSettings("S Talking", "S Talking").clear()
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    app.processEvents()
    return window


def _load_repaired_csv(window: MainWindow) -> None:
    csv_path = Path("input.repaired.csv")
    if not csv_path.exists():
        csv_path = Path("sample/input.csv")
    window.csv.setText(str(csv_path.resolve()))
    window.load_csv(update_project=False, source="Test")
    _app().processEvents()


def test_vertical_status_counters_removed_and_metrics_are_complete(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert window.queue_count_labels == {}
    assert not window.findChildren(QLabel, "queueCounter")
    assert window.metrics_strip.maximumHeight() <= 42
    assert {"files", "chars", "pending", "running", "done", "failed", "skipped", "quota", "eta"}.issubset(window.cards)
    window.close()


def test_status_metric_click_filters_queue(tmp_path: Path) -> None:
    window = _window(tmp_path)

    window.cards["failed"].clicked.emit("Failed")

    assert window.queue_filter.currentText() == "Failed"
    assert window.cards["failed"].property("active") is True
    window.close()


def test_provider_panel_readable_widths_sections_and_icon_buttons(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert 270 <= window.left_dock.minimumWidth() <= 300
    assert window.left_dock.maximumWidth() <= 360
    assert {"Provider & Account", "Voice & Model", "Audio Settings", "Pronunciation", "Advanced"}.issubset(window.provider_sections)
    assert window.provider_sections["Provider & Account"].content.isVisible()
    assert window.provider_sections["Voice & Model"].content.isVisible()
    assert not window.provider_sections["Audio Settings"].content.isVisible()
    for widget in [window.api_profile, window.model, window.voice]:
        assert widget.minimumWidth() >= 180
    for button in [
        window.account_manager_button,
        window.test_connection_button,
        window.voice_browser_button,
        window.refresh_models_button,
    ]:
        assert 34 <= button.width() <= 36
        assert button.toolTip()
    window.close()


def test_provider_status_does_not_resize_dock(tmp_path: Path) -> None:
    window = _window(tmp_path)
    before = window.left_dock.sizeHint().width()

    window.set_provider_status("Connected · A very long account status with quota and catalog details")
    _app().processEvents()

    assert window.left_dock.sizeHint().width() == before
    window.close()


def test_toolbar_primary_actions_and_overflow(tmp_path: Path) -> None:
    window = _window(tmp_path)

    visible_texts = {action.iconText() or action.text() for action in window.main_toolbar.actions() if not action.isSeparator()}
    assert {"New", "Open", "Save", "Sources", "Start", "Pause", "Stop", "Preflight", "Voices"}.issubset(visible_texts)
    assert "Open Latest Report" not in visible_texts
    overflow = window.findChild(QToolButton, "toolbarOverflowButton")
    assert overflow is window.toolbar_overflow_button
    overflow_actions = {action.text() for action in window.toolbar_overflow_menu.actions()}
    assert {"Open Latest Report", "Provider accounts", "Pronunciation dictionaries", "Command Palette"}.issubset(overflow_actions)
    window.close()


def test_empty_state_actions_and_activity_collapsed(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert window.empty_state.isVisible()
    assert window.empty_add_source_button.text() == "Add source files"
    assert window.empty_open_project_button.text() == "Open project"
    assert window.empty_recent_projects_button.text() == "Recent projects"
    assert window.activity_tabs.maximumHeight() <= 34
    window.set_activity_expanded(True)
    assert window.activity_tabs.maximumHeight() >= 140
    window.close()


def test_loaded_queue_dominates_workspace_with_repaired_csv(tmp_path: Path) -> None:
    window = _window(tmp_path)
    _load_repaired_csv(window)
    window.setGeometry(0, 0, 1366, 768)
    window.apply_workspace_preset("Compact")
    _app().processEvents()

    assert len(window.generation_controller.jobs) >= 1
    if Path("input.repaired.csv").exists():
        assert len(window.generation_controller.jobs) == 4212
    assert not window.empty_state.isVisible()
    assert window.table.viewport().width() > 900
    assert window.table.viewport().height() > 170
    window.close()


def test_source_reorder_preserves_selection_and_boundaries(tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.project_sources = [
        ProjectSource(source_id="a", project_id=None, display_name="a.csv", source_type=SourceType.CSV, source_path=tmp_path / "a.csv"),
        ProjectSource(source_id="b", project_id=None, display_name="b.csv", source_type=SourceType.CSV, source_path=tmp_path / "b.csv"),
    ]
    window.render_project_sources()

    window.sources_table.selectRow(0)
    assert not window.source_move_up_button.isEnabled()
    assert window.source_move_down_button.isEnabled()
    window.move_selected_source(1)

    assert window.project_sources[1].source_id == "a"
    assert window.selected_source_rows() == [1]
    assert window.source_move_up_button.isEnabled()
    assert not window.source_move_down_button.isEnabled()
    window.close()


def test_combo_popup_widths_and_logo_hash_unchanged(tmp_path: Path) -> None:
    window = _window(tmp_path)

    assert window.api_profile.view().minimumWidth() >= 260
    assert window.model.view().minimumWidth() >= 260
    logo_hash = hashlib.sha256(Path("app/resources/brand/official/S-Logo.svg").read_bytes()).hexdigest()
    assert logo_hash == "ee062816f60038130f7be4fafe58fc0a7378fdc32f967e2b4faf479d40e9e0e9"
    window.close()
