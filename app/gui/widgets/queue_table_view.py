from __future__ import annotations

from collections.abc import Iterable, Sequence

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableView,
    QWidget,
)

from app.gui.widgets.queue_table_model import QueueColumn, QueueDataRole, QueueTableModel
from app.models.domain import TTSJob


class QueueTableView(QTableView):
    """Queue-specific QTableView prepared for gradual MainWindow migration.

    The class deliberately exposes a few QTableWidget-like signals and helpers
    used by the current application so the old table can be replaced in small,
    testable steps rather than through a high-risk all-at-once rewrite.
    """

    itemSelectionChanged = Signal()
    cellDoubleClicked = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("queueTable")
        self.setProperty("implementation","model-view")
        self._queue_model = QueueTableModel(self)
        self.setModel(self._queue_model)

        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSortingEnabled(False)
        self.verticalHeader().setVisible(True)
        self.verticalHeader().setFixedWidth(46)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.verticalHeader().setToolTip("Queue row · current displayed position")
        self.verticalHeader().setDefaultSectionSize(32)
        self.verticalHeader().setMinimumSectionSize(28)

        header = self.horizontalHeader()
        header.setObjectName("queueHeader")
        header.setSectionsClickable(True)
        header.setHighlightSections(False)
        header.setSortIndicatorShown(True)
        header.setMinimumSectionSize(56)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(int(QueueColumn.FILENAME), QHeaderView.Stretch)
        header.setSectionResizeMode(int(QueueColumn.OUTPUT), QHeaderView.Stretch)
        for column in (
            QueueColumn.SOURCE_ROW,
            QueueColumn.CHARACTERS,
            QueueColumn.STATUS,
            QueueColumn.DURATION,
            QueueColumn.RETRY,
        ):
            header.setSectionResizeMode(int(column), QHeaderView.ResizeToContents)

        self.setColumnWidth(int(QueueColumn.SOURCE), 140)
        self.setColumnWidth(int(QueueColumn.WORKSHEET), 110)
        self.setColumnWidth(int(QueueColumn.PROVIDER), 110)
        self.setColumnWidth(int(QueueColumn.VOICE), 150)
        self.setColumnWidth(int(QueueColumn.MODEL), 160)

        self.selectionModel().selectionChanged.connect(lambda *_: self.itemSelectionChanged.emit())
        self.doubleClicked.connect(self._emit_cell_double_clicked)
        QShortcut(QKeySequence.SelectAll, self, activated=self.selectAll)
        QShortcut(QKeySequence("Escape"), self, activated=self.clearSelection)

    @property
    def queue_model(self) -> QueueTableModel:
        return self._queue_model

    # Temporary QTableWidget compatibility helpers. Existing project and
    # regression code still asks the public queue surface for row/column counts
    # while the application migrates to QTableView. Keep these methods on the
    # view so callers do not need to know which implementation is active.
    def rowCount(self) -> int:  # noqa: N802
        return self._queue_model.rowCount()

    def columnCount(self) -> int:  # noqa: N802
        return self._queue_model.columnCount()

    def set_jobs(self, jobs: Sequence[TTSJob] | Iterable[TTSJob], **kwargs) -> None:  # noqa: ANN003
        selected_ids = self.selected_job_ids()
        self._queue_model.set_jobs(jobs, **kwargs)
        self.restore_selection(selected_ids)

    def selected_rows(self) -> list[int]:
        selection = self.selectionModel()
        if selection is None:
            return []
        return sorted({index.row() for index in selection.selectedRows()})

    def selected_job_ids(self) -> set[int]:
        result: set[int] = set()
        for row in self.selected_rows():
            index = self._queue_model.index(row, int(QueueColumn.SOURCE_ROW))
            value = index.data(QueueDataRole.JOB_ID)
            if value is not None:
                result.add(int(value))
        return result

    def selected_jobs(self) -> list[TTSJob]:
        jobs: list[TTSJob] = []
        for row in self.selected_rows():
            job = self._queue_model.job_at(row)
            if job is not None:
                jobs.append(job)
        return jobs

    def restore_selection(self, job_ids: Iterable[int]) -> None:
        selection = self.selectionModel()
        if selection is None:
            return
        ids = {int(job_id) for job_id in job_ids}
        if not ids:
            return
        self.blockSignals(True)
        try:
            self.clearSelection()
            for job_id in ids:
                row = self._queue_model.row_for_job_id(job_id)
                if row is None:
                    continue
                index = self._queue_model.index(row, 0)
                selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        finally:
            self.blockSignals(False)
        self.itemSelectionChanged.emit()

    def select_job_id(self, job_id: int, *, clear: bool = True, scroll: bool = True) -> bool:
        row = self._queue_model.row_for_job_id(int(job_id))
        if row is None:
            return False
        index = self._queue_model.index(row, 0)
        flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
        if clear:
            flags |= QItemSelectionModel.Clear
        self.selectionModel().select(index, flags)
        self.setCurrentIndex(index)
        if scroll:
            self.scrollTo(index, QAbstractItemView.PositionAtCenter)
        return True

    def job_at_view_row(self, row: int) -> TTSJob | None:
        return self._queue_model.job_at(row)

    def context_menu(self, parent: QWidget | None = None) -> QMenu:
        return QMenu(parent or self)

    def _emit_cell_double_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.cellDoubleClicked.emit(index.row(), index.column())
