from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QSizePolicy

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.main_workspace_modernization import MainWorkspaceModernizer
from app.gui.theme_accessibility_v2 import (
    soft_professional_vertical_rhythm_stylesheet,
    theme_accessibility_stylesheet,
)
from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, COMPONENTS, TYPOGRAPHY


ROOT = Path(__file__).resolve().parents[1]


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def _top_in_shell(window: MainWindow, widget) -> int:  # noqa: ANN001
    return widget.mapTo(window.application_shell, QPoint(0, 0)).y()


def test_hotfix9_uses_selected_a8_typography_and_control_contract() -> None:
    style = soft_professional_vertical_rhythm_stylesheet(is_dark=True)

    assert ACTIVE_CONCEPT == "soft_professional"
    assert f"font-size:{TYPOGRAPHY.body}px" in style
    assert f"font-size:{TYPOGRAPHY.caption}px" in style
    assert f"font-size:{TYPOGRAPHY.label}px" in style
    assert f"font-size:{TYPOGRAPHY.section}px" in style
    assert f"font-size:{TYPOGRAPHY.title}px" in style
    assert f"min-height:{COMPONENTS.control_compact_height}px" in style
    assert f"max-height:{COMPONENTS.control_compact_height}px" in style


def test_hotfix9_typography_layer_is_final_for_all_public_themes() -> None:
    for is_dark in (False, True):
        style = theme_accessibility_stylesheet(is_dark=is_dark)
        marker = "Roadmap 2 B6 Hotfix 3 Hotfix 9 — Vertical Rhythm & Typography Unification"
        assert marker in style
        assert style.rfind(marker) > style.rfind("Roadmap 2 B6 Hotfix 3 Hotfix 6")


def test_hotfix9_geometry_removes_duplicate_queue_command_margins() -> None:
    source = inspect.getsource(MainWorkspaceModernizer._apply_soft_professional_geometry)

    assert "command_root_layout, (8, 4, 8, 4), 4" in source
    assert "command_layout, (0, 0, 0, 0), 6" in source
    assert "action_layout, (0, 0, 0, 0), 6" in source
    assert "planning_layout, (0, 0, 0, 0), 6" in source
    assert "_lock_vertical(owner.queue_workspace.command_host" in source


def test_hotfix9_wide_queue_gives_spare_height_to_work_surface(qt_app, tmp_path: Path) -> None:  # noqa: ANN001
    _b7_window = _window(tmp_path)
    if _b7_window.queue_workspace.minimal_accordion_active:
        _b7_queue = _b7_window.queue_workspace
        assert _b7_queue.command_host.isHidden()
        assert _b7_queue.root_layout.indexOf(_b7_queue.command_host) == -1
        assert _b7_queue.body_layout.indexOf(_b7_window.table) >= 0
        assert _b7_queue.body_layout.indexOf(_b7_window.queue_tools_accordion) > _b7_queue.body_layout.indexOf(_b7_window.table)
        assert all(not _b7_window.queue_tools_accordion.is_expanded(key) for key in _b7_window.queue_tools_accordion.sections)
        _b7_window.close()
        return
    _b7_window.close()
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    window.main_workspace_modernizer.reveal_workflow(False)
    window.main_workspace_modernizer.reveal_batch_planning(False)
    window.main_workspace_modernizer.reapply_visual_geometry()
    for _ in range(4):
        qt_app.processEvents()

    assert window.queue_workspace.heading.height() == 46
    assert window.queue_workspace.heading.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert window.queue_workspace.command_host.height() == 80
    assert window.queue_workspace.command_host.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert 30 <= window.queue_workspace.summary.height() <= 32
    assert window.queue_workspace.summary.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed

    shell_gap = _top_in_shell(window, window.queue_workspace) - (
        _top_in_shell(window, window.generation_status_strip)
        + window.generation_status_strip.height()
    )
    assert 0 <= shell_gap <= 8

    command_gap = window.queue_workspace.command_host.y() - (
        window.queue_workspace.heading.y() + window.queue_workspace.heading.height()
    )
    assert 0 <= command_gap <= 8
    summary_gap = window.queue_workspace.summary.y() - (
        window.queue_workspace.command_host.y() + window.queue_workspace.command_host.height()
    )
    assert 0 <= summary_gap <= 8
    assert window.queue_workspace.chrome_host.height() == window.queue_workspace.chrome_content_height()
    assert window.queue_workspace.range_host.isHidden()
    assert window.queue_workspace.range_host.maximumHeight() == 0

    # The collapsed queue chrome consists of a 44px launch band, 46px heading,
    # two 34px command rows and a 30-32px summary plus compact inter-row gaps.
    # A <=220px envelope is attainable only when the fixed chrome host shrinks
    # back to the bounded visible rows after disclosure composition changes.
    summary_bottom = _top_in_shell(window, window.queue_workspace.summary) + window.queue_workspace.summary.height()
    launch_top = _top_in_shell(window, window.generation_status_strip)
    assert summary_bottom - launch_top <= 220
    window.close()


def test_hotfix9_center_controls_share_one_compact_height(qt_app, tmp_path: Path) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    window.main_workspace_modernizer.reapply_visual_geometry()
    qt_app.processEvents()

    controls = [
        window.queue_search,
        window.queue_filter,
        window.source_filter,
        window.scope_selector,
        window.order_selector,
        window.use_sort_button,
        window.use_selection_scope_button,
        window.dry_run_button,
        window.retry_menu_button,
        window.clear_completed_button,
    ]
    assert {control.height() for control in controls} == {COMPONENTS.control_compact_height}
    window.close()


def test_hotfix9_generation_buttons_use_color_not_size_for_hierarchy(qt_app, tmp_path: Path) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.show()
    window.main_workspace_modernizer.reapply_visual_geometry()
    qt_app.processEvents()

    heights = {
        window.generation_status_strip.start_button.height(),
        window.generation_status_strip.preflight_button.height(),
        window.generation_status_strip.pause_button.height(),
        window.generation_status_strip.stop_button.height(),
        window.generation_status_strip.state_badge.height(),
    }
    assert heights == {COMPONENTS.control_compact_height}
    assert window.generation_status_strip.height() == COMPONENTS.generation_action_bar_height
    window.close()


def test_hotfix9_body_control_typography_is_explicitly_unified() -> None:
    style = soft_professional_vertical_rhythm_stylesheet(is_dark=False)

    for selector in (
        "QToolBar#mainToolbar QToolButton",
        "QFrame#generationActionBar QPushButton",
        "QWidget#queueWorkspace QPushButton",
        "QWidget#queueWorkspace QToolButton",
        "QWidget#queueWorkspace QLineEdit",
        "QWidget#queueWorkspace QComboBox",
        "QDockWidget#workspaceLeftDock QPushButton",
        "QDockWidget#workspaceRightDock QPushButton",
    ):
        assert selector in style


def test_hotfix9_is_presentation_only() -> None:
    source = (
        inspect.getsource(MainWorkspaceModernizer._apply_soft_professional_geometry)
        + soft_professional_vertical_rhythm_stylesheet(is_dark=True)
    )
    for forbidden in (
        "run_preflight(",
        "start_generation(",
        "setCurrentText(",
        "activate_failover",
        "api_key_for(",
    ):
        assert forbidden not in source
