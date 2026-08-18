from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import Qt

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.theme_accessibility_v2 import soft_professional_vertical_rhythm_stylesheet
from app.gui.visual_design_system_v2 import COMPONENTS
from app.gui.widgets.queue_table_view import QueueTableView


def _window(tmp_path: Path) -> MainWindow:
    return MainWindow(
        create_application_context(
            create_service_container(RuntimeConfig.from_root(tmp_path))
        )
    )


def test_hotfix10_toolbar_uses_centered_24px_icon_geometry() -> None:
    source = inspect.getsource(MainWindow.build_main_toolbar)
    style = soft_professional_vertical_rhythm_stylesheet(is_dark=True)

    assert "setIconSize(QSize(24,24))" in source
    assert "setFixedHeight(42)" in source
    assert "QToolBar#mainToolbar" in style
    assert "padding:4px 8px 5px 8px" in style
    assert "min-height:32px" in style
    assert "max-height:32px" in style
    assert "padding:0 9px" in style


def test_hotfix10_generation_primary_is_compact_without_losing_accessible_name(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    window.main_workspace_modernizer.apply_responsive_mode("wide")
    window.main_workspace_modernizer.reapply_visual_geometry()
    qt_app.processEvents()

    bar = window.generation_status_strip
    assert bar.start_button.text() == "Start"
    assert bar.start_button.accessibleName() == "Start generation"
    assert {
        bar.start_button.height(),
        bar.preflight_button.height(),
        bar.pause_button.height(),
        bar.stop_button.height(),
    } == {COMPONENTS.control_compact_height}
    window.close()


def test_hotfix10_range_disclosure_is_visible_without_batch_plan(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_batch_planning(False)
    modernizer.reveal_workflow(False)
    qt_app.processEvents()

    queue = window.queue_workspace
    assert not modernizer.range_toggle.isHidden()
    assert modernizer.range_toggle.text() == "Range"
    assert queue.root_layout.indexOf(queue.range_host) == -1

    modernizer.reveal_range_controls(True)
    qt_app.processEvents()
    assert queue.root_layout.indexOf(queue.range_host) >= 1
    assert queue.root_layout.indexOf(window.queue_batch_operations) == -1
    assert not queue.range_host.isHidden()
    assert queue.range_host.maximumHeight() == COMPONENTS.control_compact_height + 8

    modernizer.reveal_range_controls(False)
    qt_app.processEvents()
    assert queue.root_layout.indexOf(queue.range_host) == -1
    window.close()


def test_hotfix10_batch_plan_keeps_historical_range_row_contract(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    window.resize(2048, 1140)
    window.show()
    modernizer = window.main_workspace_modernizer
    modernizer.apply_responsive_mode("wide")
    modernizer.reveal_range_controls(False)
    modernizer.reveal_batch_planning(True)
    qt_app.processEvents()

    queue = window.queue_workspace
    assert queue.root_layout.indexOf(window.queue_batch_operations) >= 1
    assert queue.root_layout.indexOf(queue.range_host) > queue.root_layout.indexOf(
        window.queue_batch_operations
    )

    modernizer.reveal_batch_planning(False)
    qt_app.processEvents()
    assert queue.root_layout.indexOf(queue.range_host) == -1
    window.close()


def test_hotfix10_queue_row_numbers_are_visible_current_display_positions(qt_app) -> None:  # noqa: ANN001
    table = QueueTableView()
    header = table.verticalHeader()

    assert not header.isHidden()
    assert header.width() == 46
    assert header.defaultAlignment() == Qt.AlignCenter
    assert "current displayed position" in header.toolTip().lower()
    table.close()


def test_hotfix10_range_basis_still_supports_original_and_displayed_rows(
    qt_app, tmp_path: Path
) -> None:  # noqa: ANN001
    window = _window(tmp_path)
    values = {
        str(window.range_basis.itemData(index))
        for index in range(window.range_basis.count())
    }
    assert {"row_range", "display_range"}.issubset(values)
    assert window.range_from.specialValueText() == "First"
    assert window.range_to.specialValueText() == "Last"
    window.close()
