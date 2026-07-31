from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QTableWidget, QWidget

from app.gui.widgets.queue_details_pane import QueueDetailsPane
from app.gui.widgets.queue_workspace import QueueColumnController


def test_queue_details_pane_exposes_migration_contract(qt_app) -> None:
    host = QWidget()
    pane = QueueDetailsPane(
        host,
        play_output=lambda: None,
        open_output=lambda: None,
        stop_playback=lambda: None,
        copy_output=lambda: None,
    )
    assert pane.pname.text() == "No row selected"
    assert pane.ptext.isReadOnly()
    assert pane.play_output_button.text() == "Play"


def test_column_controller_persists_complete_header_state(qt_app, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "queue.ini"), QSettings.IniFormat)
    table = QTableWidget(0, 4)
    table.setHorizontalHeaderLabels(["A", "B", "C", "D"])
    controller = QueueColumnController(table, settings)
    table.setColumnWidth(2, 222)
    table.horizontalHeader().moveSection(3, 0)
    controller.save_header_state()

    restored = QTableWidget(0, 4)
    restored.setHorizontalHeaderLabels(["A", "B", "C", "D"])
    restored_controller = QueueColumnController(restored, settings)
    assert restored.columnWidth(2) == 222
    assert restored.horizontalHeader().visualIndex(3) == 0
    assert restored_controller.restore_header_state()
