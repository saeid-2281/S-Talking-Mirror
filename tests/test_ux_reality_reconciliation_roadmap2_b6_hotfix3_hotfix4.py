from __future__ import annotations

import inspect
from pathlib import Path

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


def test_hotfix4_active_monitor_uses_persistent_internal_qt_constraint() -> None:
    main_source = inspect.getsource(MainWindow.clamp_monitor_width)
    hardener_source = inspect.getsource(VisualFidelityHardener.refresh_monitor)

    assert "visualFidelityPresentationLocked" in main_source
    assert "visualFidelityPresentationLocked" in hardener_source
    assert "self.monitor_dock.setMinimumWidth(width)" in main_source
    assert "self.monitor_dock.setMaximumWidth(width)" in main_source
    active_block = main_source.split("if monitor_active and requested not in (None,''):", 1)[1]
    assert "setMinimumWidth(MONITOR_MIN_WIDTH)" not in active_block.split("return", 1)[0]


def test_hotfix4_forced_responsive_refresh_keeps_active_monitor_layout_locked(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    _activate_monitor(window, qt_app)

    # Public compatibility stays 290 px while Qt's internal layout constraint
    # remains at the active presentation width.
    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert window.monitor_dock.minimumSize().width() >= 320
    assert window.monitor_dock.property("visualFidelityPresentationLocked") is True
    assert 320 <= window.monitor_dock.width() <= 340

    window.responsive_workspace.refresh(force=True)
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert window.monitor_dock.minimumSize().width() >= 320
    assert window.monitor_dock.property("visualFidelityPresentationLocked") is True
    assert window.monitor_dock.property("visualFidelityRequestedWidth") == 340
    assert 320 <= window.monitor_dock.width() <= 340
    window.close()


def test_hotfix4_repeated_responsive_refreshes_cannot_collapse_active_monitor(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    _activate_monitor(window, qt_app)

    for _ in range(3):
        window.responsive_workspace.refresh(force=True)
        qt_app.processEvents()
        assert window.monitor_dock.minimumSize().width() >= 320
        assert 320 <= window.monitor_dock.width() <= 340
    window.close()


def test_hotfix4_leaving_monitor_releases_internal_layout_constraint(
    qt_app, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    _activate_monitor(window, qt_app)

    selected_index = next(
        index
        for index in range(window.right_tabs.count())
        if window.right_tabs.tabText(index) == "Selected Row"
    )
    window.right_tabs.setCurrentIndex(selected_index)
    window.visual_fidelity_hardener.refresh_monitor()
    qt_app.processEvents()

    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert window.monitor_dock.minimumSize().width() <= 300
    assert window.monitor_dock.property("visualFidelityPresentationLocked") is False
    assert window.monitor_dock.property("visualFidelityRequestedWidth") in (None, "")
    window.close()
