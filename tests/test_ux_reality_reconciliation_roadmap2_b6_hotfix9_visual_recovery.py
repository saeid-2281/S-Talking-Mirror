from __future__ import annotations

import inspect

from app.gui.main import MainWindow


def test_visual_recovery_restores_b6h3_first_paint_and_non_modal_path_contracts() -> None:
    constructor = inspect.getsource(MainWindow.__init__)
    deferred = inspect.getsource(MainWindow._finish_deferred_startup)
    build = inspect.getsource(MainWindow.build)
    warnings = inspect.getsource(MainWindow.show_path_warnings)

    assert "QTimer.singleShot(50,self._finish_deferred_startup)" in constructor
    assert "self.restore_previous_session()" not in constructor
    assert "self.run_startup_recovery()" in deferred
    assert "self.restore_previous_session()" in deferred
    assert "ProjectPathNotice" in build
    assert "project_path_notice.show_validation" in warnings
    assert "notifications.warning" not in warnings


def test_visual_recovery_restores_hidpi_font_and_monitor_runtime_contracts() -> None:
    toolbar = inspect.getsource(MainWindow.build_main_toolbar)
    responsive = inspect.getsource(MainWindow._apply_responsive_workspace)
    clamp = inspect.getsource(MainWindow.clamp_monitor_width)
    module_source = inspect.getsource(inspect.getmodule(MainWindow))

    assert "setIconSize(QSize(24,24))" in toolbar
    assert "visualFidelityRequestedWidth" in responsive
    assert "visualFidelityRequestedWidth" in clamp
    assert "visualFidelityPresentationLocked" in clamp
    assert "ensure_readable_runtime_font(qt_app)" in module_source


def test_visual_recovery_preserves_h9_structural_disclosure_resync() -> None:
    source = inspect.getsource(MainWindow._sync_workspace_overlay_compact)

    assert "generation_journey.set_compact_mode(compact)" in source
    assert "queue_batch_operations.set_compact_mode(compact)" in source
    assert "main_workspace_modernizer.sync_queue_disclosure_layout_from_widgets()" in source
