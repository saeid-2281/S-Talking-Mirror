from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from app.services.voice_service import VoiceItem


class VoiceDataRole(IntEnum):
    ITEM = int(Qt.UserRole) + 1
    VOICE_ID = int(Qt.UserRole) + 2
    SEARCH_TEXT = int(Qt.UserRole) + 3
    FAVORITE = int(Qt.UserRole) + 4


class VoiceTableModel(QAbstractTableModel):
    """Read-only, identity-stable table model for provider voices."""

    HEADERS = ("Favorite", "Voice Name", "Language", "Accent", "Gender", "Age", "Category")

    def __init__(self, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._items: list[VoiceItem] = []
        self._row_by_id: dict[str, int] = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802, ANN001
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: ANN001
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        values = (
            "★" if item.is_favorite else "☆",
            item.name,
            item.language or "—",
            item.accent or "—",
            item.gender or "—",
            item.age or "—",
            item.category or "—",
        )
        if role in {Qt.DisplayRole, Qt.ToolTipRole}:
            return values[index.column()]
        if role == VoiceDataRole.ITEM:
            return item
        if role == VoiceDataRole.VOICE_ID:
            return item.voice_id
        if role == VoiceDataRole.SEARCH_TEXT:
            return " ".join(str(value) for value in values)
        if role == VoiceDataRole.FAVORITE:
            return item.is_favorite
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignCenter) if index.column() == 0 else int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def set_items(self, items: list[VoiceItem] | tuple[VoiceItem, ...]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._row_by_id = {item.voice_id: row for row, item in enumerate(self._items)}
        self.endResetModel()

    def item_at(self, row: int) -> VoiceItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def row_for_voice_id(self, voice_id: str | None) -> int:
        if not voice_id:
            return -1
        return self._row_by_id.get(str(voice_id), -1)
