from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import QPoint

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.queue_workspace import QueueWorkspace


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


def _top_in_shell(window: MainWindow, widget) -> int:  # noqa: ANN001
    return widget.mapTo(window.application_shell, QPoint(0, 0)).y()


def test_hotfix9_hotfix6_hotfix2_uses_bounded_visible_chrome_height_authority() -> None:
    source = inspect.getsource(QueueWorkspace.chrome_content_height)
    sync_source = inspect.getsource(QueueWorkspace.sync_chrome_height)

    assert "widget.isHidden()" in source
    assert "widget.minimumHeight()" in source
    assert "widget.maximumHeight()" in source
    assert "self.chrome_host.setMinimumHeight(0)" in sync_source
    assert "self.chrome_host.setMaximumHeight(16777215)" in sync_source
    assert "height = self.chrome_content_height()" in sync_source
    assert "self.chrome_host.setFixedHeight(height)" in sync_source


def test_hotfix9_hotfix6_hotfix2_collapsed_chrome_has_no_command_summary_dead_cell(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.count() == 3
    assert queue.root_layout.indexOf(queue.heading) == 0
    assert queue.root_layout.indexOf(queue.command_host) == 1
    assert queue.root_layout.indexOf(queue.summary) == 2
    assert queue.chrome_host.height() == queue.chrome_content_height()
    assert 0 <= _gap(queue.heading, queue.command_host) <= 8
    assert 0 <= _gap(queue.command_host, queue.summary) <= 8

    launch_top = _top_in_shell(window, window.generation_status_strip)
    summary_bottom = _top_in_shell(window, queue.summary) + queue.summary.height()
    assert summary_bottom - launch_top <= 220
    window.close()


def test_hotfix9_hotfix6_hotfix2_expanded_then_collapsed_chrome_shrinks_again(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(True)
    modernizer.reveal_batch_planning(True)
    modernizer.reapply_visual_geometry()
    _events(qt_app)
    expanded_height = window.queue_workspace.chrome_host.height()

    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)
    modernizer.reapply_visual_geometry()
    _events(qt_app)
    queue = window.queue_workspace
    collapsed_height = queue.chrome_host.height()

    assert collapsed_height < expanded_height
    assert collapsed_height == queue.chrome_content_height()
    assert queue.root_layout.count() == 3
    assert 0 <= _gap(queue.command_host, queue.summary) <= 8
    window.close()


def test_hotfix9_hotfix6_hotfix2_repeated_disclosure_cycles_do_not_ratchet_height(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)
    modernizer.reapply_visual_geometry()
    _events(qt_app)
    baseline = window.queue_workspace.chrome_host.height()

    for _ in range(3):
        modernizer.reveal_batch_planning(True)
        modernizer.reveal_workflow(True)
        _events(qt_app, 3)
        modernizer.reveal_workflow(False)
        modernizer.reveal_batch_planning(False)
        modernizer.reapply_visual_geometry()
        _events(qt_app, 3)
        assert window.queue_workspace.chrome_host.height() == baseline
        assert window.queue_workspace.chrome_host.height() == window.queue_workspace.chrome_content_height()

    window.close()
