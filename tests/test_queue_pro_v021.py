from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QTableWidget

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.queue_workspace import (
    QueueColumnController,
    QueueStatusDelegate,
    QueueWorkspace,
    configure_queue_table,
)


def test_queue_workspace_is_an_independent_visual_shell(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    assert isinstance(window.queue_workspace, QueueWorkspace)
    assert window.queue_workspace.objectName() == "queueWorkspace"
    assert window.queue_workspace.summary is window.queue_scope_summary
    assert window.queue_workspace.columns_button.menu() is not None
    assert window.queue_workspace.footer.text()
    assert window.table.parentWidget() is not window

    window.close()


def test_queue_table_has_status_delegate_and_movable_columns(qt_app) -> None:
    table = QTableWidget(0, 12)
    table.setHorizontalHeaderLabels(
        [
            "Source row",
            "Filename",
            "Source",
            "Worksheet",
            "Characters",
            "Status",
            "Provider",
            "Voice",
            "Model",
            "Duration",
            "Retry",
            "Output",
        ]
    )
    configure_queue_table(table)

    assert isinstance(table.itemDelegateForColumn(5), QueueStatusDelegate)
    assert table.horizontalHeader().sectionsMovable() is True
    assert table.selectionBehavior() == QTableWidget.SelectRows


def test_queue_column_visibility_is_persistent_and_structural_columns_stay_visible(
    qt_app, tmp_path: Path
) -> None:
    QSettings.setDefaultFormat(QSettings.IniFormat)
    settings = QSettings(str(tmp_path / "queue.ini"), QSettings.IniFormat)
    table = QTableWidget(0, 12)
    table.setHorizontalHeaderLabels([f"Column {i}" for i in range(12)])
    controller = QueueColumnController(table, settings)

    controller.set_visible(2, False)
    assert table.isColumnHidden(2) is True

    controller.set_visible(1, False)
    controller.set_visible(5, False)
    assert table.isColumnHidden(1) is False
    assert table.isColumnHidden(5) is False

    second = QTableWidget(0, 12)
    second.setHorizontalHeaderLabels([f"Column {i}" for i in range(12)])
    QueueColumnController(second, settings)
    assert second.isColumnHidden(2) is True
    assert second.isColumnHidden(1) is False
    assert second.isColumnHidden(5) is False


def test_main_window_no_longer_builds_a_plain_queue_container_inline() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "self.queue_workspace=QueueWorkspace()" in source
    assert "mid=QWidget(); ml=QVBoxLayout(mid)" not in source
