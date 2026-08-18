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


def test_hotfix9_hotfix6_queue_composition_uses_logical_disclosure_authority() -> None:
    source = inspect.getsource(MainWorkspaceModernizer._sync_queue_disclosure_layout)
    workflow_source = inspect.getsource(MainWorkspaceModernizer.reveal_workflow)
    batch_source = inspect.getsource(MainWorkspaceModernizer.reveal_batch_planning)
    sync_source = inspect.getsource(MainWorkspaceModernizer.sync_queue_disclosure_layout_from_widgets)

    assert "self._workflow_expanded" in source
    assert "self._batch_expanded" in source
    assert "queue.range_host" in source
    assert "self._batch_expanded" in workflow_source
    assert "self._workflow_expanded" in batch_source
    assert "self._workflow_expanded" in sync_source
    assert "self._batch_expanded" in sync_source


def test_hotfix9_hotfix6_stale_range_is_reordered_after_explicit_batch(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)

    # Reproduce the exact H5 failure precondition: a stale Range row survives
    # before Batch. The next explicit Batch reveal must rebuild canonical order.
    queue = window.queue_workspace
    queue.root_layout.insertWidget(1, queue.range_host)
    queue.range_host.setMinimumHeight(42)
    queue.range_host.setMaximumHeight(42)
    queue.range_host.show()
    queue.sync_chrome_height()

    modernizer.reveal_batch_planning(True)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == 1
    assert queue.root_layout.indexOf(queue.range_host) == 2
    assert queue.root_layout.indexOf(queue.command_host) == 3
    assert 0 <= _gap(queue.heading, window.queue_batch_operations) <= 8
    assert 0 <= _gap(window.queue_batch_operations, queue.range_host) <= 8
    assert 0 <= _gap(queue.range_host, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix6_physical_visibility_cannot_reopen_logically_collapsed_rows(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)

    # A Qt polish/parent visibility transition may make a child physically
    # visible. It must not become an A9 disclosure request.
    window.generation_journey.show()
    window.queue_batch_operations.show()
    modernizer.sync_queue_disclosure_layout_from_widgets()
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == -1
    assert queue.root_layout.indexOf(queue.range_host) == -1
    assert queue.root_layout.indexOf(queue.command_host) == 1
    assert 0 <= _gap(queue.heading, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix6_sibling_disclosure_state_preserves_canonical_order(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(True)
    modernizer.reveal_workflow(True)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == 1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == 2
    assert queue.root_layout.indexOf(queue.range_host) == 3
    assert queue.root_layout.indexOf(queue.command_host) == 4

    modernizer.reveal_workflow(False)
    modernizer.reapply_visual_geometry()
    _events(qt_app)
    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == 1
    assert queue.root_layout.indexOf(queue.range_host) == 2
    assert queue.root_layout.indexOf(queue.command_host) == 3
    assert 0 <= _gap(queue.heading, window.queue_batch_operations) <= 8
    window.close()
