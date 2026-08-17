from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.visual_fidelity_hardening import VisualFidelityHardener


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_hotfix1_monitor_requested_width_is_published_before_geometry() -> None:
    source = inspect.getsource(VisualFidelityHardener.refresh_monitor)
    property_line = 'dock.setProperty("visualFidelityRequestedWidth", target_width)'
    clamp_line = "dock.setMinimumWidth(target_width)"

    assert property_line in source
    assert clamp_line in source
    assert source.index(property_line) < source.index(clamp_line)


def test_hotfix1_mainwindow_resize_preserves_active_monitor_target_width(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    monitor_index = next(
        index
        for index in range(window.right_tabs.count())
        if window.right_tabs.tabText(index) == "Generation Monitor"
    )
    window.right_tabs.setCurrentIndex(monitor_index)
    window.visual_fidelity_hardener.refresh_monitor()
    window.clamp_monitor_width()
    qt_app.processEvents()

    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340

    window.resize(window.width() + 1, window.height())
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.maximumWidth() <= 340
    window.close()
