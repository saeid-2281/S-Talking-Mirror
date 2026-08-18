from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import QPoint
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


def _events(qt_app, count: int = 6) -> None:  # noqa: ANN001
    for _ in range(count):
        qt_app.processEvents()


def _top_in_shell(window: MainWindow, widget) -> int:  # noqa: ANN001
    return widget.mapTo(window.application_shell, QPoint(0, 0)).y()


def test_hotfix9_hotfix6_hotfix3_shell_uses_real_expanding_body_host() -> None:
    source = inspect.getsource(QueueWorkspace.__init__)

    assert 'self.body_host = QWidget(self)' in source
    assert 'self.body_host.setObjectName("queueBodyHost")' in source
    assert 'QSizePolicy.Expanding, QSizePolicy.Expanding' in source
    assert 'self.shell_layout.addWidget(self.body_host, 1)' in source
    assert 'self.shell_layout.addLayout(self.body_layout, 1)' not in source
    assert 'self.shell_layout.setAlignment(self.chrome_host, Qt.AlignTop)' in source


def test_hotfix9_hotfix6_hotfix3_collapsed_chrome_starts_at_queue_top(
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
    assert 0 <= queue.chrome_host.y() <= 2
    assert 0 <= queue.heading.y() <= 2
    assert queue.chrome_host.height() == queue.chrome_content_height()
    assert queue.body_host.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
    body_gap = queue.body_host.y() - (queue.chrome_host.y() + queue.chrome_host.height())
    assert 0 <= body_gap <= 8

    launch_top = _top_in_shell(window, window.generation_status_strip)
    summary_bottom = _top_in_shell(window, queue.summary) + queue.summary.height()
    assert summary_bottom - launch_top <= 220
    window.close()


def test_hotfix9_hotfix6_hotfix3_tall_window_donates_growth_only_to_body(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 900)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_workflow(False)
    modernizer.reveal_batch_planning(False)
    modernizer.reapply_visual_geometry()
    _events(qt_app)

    queue = window.queue_workspace
    chrome_before = queue.chrome_host.height()
    body_before = queue.body_host.height()
    window.resize(2048, 1140)
    _events(qt_app)

    assert queue.chrome_host.height() == chrome_before
    assert queue.chrome_host.y() <= 2
    assert queue.body_host.height() >= body_before + 180
    body_gap = queue.body_host.y() - (queue.chrome_host.y() + queue.chrome_host.height())
    assert 0 <= body_gap <= 8
    window.close()


def test_hotfix9_hotfix6_hotfix3_disclosure_round_trip_cannot_move_chrome_down(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")

    for _ in range(2):
        modernizer.reveal_workflow(True)
        modernizer.reveal_batch_planning(True)
        _events(qt_app, 2)
        modernizer.reveal_workflow(False)
        modernizer.reveal_batch_planning(False)
        modernizer.reapply_visual_geometry()
        _events(qt_app, 2)

    queue = window.queue_workspace
    assert queue.root_layout.count() == 3
    assert queue.root_layout.indexOf(queue.heading) == 0
    assert queue.root_layout.indexOf(queue.command_host) == 1
    assert queue.root_layout.indexOf(queue.summary) == 2
    assert 0 <= queue.chrome_host.y() <= 2
    body_gap = queue.body_host.y() - (queue.chrome_host.y() + queue.chrome_host.height())
    assert 0 <= body_gap <= 8

    launch_top = _top_in_shell(window, window.generation_status_strip)
    summary_bottom = _top_in_shell(window, queue.summary) + queue.summary.height()
    assert summary_bottom - launch_top <= 220
    window.close()
