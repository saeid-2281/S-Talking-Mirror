from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.activity_timeline_service import ActivityTimelineService


class ActivityTimelineWidget(QWidget):
    """Structured project and generation activity timeline."""

    def __init__(self, service: ActivityTimelineService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setObjectName("activityTimeline")
        self.project_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        filters = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItems(["All", "Project", "Import", "Provider", "Generation", "Preflight", "Report"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search activity…")
        self.copy_button = QPushButton("Copy")
        self.clear_button = QPushButton("Clear")
        filters.addWidget(self.category)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.copy_button)
        filters.addWidget(self.clear_button)
        root.addLayout(filters)
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("activityTimelineList")
        root.addWidget(self.list_widget, 1)

        self.search.textChanged.connect(self.refresh)
        self.category.currentTextChanged.connect(self.refresh)
        self.copy_button.clicked.connect(self.copy_selected)
        self.clear_button.clicked.connect(self.clear)
        self._unsubscribe = self.service.subscribe(lambda _event: self.refresh())
        self.refresh()

    def set_project_id(self, project_id: int | None) -> None:
        self.project_id = project_id
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().strip().casefold()
        category = self.category.currentText().casefold()
        self.list_widget.clear()
        for event in self.service.list(project_id=self.project_id):
            if category != "all" and event.category.casefold() != category:
                continue
            haystack = f"{event.title} {event.message}".casefold()
            if query and query not in haystack:
                continue
            timestamp = event.created_at.replace("T", " ")[:19]
            item = QListWidgetItem(f"{timestamp}  {event.title}\n{event.message}")
            item.setData(Qt.UserRole, event.event_id)
            item.setToolTip(event.category)
            self.list_widget.addItem(item)

    def copy_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item:
            QApplication.clipboard().setText(item.text())

    def clear(self) -> None:
        self.service.clear(project_id=self.project_id)
        self.refresh()

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
