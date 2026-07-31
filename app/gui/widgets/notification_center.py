from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.product_events import NotificationRecord
from app.services.notification_center_service import NotificationCenterService


class NotificationCenterWidget(QWidget):
    """Searchable, persistent notification history."""

    def __init__(self, service: NotificationCenterService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setObjectName("notificationCenter")
        self._records: dict[str, NotificationRecord] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        toolbar = QHBoxLayout()
        self.title = QLabel("Notifications")
        self.title.setObjectName("panelTitle")
        self.badge = QLabel("0")
        self.badge.setObjectName("notificationBadge")
        self.severity = QComboBox()
        self.severity.addItems(["All", "Success", "Info", "Warning", "Error"])
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notifications…")
        toolbar.addWidget(self.title)
        toolbar.addWidget(self.badge)
        toolbar.addStretch()
        toolbar.addWidget(self.severity)
        root.addLayout(toolbar)
        root.addWidget(self.search)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("notificationList")
        self.list_widget.itemDoubleClicked.connect(self.mark_selected_read)
        root.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        self.mark_read_button = QPushButton("Mark read")
        self.dismiss_button = QPushButton("Dismiss")
        self.clear_button = QPushButton("Clear all")
        self.mark_read_button.clicked.connect(self.mark_selected_read)
        self.dismiss_button.clicked.connect(self.dismiss_selected)
        self.clear_button.clicked.connect(self.clear_all)
        actions.addWidget(self.mark_read_button)
        actions.addWidget(self.dismiss_button)
        actions.addStretch()
        actions.addWidget(self.clear_button)
        root.addLayout(actions)

        self.search.textChanged.connect(self.refresh)
        self.severity.currentTextChanged.connect(self.refresh)
        self._unsubscribe = self.service.subscribe(lambda _record: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().strip().casefold()
        selected_severity = self.severity.currentText().casefold()
        records = self.service.list()
        self._records = {record.notification_id: record for record in records}
        self.list_widget.clear()
        for record in records:
            if selected_severity != "all" and record.severity.casefold() != selected_severity:
                continue
            haystack = f"{record.title} {record.message}".casefold()
            if query and query not in haystack:
                continue
            marker = "●" if not record.read else "○"
            item = QListWidgetItem(f"{marker} {record.title}\n{record.message}")
            item.setData(Qt.UserRole, record.notification_id)
            item.setToolTip(record.created_at)
            self.list_widget.addItem(item)
        self.badge.setText(str(self.service.unread_count()))
        self.badge.setVisible(self.service.unread_count() > 0)

    def selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.UserRole)) if item else None

    def mark_selected_read(self, *_args) -> None:
        notification_id = self.selected_id()
        if notification_id:
            self.service.mark_read(notification_id)
            self.refresh()

    def dismiss_selected(self) -> None:
        notification_id = self.selected_id()
        if notification_id:
            self.service.dismiss(notification_id)
            self.refresh()

    def clear_all(self) -> None:
        self.service.clear()
        self.refresh()

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
