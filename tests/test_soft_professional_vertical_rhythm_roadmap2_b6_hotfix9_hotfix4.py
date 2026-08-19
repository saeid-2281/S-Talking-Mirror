from __future__ import annotations

import inspect
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.main_workspace_modernization import MainWorkspaceModernizer


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def _events(qt_app, count: int = 8) -> None:  # noqa: ANN001
    for _ in range(count):
        qt_app.processEvents()


def _gap(upper, lower) -> int:  # noqa: ANN001
    return lower.y() - (upper.y() + upper.height())


def test_hotfix9_hotfix4_optional_disclosures_use_structural_membership() -> None:
    source = inspect.getsource(MainWorkspaceModernizer._sync_queue_disclosure_layout)
    assert "root.removeWidget(widget)" in source
    assert "root.insertWidget" in source
    assert "root.activate()" in source
    assert "_sync_batch_range_host_geometry" in source


def test_hotfix9_hotfix4_collapsed_wide_queue_is_physically_contiguous(
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
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)

    # Exercise the delayed MainWindow overlay resync that exposed H9 H1-H3.
    window._workspace_preset_compact = False
    window._responsive_overlay_compact = False
    window._sync_workspace_overlay_compact()
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == -1
    assert queue.root_layout.indexOf(queue.range_host) == -1
    assert queue.root_layout.indexOf(queue.command_host) == 1
    assert 0 <= _gap(queue.heading, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix4_explicit_batch_plan_is_one_contiguous_structural_block(
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
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(True)
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == 1
    assert queue.root_layout.indexOf(queue.range_host) == 2
    assert queue.root_layout.indexOf(queue.command_host) == 3
    assert 0 <= _gap(queue.heading, window.queue_batch_operations) <= 8
    assert 0 <= _gap(window.queue_batch_operations, queue.range_host) <= 8
    assert 0 <= _gap(queue.range_host, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix4_explicit_workflow_is_contiguous_and_batch_stays_detached(
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
    modernizer.reveal_workflow(True)
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == 1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == -1
    assert queue.root_layout.indexOf(queue.range_host) == -1
    assert queue.root_layout.indexOf(queue.command_host) == 2
    assert 0 <= _gap(queue.heading, window.generation_journey) <= 8
    assert 0 <= _gap(window.generation_journey, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix4_compact_focus_still_surfaces_historical_actions(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    _b7_window = _window(tmp_path)
    if _b7_window.queue_workspace.minimal_accordion_active:
        _b7_window.main_workspace_modernizer.apply_responsive_mode("compact")
        assert all(not _b7_window.queue_tools_accordion.is_expanded(key) for key in _b7_window.queue_tools_accordion.sections)
        _b7_window.focus_generation_workflow()
        qt_app.processEvents()
        assert _b7_window.queue_tools_accordion.is_expanded("workflow")
        _b7_window.focus_queue_batch_operations()
        qt_app.processEvents()
        assert _b7_window.queue_tools_accordion.is_expanded("batch")
        assert not _b7_window.queue_tools_accordion.is_expanded("workflow")
        _b7_window.close()
        return
    _b7_window.close()
    window = _window(tmp_path)
    window.resize(1366, 768)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("compact")
    _events(qt_app, 2)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == -1

    window.focus_generation_workflow()
    _events(qt_app, 2)
    assert queue.root_layout.indexOf(window.generation_journey) == 1
    assert not window.generation_journey.isHidden()

    modernizer.reveal_workflow(False)
    window.focus_queue_batch_operations()
    _events(qt_app, 2)
    assert queue.root_layout.indexOf(window.queue_batch_operations) == 1
    assert not window.queue_batch_operations.isHidden()
    window.close()
