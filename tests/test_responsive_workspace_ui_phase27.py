from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.responsive_workspace import (
    ResponsiveWorkspaceCoordinator,
    WorkspaceBreakpoint,
    resolve_workspace_state,
)


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase27_responsive_state_uses_window_and_queue_width() -> None:
    compact = resolve_workspace_state(window_width=1600, window_height=900, queue_width=500)
    narrow = resolve_workspace_state(window_width=1024, window_height=720, queue_width=500)
    standard = resolve_workspace_state(window_width=1366, window_height=768, queue_width=760)
    wide = resolve_workspace_state(window_width=1920, window_height=1080, queue_width=1100)

    assert compact.mode is WorkspaceBreakpoint.COMPACT
    assert compact.source_action_columns == 2
    assert compact.toolbar_icon_only is False
    assert narrow.toolbar_icon_only is True
    assert standard.mode is WorkspaceBreakpoint.STANDARD
    assert standard.right_dock_width == 310
    assert wide.mode is WorkspaceBreakpoint.WIDE
    assert wide.source_action_columns == 3


def test_phase27_coordinator_ignores_pixel_changes_inside_same_breakpoint() -> None:
    first = resolve_workspace_state(window_width=1366, window_height=768, queue_width=760)
    second = resolve_workspace_state(window_width=1420, window_height=800, queue_width=820)
    compact = resolve_workspace_state(window_width=1024, window_height=720, queue_width=500)

    assert ResponsiveWorkspaceCoordinator._presentation_signature(first) == (
        ResponsiveWorkspaceCoordinator._presentation_signature(second)
    )
    assert ResponsiveWorkspaceCoordinator._presentation_signature(first) != (
        ResponsiveWorkspaceCoordinator._presentation_signature(compact)
    )


def test_phase27_compact_queue_reflow_keeps_primary_controls_visible(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.responsive_workspace._timer.stop()
    state = resolve_workspace_state(window_width=1024, window_height=720, queue_width=500)
    window.apply_responsive_workspace(state)

    assert window.queue_workspace.property("responsiveMode") == "compact"
    if window.queue_workspace.minimal_accordion_active:
        accordion = window.queue_tools_accordion
        assert all(not accordion.is_expanded(key) for key in accordion.sections)
        accordion.set_expanded("filters", True)
        qt_app.processEvents()
        assert window.queue_search.isVisible() is True
        assert window.queue_filter.isVisible() is True
        assert window.source_filter.isVisible() is True
        accordion.set_expanded("batch", True)
        qt_app.processEvents()
        assert window.scope_selector.isVisible() is True
        assert window.order_selector.isVisible() is True
        accordion.set_expanded("queue-actions", True)
        qt_app.processEvents()
        assert window.dry_run_button.isHidden()
        assert window.retry_menu_button.isVisible() is True
        assert window.queue_more_actions_button.isVisible() is True
        assert window.use_selection_scope_button.isVisible() is False
        assert window.skip_menu_button.isVisible() is False
    else:
        assert window.queue_search.isVisible() is True
        assert window.queue_filter.isVisible() is True
        assert window.source_filter.isVisible() is True
        assert window.scope_selector.isVisible() is True
        assert window.order_selector.isVisible() is True
        assert window.dry_run_button.isVisible() is True
        assert window.retry_menu_button.isVisible() is True
        assert window.queue_more_actions_button.isVisible() is True
        assert window.use_selection_scope_button.isVisible() is False
        assert window.skip_menu_button.isVisible() is False
    assert window.main_toolbar.toolButtonStyle() == Qt.ToolButtonIconOnly


def test_phase27_wide_queue_reflow_restores_full_operator_actions(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.responsive_workspace._timer.stop()
    compact = resolve_workspace_state(window_width=1024, window_height=720, queue_width=500)
    wide = resolve_workspace_state(window_width=1920, window_height=1080, queue_width=1120)
    window.apply_responsive_workspace(compact)
    window.apply_responsive_workspace(wide)

    assert window.queue_workspace.property("responsiveMode") == "wide"
    if window.queue_workspace.minimal_accordion_active:
        window.queue_tools_accordion.set_expanded("queue-actions", True)
        qt_app.processEvents()
    assert window.use_selection_scope_button.isVisible() is True
    assert window.skip_menu_button.isVisible() is True
    assert window.reset_menu_button.isVisible() is True
    assert window.clear_completed_button.isVisible() is True
    assert window.output_menu_button.isVisible() is True
    assert window.queue_more_actions_button.isVisible() is False
    assert window.main_toolbar.toolButtonStyle() == Qt.ToolButtonTextBesideIcon


def test_phase27_compact_source_actions_reflow_to_two_columns(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.reflow_source_actions(2)

    assert window.sources_action_card.property("columns") == "2"
    assert window.sources_action_layout.itemAtPosition(0, 0).widget().text() == "Add files"
    assert window.sources_action_layout.itemAtPosition(0, 1).widget().text() == "Add text"
    assert window.sources_action_layout.itemAtPosition(1, 0).widget().text() == "Refresh"
    assert window.sources_action_layout.itemAtPosition(4, 0).widget().text() == "View report"


def test_phase27_inspector_and_metrics_adapt_without_losing_controls(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.responsive_workspace._timer.stop()
    compact = resolve_workspace_state(window_width=1024, window_height=720, queue_width=500)
    window.apply_responsive_workspace(compact)

    assert window.queue_details.ptext.minimumHeight() >= 180
    assert window.queue_details.copy_output_button.text() == "Copy"
    assert window.queue_details.stop_playback_button.text() == "Stop"
    assert window.cards["chars"].isVisible() is False
    assert window.cards["skipped"].isVisible() is False
    assert window.cards["files"].isVisible() is True


def test_phase27_preflight_label_preserves_full_status_across_breakpoints(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    full_text = "Preflight: Ready · 0 errors · 2 warnings"
    window.generation_status_strip.set_preflight_text(full_text)

    window.generation_status_strip.set_responsive_mode(WorkspaceBreakpoint.COMPACT)
    assert window.preflight_status.text() == "Preflight"
    assert window.preflight_status.toolTip() == full_text

    window.generation_status_strip.set_responsive_mode(WorkspaceBreakpoint.WIDE)
    assert window.preflight_status.text() == full_text
