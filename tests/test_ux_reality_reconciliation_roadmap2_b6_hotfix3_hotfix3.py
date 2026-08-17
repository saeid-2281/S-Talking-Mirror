from __future__ import annotations

import inspect
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def _activate_monitor(window: MainWindow, qt_app) -> None:  # noqa: ANN001
    window.show()
    qt_app.processEvents()
    monitor_index = next(
        index
        for index in range(window.right_tabs.count())
        if window.right_tabs.tabText(index) == "Generation Monitor"
    )
    window.right_tabs.setCurrentIndex(monitor_index)
    window.visual_fidelity_hardener.refresh_monitor()
    qt_app.processEvents()


def test_hotfix3_responsive_layout_recognizes_visual_fidelity_monitor_authority() -> None:
    source = inspect.getsource(MainWindow._apply_responsive_workspace)

    assert "visualFidelityRequestedWidth" in source
    assert "requested_monitor_width" in source
    assert "self.right_tabs.currentWidget() is self.monitor_scroll" in source
    assert "self.clamp_monitor_width()" in source


def test_hotfix3_forced_responsive_refresh_cannot_collapse_active_monitor(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    _activate_monitor(window, qt_app)

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340

    # Reproduce the delayed ResponsiveWorkspaceCoordinator handoff that could
    # previously overwrite the A11.1 monitor width with the generic inspector
    # width (290/310/330px) after the certifier or another slow UI test.
    window.responsive_workspace.refresh(force=True)
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.maximumWidth() <= 340
    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    window.close()


def test_hotfix3_monitor_contract_survives_second_responsive_reconciliation(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    _activate_monitor(window, qt_app)

    window.responsive_workspace.refresh(force=True)
    window.visual_fidelity_hardener.refresh_monitor()
    window.responsive_workspace.refresh(force=True)
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 320 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    window.close()
