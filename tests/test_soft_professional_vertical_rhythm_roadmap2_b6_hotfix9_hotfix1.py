from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtWidgets import QSizePolicy

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


def test_hotfix9_hotfix1_collapsed_batch_row_has_zero_layout_authority() -> None:
    source = inspect.getsource(MainWorkspaceModernizer._sync_batch_range_host_geometry)

    assert 'self._batch_expanded and self._responsive_mode != "compact"' in source
    assert "host.setMinimumHeight(0)" in source
    assert "host.setMaximumHeight(0)" in source
    assert "host.hide()" in source
    assert "COMPONENTS.control_compact_height + 8" in source


def test_hotfix9_hotfix1_wide_collapsed_batch_row_cannot_recreate_dead_gap(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    window.main_workspace_modernizer.reveal_batch_planning(False)
    window.main_workspace_modernizer.reapply_visual_geometry()
    for _ in range(5):
        qt_app.processEvents()

    host = window.queue_workspace.range_host
    assert host.isHidden()
    assert host.minimumHeight() == 0
    assert host.maximumHeight() == 0
    assert host.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed

    command_gap = window.queue_workspace.command_host.y() - (
        window.queue_workspace.heading.y() + window.queue_workspace.heading.height()
    )
    assert 0 <= command_gap <= 8
    window.close()


def test_hotfix9_hotfix1_batch_row_restores_one_compact_row_only_when_explicit(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(True)
    qt_app.processEvents()

    host = window.queue_workspace.range_host
    expected_height = COMPONENTS.control_compact_height + 8
    assert not host.isHidden()
    assert host.minimumHeight() == expected_height
    assert host.maximumHeight() == expected_height

    modernizer.apply_responsive_mode("compact")
    qt_app.processEvents()
    assert host.isHidden()
    assert host.maximumHeight() == 0

    modernizer.apply_responsive_mode("wide")
    qt_app.processEvents()
    assert not host.isHidden()
    assert host.minimumHeight() == expected_height
    assert host.maximumHeight() == expected_height
    window.close()
