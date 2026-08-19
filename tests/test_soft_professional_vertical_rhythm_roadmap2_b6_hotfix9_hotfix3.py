from __future__ import annotations

import inspect
import re
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.main_workspace_modernization import MainWorkspaceModernizer
from app.gui.widgets.generation_journey import GenerationJourneyWidget
from app.gui.widgets.queue_batch_operations import QueueBatchOperationsWidget


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def _events(qt_app, count: int = 8) -> None:  # noqa: ANN001
    for _ in range(count):
        qt_app.processEvents()


def test_hotfix9_hotfix3_overlay_widgets_keep_presentation_visibility_state() -> None:
    journey_source = inspect.getsource(GenerationJourneyWidget.set_compact_mode)
    batch_source = inspect.getsource(QueueBatchOperationsWidget.set_compact_mode)
    modernizer_source = inspect.getsource(MainWorkspaceModernizer._set_visible)

    assert "_presentation_visible" in journey_source
    assert "_presentation_visible" in batch_source
    assert "set_presentation_visible" in modernizer_source
    top_level_reopen = re.compile(r"^\s*self\.setVisible\(not self\._compact\)", re.MULTILINE)
    assert top_level_reopen.search(journey_source) is None
    assert top_level_reopen.search(batch_source) is None


def test_hotfix9_hotfix3_delayed_noncompact_sync_cannot_reopen_collapsed_disclosures(
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

    # Reproduce the resize/overlay callback that previously called
    # set_compact_mode(False) after A9 had already collapsed both surfaces.
    window._workspace_preset_compact = False
    window._responsive_overlay_compact = False
    window._sync_workspace_overlay_compact()
    _events(qt_app)

    queue = window.queue_workspace
    assert window.generation_journey.isHidden()
    assert window.queue_batch_operations.isHidden()
    assert queue.root_layout.indexOf(queue.range_host) == -1

    gap = queue.command_host.y() - (queue.heading.y() + queue.heading.height())
    assert 0 <= gap <= 8
    window.close()


def test_hotfix9_hotfix3_explicit_batch_plan_keeps_only_batch_and_range_rows(
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

    window._workspace_preset_compact = False
    window._responsive_overlay_compact = False
    window._sync_workspace_overlay_compact()
    _events(qt_app)

    queue = window.queue_workspace
    batch = window.queue_batch_operations
    assert window.generation_journey.isHidden()
    assert not batch.isHidden()
    assert not queue.range_host.isHidden()

    batch_gap = batch.y() - (queue.heading.y() + queue.heading.height())
    range_gap = queue.range_host.y() - (batch.y() + batch.height())
    command_gap = queue.command_host.y() - (
        queue.range_host.y() + queue.range_host.height()
    )
    assert 0 <= batch_gap <= 8
    assert 0 <= range_gap <= 8
    assert 0 <= command_gap <= 8
    window.close()


def test_hotfix9_hotfix3_explicit_workflow_does_not_reopen_batch_plan(
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

    window._workspace_preset_compact = False
    window._responsive_overlay_compact = False
    window._sync_workspace_overlay_compact()
    _events(qt_app)

    assert not window.generation_journey.isHidden()
    assert window.queue_batch_operations.isHidden()
    assert window.queue_workspace.root_layout.indexOf(window.queue_workspace.range_host) == -1
    window.close()
