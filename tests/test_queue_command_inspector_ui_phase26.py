from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QTabWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase26_queue_command_center_uses_two_readable_rows(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    workspace = window.queue_workspace

    # The responsive coordinator is intentionally debounced. Pin the
    # presentation under test instead of depending on event-loop timing. B7
    # replaces the legacy two/three-row command band with a hidden compatibility
    # host plus the one-open queue accordion; pre-B7 builds retain the row test.
    workspace.set_responsive_mode("standard", force=True)
    if workspace.minimal_accordion_active:
        assert workspace.command_host.isHidden()
        assert workspace.command_host.maximumHeight() == 0
        assert workspace.queue_accordion is not None
        assert set(workspace.queue_accordion.sections) == {
            "queue-actions", "filters", "batch", "workflow", "columns"
        }
        workspace.set_responsive_mode("compact", force=True)
        assert all(
            not workspace.queue_accordion.is_expanded(key)
            for key in workspace.queue_accordion.sections
        )
        workspace.set_responsive_mode("standard", force=True)
        assert workspace.command_host.isHidden()
    else:
        assert workspace.command_root_layout.count() == 2
        assert workspace.command_layout.count() >= 7
        assert workspace.action_layout.count() >= 8
        workspace.set_responsive_mode("compact", force=True)
        assert workspace.command_root_layout.count() == 3
        assert workspace.command_root_layout.indexOf(workspace.planning_host) == 1
        workspace.set_responsive_mode("standard", force=True)
        assert workspace.command_root_layout.count() == 2
    assert window.queue_search.minimumWidth() >= 220
    assert window.dry_run_button.objectName() == "queuePrimaryAction"
    assert window.retry_menu_button.objectName() == "queueActionMenu"


def test_phase26_queue_inspector_uses_cards_and_action_grid(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    header = window.selected_row_panel.findChild(QFrame, "queueInspectorHeader")
    actions = window.selected_row_panel.findChild(QFrame, "queueInspectorActions")
    assert header is not None
    assert actions is not None
    assert isinstance(actions.layout(), QGridLayout)
    assert actions.layout().columnCount() == 2
    assert window.pstatus.objectName() == "queueInspectorStatus"
    assert window.pmeta.wordWrap() is True
    assert window.ptext.minimumHeight() >= 180


def test_phase26_inspector_actions_remain_visible_in_narrow_dock(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    window.resizeDocks([window.right_dock], [290], Qt.Horizontal)
    qt_app.processEvents()

    for button in (
        window.play_output_button,
        window.open_selected_button,
        window.copy_output_button,
        window.stop_playback_button,
    ):
        assert button.minimumWidth() == 0
        assert button.minimumHeight() >= 34
        assert button.isVisible() is True


def test_phase26_generation_monitor_uses_tabbed_metrics_and_cards(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert isinstance(window.monitor_sections, QTabWidget)
    assert window.monitor_sections.count() == 4
    assert [window.monitor_sections.tabText(i) for i in range(4)] == [
        "Current job",
        "Queue",
        "Performance",
        "Timing",
    ]
    assert window.monitor_status.objectName() == "monitorStatusBadge"
    assert window.monitor_output.wordWrap() is True
    assert window.monitor_progress.objectName() == "monitorProgress"


def test_phase26_monitor_and_inspector_status_use_semantic_properties(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.monitor_status.setProperty("tone", "running")
    window.monitor_status.style().unpolish(window.monitor_status)
    window.monitor_status.style().polish(window.monitor_status)
    window.pstatus.setProperty("tone", "completed")
    window.pstatus.style().unpolish(window.pstatus)
    window.pstatus.style().polish(window.pstatus)

    assert window.monitor_status.property("tone") == "running"
    assert window.pstatus.property("tone") == "completed"
