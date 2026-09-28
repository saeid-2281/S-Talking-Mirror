from __future__ import annotations

from PySide6.QtWidgets import QHeaderView, QTableWidget

from app.gui.widgets.queue_table_model import QueueColumn
from app.gui.widgets.queue_table_view import QueueTableView
from app.gui.widgets.queue_workspace import DEFAULT_QUEUE_COLUMNS, configure_queue_table


COMPACT_WIDTHS = {
    int(QueueColumn.SOURCE_ROW): 121,
    int(QueueColumn.CHARACTERS): 117,
    int(QueueColumn.STATUS): 91,
    int(QueueColumn.DURATION): 108,
    int(QueueColumn.RETRY): 87,
}


def _assert_fast_header_contract(table) -> None:  # noqa: ANN001
    header = table.horizontalHeader()
    assert header.sectionResizeMode(int(QueueColumn.FILENAME)) == QHeaderView.Stretch
    assert header.sectionResizeMode(int(QueueColumn.OUTPUT)) == QHeaderView.Stretch
    for column, width in COMPACT_WIDTHS.items():
        assert header.sectionResizeMode(column) == QHeaderView.Interactive
        assert table.columnWidth(column) == width


def test_model_view_queue_avoids_resize_to_contents_rescans(qt_app) -> None:  # noqa: ANN001
    view = QueueTableView()
    _assert_fast_header_contract(view)
    view.close()


def test_legacy_queue_uses_same_deterministic_compact_widths(qt_app) -> None:  # noqa: ANN001
    table = QTableWidget(0, len(DEFAULT_QUEUE_COLUMNS))
    table.setHorizontalHeaderLabels(list(DEFAULT_QUEUE_COLUMNS))
    configure_queue_table(table)
    _assert_fast_header_contract(table)
    table.close()


def test_compact_columns_remain_user_resizable(qt_app) -> None:  # noqa: ANN001
    view = QueueTableView()
    header = view.horizontalHeader()
    column = int(QueueColumn.STATUS)
    before = view.columnWidth(column)
    view.setColumnWidth(column, before + 24)
    assert header.sectionResizeMode(column) == QHeaderView.Interactive
    assert view.columnWidth(column) == before + 24
    view.close()
