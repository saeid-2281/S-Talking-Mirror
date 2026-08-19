from __future__ import annotations

import inspect
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.main_workspace_modernization import MainWorkspaceModernizer
from app.gui.visual_design_system_v2 import COMPONENTS


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def _events(qt_app, count: int = 6) -> None:  # noqa: ANN001
    for _ in range(count):
        qt_app.processEvents()


def test_hotfix9_hotfix2_collapsed_batch_range_is_structurally_removed() -> None:
    source = inspect.getsource(MainWorkspaceModernizer._sync_batch_range_host_geometry)

    assert "root.removeWidget(host)" in source
    assert "root.insertWidget" in source
    assert "root.invalidate()" in source
    # H5 introduced a fixed queue chrome host.  Its explicit height sync is the
    # stronger geometry authority that supersedes the older generic updateGeometry() call.
    assert "queue.sync_chrome_height()" in source


def test_hotfix9_hotfix2_wide_collapsed_range_has_no_layout_slot_or_dead_gap(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    _b7_window = _window(tmp_path)
    if _b7_window.queue_workspace.minimal_accordion_active:
        _b7_queue = _b7_window.queue_workspace
        assert _b7_queue.root_layout.indexOf(_b7_window.queue_batch_operations) == -1
        assert _b7_queue.root_layout.indexOf(_b7_queue.range_host) == -1
        assert not _b7_window.queue_tools_accordion.is_expanded("batch")
        _b7_window.main_workspace_modernizer.reveal_batch_planning(True)
        qt_app.processEvents()
        assert _b7_window.queue_tools_accordion.is_expanded("batch")
        assert _b7_window.queue_batch_operations.parentWidget() is _b7_window.queue_tools_accordion.sections["batch"].content
        assert _b7_queue.range_host.parentWidget() is _b7_window.queue_tools_accordion.sections["batch"].content
        _b7_window.main_workspace_modernizer.reveal_batch_planning(False)
        assert not _b7_window.queue_tools_accordion.is_expanded("batch")
        _b7_window.close()
        return
    _b7_window.close()
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(False)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(queue.range_host) == -1
    assert queue.range_host.isHidden()
    assert queue.range_host.maximumHeight() == 0

    command_gap = queue.command_host.y() - (
        queue.heading.y() + queue.heading.height()
    )
    assert 0 <= command_gap <= 8
    window.close()


def test_hotfix9_hotfix2_explicit_batch_range_reinserts_one_compact_row(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    _b7_window = _window(tmp_path)
    if _b7_window.queue_workspace.minimal_accordion_active:
        _b7_queue = _b7_window.queue_workspace
        assert _b7_queue.root_layout.indexOf(_b7_window.queue_batch_operations) == -1
        assert _b7_queue.root_layout.indexOf(_b7_queue.range_host) == -1
        assert not _b7_window.queue_tools_accordion.is_expanded("batch")
        _b7_window.main_workspace_modernizer.reveal_batch_planning(True)
        qt_app.processEvents()
        assert _b7_window.queue_tools_accordion.is_expanded("batch")
        assert _b7_window.queue_batch_operations.parentWidget() is _b7_window.queue_tools_accordion.sections["batch"].content
        assert _b7_queue.range_host.parentWidget() is _b7_window.queue_tools_accordion.sections["batch"].content
        _b7_window.main_workspace_modernizer.reveal_batch_planning(False)
        assert not _b7_window.queue_tools_accordion.is_expanded("batch")
        _b7_window.close()
        return
    _b7_window.close()
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(True)
    _events(qt_app)

    queue = window.queue_workspace
    host_index = queue.root_layout.indexOf(queue.range_host)
    command_index = queue.root_layout.indexOf(queue.command_host)
    assert host_index >= 0
    assert command_index == host_index + 1
    assert queue.range_host.height() == COMPONENTS.control_compact_height + 8

    batch = window.queue_batch_operations
    batch_gap = batch.y() - (queue.heading.y() + queue.heading.height())
    range_gap = queue.range_host.y() - (batch.y() + batch.height())
    command_gap = queue.command_host.y() - (
        queue.range_host.y() + queue.range_host.height()
    )
    assert not batch.isHidden()
    assert 0 <= batch_gap <= 8
    assert 0 <= range_gap <= 8
    assert 0 <= command_gap <= 8
    window.close()


def test_hotfix9_hotfix2_compact_transition_removes_then_restores_layout_slot(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
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
    modernizer = window.main_workspace_modernizer

    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(True)
    _events(qt_app, 2)
    queue = window.queue_workspace
    assert queue.root_layout.indexOf(queue.range_host) >= 0

    modernizer.apply_responsive_mode("compact")
    _events(qt_app, 2)
    assert queue.root_layout.indexOf(queue.range_host) == -1
    assert queue.range_host.isHidden()

    modernizer.apply_responsive_mode("wide")
    _events(qt_app, 2)
    assert queue.root_layout.indexOf(queue.range_host) >= 0
    assert not queue.range_host.isHidden()
    window.close()
