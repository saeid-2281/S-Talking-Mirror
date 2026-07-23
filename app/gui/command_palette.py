from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


@dataclass
class PaletteCommand:
    name: str
    callback: Callable[[], None]
    enabled: Callable[[], bool] = lambda: True


class CommandPalette(QDialog):
    def __init__(self, commands: list[PaletteCommand], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.commands = commands
        self.filtered: list[PaletteCommand] = []
        self.setWindowTitle("Command Palette")
        self.setModal(False)
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands...")
        self.list = QListWidget()
        layout.addWidget(self.search)
        layout.addWidget(self.list)
        self.search.textChanged.connect(self.filter_commands)
        self.list.itemDoubleClicked.connect(lambda _item: self.execute_selected())
        self.filter_commands("")

    def filter_commands(self, text: str) -> None:
        query = text.casefold().strip()
        self.list.clear()
        self.filtered = [
            command
            for command in self.commands
            if not query or all(part in command.name.casefold() for part in query.split())
        ]
        for command in self.filtered:
            item = QListWidgetItem(command.name)
            item.setFlags(item.flags() | Qt.ItemIsEnabled)
            if not command.enabled():
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setToolTip("Command is not currently available.")
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def execute_selected(self) -> bool:
        row = self.list.currentRow()
        if row < 0 or row >= len(self.filtered):
            return False
        command = self.filtered[row]
        if not command.enabled():
            return False
        command.callback()
        self.close()
        return True

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key_Return, Qt.Key_Enter}:
            self.execute_selected()
            return
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        if event.key() in {Qt.Key_Down, Qt.Key_Up}:
            current = self.list.currentRow()
            delta = 1 if event.key() == Qt.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, current + delta)))
            return
        super().keyPressEvent(event)
