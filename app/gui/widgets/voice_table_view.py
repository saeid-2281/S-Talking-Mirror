from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QTableWidgetItem

from app.gui.widgets.voice_table_model import VoiceTableModel
from app.services.voice_service import VoiceItem


class VoiceTableView(QTableView):
    """Professional Model/View voice catalog with legacy read helpers."""

    voice_selection_changed = Signal()
    voice_double_clicked = Signal(int, int)

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._voice_model = VoiceTableModel(self)
        self.setModel(self._voice_model)
        self.setObjectName("voiceCatalogTable")
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        header = self.horizontalHeader()
        header.setSectionsClickable(True)
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (0, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.selectionModel().selectionChanged.connect(lambda *_: self.voice_selection_changed.emit())
        self.doubleClicked.connect(lambda index: self.voice_double_clicked.emit(index.row(), index.column()))
        QShortcut(QKeySequence("Escape"), self, activated=self.clearSelection)

    @property
    def voice_model(self) -> VoiceTableModel:
        return self._voice_model

    def set_items(self, items: list[VoiceItem] | tuple[VoiceItem, ...], selected_id: str | None = None) -> None:
        self._voice_model.set_items(items)
        if items:
            row = self._voice_model.row_for_voice_id(selected_id)
            self.selectRow(row if row >= 0 else 0)
        else:
            self.clearSelection()

    def selected_item(self) -> VoiceItem | None:
        index = self.currentIndex()
        return self._voice_model.item_at(index.row()) if index.isValid() else None

    def selectRow(self, row: int) -> None:  # noqa: N802
        if not 0 <= row < self._voice_model.rowCount():
            self.clearSelection()
            return
        index = self._voice_model.index(row, 0)
        self.setCurrentIndex(index)
        self.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def select_voice_id(self, voice_id: str, *, scroll: bool = True) -> bool:
        row = self._voice_model.row_for_voice_id(voice_id)
        if row < 0:
            return False
        index = self._voice_model.index(row, 0)
        self.setCurrentIndex(index)
        self.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
        if scroll:
            self.scrollTo(index, QAbstractItemView.PositionAtCenter)
        return True

    # Temporary compatibility with the previous QTableWidget surface used by
    # existing regression tests and a few call sites.
    def rowCount(self) -> int:  # noqa: N802
        return self._voice_model.rowCount()

    def columnCount(self) -> int:  # noqa: N802
        return self._voice_model.columnCount()

    def currentRow(self) -> int:  # noqa: N802
        return self.currentIndex().row()

    def item(self, row: int, column: int) -> QTableWidgetItem | None:
        index = self._voice_model.index(row, column)
        if not index.isValid():
            return None
        item = QTableWidgetItem(str(index.data(Qt.DisplayRole) or ""))
        item.setData(Qt.UserRole, index.data(Qt.UserRole + 2))
        return item
