from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QTableWidget

from app.gui.widgets.queue_workspace import (
    QUEUE_COLUMN_PRESETS,
    QueueColumnController,
)


def _table() -> QTableWidget:
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
    return table


def test_column_presets_keep_structural_columns_visible(qt_app, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "queue.ini"), QSettings.IniFormat)
    table = _table()
    controller = QueueColumnController(table, settings)

    assert controller.apply_preset("Compact")
    visible = {column for column in range(table.columnCount()) if not table.isColumnHidden(column)}

    assert visible == set(QUEUE_COLUMN_PRESETS["Compact"])
    assert not table.isColumnHidden(1)
    assert not table.isColumnHidden(5)
    assert table.columnWidth(1) >= 240


def test_column_preset_persists_through_controller_recreation(qt_app, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "queue.ini"), QSettings.IniFormat)
    first = _table()
    first_controller = QueueColumnController(first, settings)
    assert first_controller.apply_preset("Generation")

    restored = _table()
    QueueColumnController(restored, settings)
    visible = {column for column in range(restored.columnCount()) if not restored.isColumnHidden(column)}

    assert visible == set(QUEUE_COLUMN_PRESETS["Generation"])
    assert settings.value(QueueColumnController.PRESET_KEY) == "Generation"


def test_unknown_column_preset_is_rejected_without_mutation(qt_app, tmp_path) -> None:
    settings = QSettings(str(tmp_path / "queue.ini"), QSettings.IniFormat)
    table = _table()
    controller = QueueColumnController(table, settings)
    before = [table.isColumnHidden(column) for column in range(table.columnCount())]

    assert controller.apply_preset("Unknown") is False
    assert [table.isColumnHidden(column) for column in range(table.columnCount())] == before
