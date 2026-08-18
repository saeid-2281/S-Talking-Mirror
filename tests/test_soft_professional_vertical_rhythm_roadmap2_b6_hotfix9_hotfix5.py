from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtWidgets import QSizePolicy

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


def test_hotfix9_hotfix5_queue_chrome_isolated_from_expanding_body() -> None:
    source = inspect.getsource(QueueWorkspace.__init__)
    assert "self.chrome_host = QWidget(self)" in source
    assert "self.chrome_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)" in source
    assert "self.root_layout = QVBoxLayout(self.chrome_host)" in source
    assert "self.body_host = QWidget(self)" in source
    assert "self.body_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)" in source
    assert "self.body_layout = QVBoxLayout(self.body_host)" in source
    assert "self.shell_layout.addWidget(self.body_host, 1)" in source


def test_hotfix9_hotfix5_collapsed_queue_has_no_surplus_chrome_cells(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)
    window._workspace_preset_compact = False
    window._responsive_overlay_compact = False
    window._sync_workspace_overlay_compact()
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.chrome_host.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert queue.chrome_host.height() == queue.chrome_content_height()
    assert queue.root_layout.indexOf(window.generation_journey) == -1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == -1
    assert queue.root_layout.indexOf(queue.range_host) == -1
    assert queue.root_layout.indexOf(queue.command_host) == 1
    assert 0 <= _gap(queue.heading, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix5_batch_composition_remains_contiguous_inside_fixed_chrome(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(True)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.queue_batch_operations) == 1
    assert queue.root_layout.indexOf(queue.range_host) == 2
    assert queue.root_layout.indexOf(queue.command_host) == 3
    assert queue.chrome_host.height() == queue.chrome_content_height()
    assert 0 <= _gap(queue.heading, window.queue_batch_operations) <= 8
    assert 0 <= _gap(window.queue_batch_operations, queue.range_host) <= 8
    assert 0 <= _gap(queue.range_host, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix5_workflow_composition_remains_contiguous_inside_fixed_chrome(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(False)
    modernizer.reveal_workflow(True)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.generation_journey) == 1
    assert queue.root_layout.indexOf(queue.command_host) == 2
    assert queue.chrome_host.height() == queue.chrome_content_height()
    assert 0 <= _gap(queue.heading, window.generation_journey) <= 8
    assert 0 <= _gap(window.generation_journey, queue.command_host) <= 8
    window.close()


def test_hotfix9_hotfix5_body_receives_extra_height_not_queue_chrome(
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
    chrome_before = queue.chrome_host.height()
    body_before = window.table.height()
    window.resize(2048, 1320)
    _events(qt_app)
    modernizer.reapply_visual_geometry()
    _events(qt_app)
    assert queue.chrome_host.height() == chrome_before
    assert window.table.height() >= body_before
    window.close()
