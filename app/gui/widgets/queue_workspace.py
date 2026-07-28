from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QWidget,
)


@dataclass(frozen=True)
class QueueSelectionStats:
    visible_jobs: int
    visible_characters: int
    selected_jobs: int
    selected_characters: int
    scope_label: str


class QueueScopeSummary(QFrame):
    """Compact, always-readable summary for the current queue view and scope."""

    clear_selection_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("queueScopeSummary")
        self.setMaximumHeight(38)
        self.setMinimumHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        self.visible_label = QLabel("Visible: 0 jobs · 0 characters")
        self.visible_label.setObjectName("queueVisibleSummary")
        self.selected_label = QLabel("Selected: 0 jobs · 0 characters")
        self.selected_label.setObjectName("queueSelectedSummary")
        self.scope_label = QLabel("Scope: Entire queue")
        self.scope_label.setObjectName("queueActiveScope")

        layout.addWidget(self.visible_label)
        layout.addWidget(self._separator())
        layout.addWidget(self.selected_label)
        layout.addStretch(1)
        layout.addWidget(self.scope_label)

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("queueSummarySeparator")
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        return separator

    def update_stats(self, stats: QueueSelectionStats) -> None:
        self.visible_label.setText(
            f"Visible: {stats.visible_jobs:,} jobs · {stats.visible_characters:,} characters"
        )
        self.selected_label.setText(
            f"Selected: {stats.selected_jobs:,} jobs · {stats.selected_characters:,} characters"
        )
        self.scope_label.setText(f"Scope: {stats.scope_label}")
        self.selected_label.setProperty("active", bool(stats.selected_jobs))
        self.selected_label.style().unpolish(self.selected_label)
        self.selected_label.style().polish(self.selected_label)


def configure_queue_table(table: QTableWidget) -> None:
    """Apply the shared professional data-grid behavior to the queue table."""

    table.setObjectName("queueTable")
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideMiddle)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(32)
    table.verticalHeader().setMinimumSectionSize(28)

    header = table.horizontalHeader()
    header.setObjectName("queueHeader")
    header.setSectionsClickable(True)
    header.setHighlightSections(False)
    header.setSortIndicatorShown(True)
    header.setMinimumSectionSize(56)
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    # Filename and output absorb available width; data columns remain compact.
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setSectionResizeMode(1, QHeaderView.Stretch)
    header.setSectionResizeMode(11, QHeaderView.Stretch)
    for column in (0, 4, 5, 9, 10):
        header.setSectionResizeMode(column, QHeaderView.ResizeToContents)

    table.setColumnWidth(2, 140)
    table.setColumnWidth(3, 110)
    table.setColumnWidth(6, 110)
    table.setColumnWidth(7, 150)
    table.setColumnWidth(8, 160)

    # Standard desktop selection shortcuts.
    QShortcut(QKeySequence.SelectAll, table, activated=table.selectAll)
    QShortcut(QKeySequence("Escape"), table, activated=table.clearSelection)
