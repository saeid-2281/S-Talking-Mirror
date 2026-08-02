from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.professional_components import EmptyStateCard, InlineFeedbackBar
from app.models.product_events import NotificationRecord
from app.services.notification_center_service import NotificationCenterService


_SEVERITY_ICON = {
    "success": "general.success",
    "info": "general.info",
    "warning": "general.warning",
    "error": "general.error",
}


class NotificationCard(QFrame):
    """Readable notification row with a direct optional action."""

    action_requested = Signal(str, str)

    def __init__(self, record: NotificationRecord, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.record = record
        self.setObjectName("notificationCard")
        self.setProperty("severity", self._severity(record.severity))
        self.setProperty("unread", not record.read)
        self.setAccessibleName(record.title)
        self.setAccessibleDescription(record.message)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        self.severity_icon = QLabel()
        self.severity_icon.setObjectName("notificationSeverityIcon")
        icon_name = _SEVERITY_ICON.get(self._severity(record.severity), "general.info")
        self.severity_icon.setPixmap(action_icon(icon_name, size=18).pixmap(18, 18))
        self.severity_icon.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.severity_icon.setFixedWidth(24)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(8)
        self.unread_dot = QLabel("●" if not record.read else "")
        self.unread_dot.setObjectName("notificationUnreadDot")
        self.unread_dot.setFixedWidth(12)
        self.title_label = QLabel(record.title)
        self.title_label.setObjectName("notificationCardTitle")
        self.title_label.setWordWrap(True)
        self.timestamp_label = QLabel(self._format_timestamp(record.created_at))
        self.timestamp_label.setObjectName("notificationCardTimestamp")
        self.timestamp_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        heading.addWidget(self.unread_dot)
        heading.addWidget(self.title_label, 1)
        heading.addWidget(self.timestamp_label)

        self.message_label = QLabel(record.message)
        self.message_label.setObjectName("notificationCardMessage")
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        content.addLayout(heading)
        content.addWidget(self.message_label)

        root.addWidget(self.severity_icon)
        root.addLayout(content, 1)

        self.action_button = QToolButton()
        self.action_button.setObjectName("notificationCardAction")
        self.action_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.action_button.setIcon(action_icon("open"))
        self.action_button.setText(record.action_label or "Open")
        self.action_button.setVisible(bool(record.action_payload))
        self.action_button.setAccessibleName(record.action_label or "Open notification action")
        self.action_button.clicked.connect(self._emit_action)
        root.addWidget(self.action_button, 0, Qt.AlignVCenter)

    @staticmethod
    def _severity(value: str) -> str:
        normalized = str(value or "info").casefold()
        return normalized if normalized in _SEVERITY_ICON else "info"

    @staticmethod
    def _format_timestamp(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
        return parsed.astimezone().strftime("%Y-%m-%d · %H:%M")

    def _emit_action(self) -> None:
        payload = str(self.record.action_payload or "").strip()
        if payload:
            self.action_requested.emit(self.record.notification_id, payload)


class NotificationCenterWidget(QWidget):
    """Professional, searchable notification history with actionable feedback."""

    action_requested = Signal(str)

    def __init__(self, service: NotificationCenterService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setObjectName("notificationCenter")
        self._records: dict[str, NotificationRecord] = {}
        self._filtered_ids: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QFrame()
        header.setObjectName("notificationCenterHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        header_layout.setSpacing(10)

        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(2)
        self.title = QLabel("Notifications")
        self.title.setObjectName("notificationCenterTitle")
        self.subtitle = QLabel("Operational messages, warnings and actions in one place")
        self.subtitle.setObjectName("notificationCenterSubtitle")
        self.subtitle.setWordWrap(True)
        heading.addWidget(self.title)
        heading.addWidget(self.subtitle)
        header_layout.addLayout(heading, 1)

        self.badge = QLabel("0 unread")
        self.badge.setObjectName("notificationBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.mark_all_button = QPushButton("Mark all read")
        self.mark_all_button.setObjectName("notificationMarkAll")
        self.mark_all_button.setIcon(action_icon("general.success"))
        self.mark_all_button.clicked.connect(self.mark_all_read)
        header_layout.addWidget(self.badge)
        header_layout.addWidget(self.mark_all_button)
        root.addWidget(header)

        filters = QFrame()
        filters.setObjectName("notificationFilterBar")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setObjectName("notificationSearch")
        self.search.setPlaceholderText("Search title or message…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search notifications")
        self.severity = QComboBox()
        self.severity.setObjectName("notificationSeverityFilter")
        self.severity.addItems(["All", "Success", "Info", "Warning", "Error"])
        self.view_filter = QComboBox()
        self.view_filter.setObjectName("notificationViewFilter")
        self.view_filter.addItem("All notifications", "all")
        self.view_filter.addItem("Unread only", "unread")
        filter_layout.addWidget(self.search, 1)
        filter_layout.addWidget(self.severity)
        filter_layout.addWidget(self.view_filter)
        root.addWidget(filters)

        self.feedback = InlineFeedbackBar()
        self.feedback.setObjectName("notificationFeedback")
        root.addWidget(self.feedback)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("notificationContentStack")
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("notificationList")
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setSpacing(6)
        self.list_widget.itemDoubleClicked.connect(self.mark_selected_read)
        self.list_widget.itemSelectionChanged.connect(self.update_action_state)
        self.content_stack.addWidget(self.list_widget)

        self.empty_state = EmptyStateCard(
            "No notifications",
            "Important generation events and recommended actions will appear here.",
            icon_name="notification",
        )
        self.empty_state.setObjectName("notificationEmptyState")
        self.empty_clear_filters_button = self.empty_state.add_action(
            "Clear filters",
            self.clear_filters,
            icon_name="general.clear",
            primary=True,
        )
        empty_host = QWidget()
        empty_layout = QVBoxLayout(empty_host)
        empty_layout.setContentsMargins(12, 20, 12, 20)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_state, 0, Qt.AlignHCenter)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(empty_host)
        root.addWidget(self.content_stack, 1)

        footer = QFrame()
        footer.setObjectName("notificationFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(10, 8, 10, 8)
        actions.setSpacing(8)
        self.mark_read_button = QPushButton("Mark read")
        self.mark_read_button.setIcon(action_icon("general.success"))
        self.open_action_button = QPushButton("Open action")
        self.open_action_button.setObjectName("notificationPrimaryAction")
        self.open_action_button.setIcon(action_icon("open"))
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setIcon(action_icon("general.remove"))
        self.clear_button = QPushButton("Clear all")
        self.clear_button.setIcon(action_icon("general.clear"))
        self.mark_read_button.clicked.connect(self.mark_selected_read)
        self.open_action_button.clicked.connect(self.open_selected_action)
        self.dismiss_button.clicked.connect(self.dismiss_selected)
        self.clear_button.clicked.connect(self.clear_all)
        actions.addWidget(self.mark_read_button)
        actions.addWidget(self.open_action_button)
        actions.addWidget(self.dismiss_button)
        actions.addStretch(1)
        actions.addWidget(self.clear_button)
        root.addWidget(footer)

        self.search.textChanged.connect(self.refresh)
        self.severity.currentTextChanged.connect(self.refresh)
        self.view_filter.currentIndexChanged.connect(self.refresh)
        self._unsubscribe = self.service.subscribe(lambda _record: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        selected_id = self.selected_id()
        query = self.search.text().strip().casefold()
        selected_severity = self.severity.currentText().casefold()
        unread_only = self.view_filter.currentData() == "unread"
        records = self.service.list()
        self._records = {record.notification_id: record for record in records}
        self._filtered_ids = []
        self.list_widget.clear()

        for record in records:
            if selected_severity != "all" and record.severity.casefold() != selected_severity:
                continue
            if unread_only and record.read:
                continue
            haystack = f"{record.title} {record.message}".casefold()
            if query and query not in haystack:
                continue
            self._filtered_ids.append(record.notification_id)
            marker = "●" if not record.read else "○"
            item = QListWidgetItem(f"{marker} {record.title}\n{record.message}")
            item.setData(Qt.UserRole, record.notification_id)
            item.setToolTip(record.created_at)
            card = NotificationCard(record)
            card.action_requested.connect(self._card_action_requested)
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
            if selected_id == record.notification_id:
                self.list_widget.setCurrentItem(item)

        unread = self.service.unread_count()
        self.badge.setText(f"{unread:,} unread")
        self.badge.setProperty("active", unread > 0)
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.mark_all_button.setEnabled(unread > 0)
        self.clear_button.setEnabled(bool(records))

        if self._filtered_ids:
            self.content_stack.setCurrentIndex(0)
            self.feedback.show_message(
                f"Showing {len(self._filtered_ids):,} of {len(records):,} notifications · {unread:,} unread",
                tone="info" if unread else "success",
            )
            self.empty_clear_filters_button.setVisible(False)
        else:
            self.content_stack.setCurrentIndex(1)
            filtered = bool(query or selected_severity != "all" or unread_only)
            self.empty_clear_filters_button.setVisible(filtered)
            if filtered:
                self.empty_state.set_content(
                    "No matching notifications",
                    "Change the search or filters to show more results.",
                    icon_name="search",
                )
                self.feedback.show_message("No notifications match the current filters.", tone="info")
            else:
                self.empty_state.set_content(
                    "No notifications",
                    "Important generation events and recommended actions will appear here.",
                    icon_name="notification",
                )
                self.feedback.show_message("Notification history is empty.", tone="neutral")
        self.update_action_state()

    def selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.UserRole)) if item else None

    def selected_record(self) -> NotificationRecord | None:
        notification_id = self.selected_id()
        return self._records.get(notification_id) if notification_id else None

    def update_action_state(self) -> None:
        record = self.selected_record()
        selected = record is not None
        self.mark_read_button.setEnabled(bool(selected and not record.read))
        self.dismiss_button.setEnabled(selected)
        has_action = bool(record and record.action_payload)
        self.open_action_button.setVisible(has_action)
        self.open_action_button.setEnabled(has_action)
        if has_action and record is not None:
            self.open_action_button.setText(record.action_label or "Open action")

    def mark_selected_read(self, *_args) -> None:
        notification_id = self.selected_id()
        if notification_id:
            self.service.mark_read(notification_id)
            self.refresh()
            self.feedback.show_message("Notification marked as read.", tone="success")

    def mark_all_read(self) -> None:
        unread = [record for record in self.service.list(unread_only=True)]
        for record in unread:
            self.service.mark_read(record.notification_id)
        self.refresh()
        self.feedback.show_message(
            f"Marked {len(unread):,} notification{'s' if len(unread) != 1 else ''} as read.",
            tone="success",
        )

    def dismiss_selected(self) -> None:
        notification_id = self.selected_id()
        if notification_id:
            self.service.dismiss(notification_id)
            self.refresh()
            self.feedback.show_message("Notification dismissed.", tone="success")

    def clear_all(self) -> None:
        count = len(self.service.list())
        if count:
            self.service.clear()
            self.refresh()
            self.feedback.show_message(f"Cleared {count:,} notifications.", tone="success")

    def clear_filters(self) -> None:
        self.search.clear()
        self.severity.setCurrentIndex(0)
        self.view_filter.setCurrentIndex(0)
        self.refresh()

    def open_selected_action(self) -> None:
        record = self.selected_record()
        if record and record.action_payload:
            self._request_action(record.notification_id, record.action_payload)

    def _card_action_requested(self, notification_id: str, payload: str) -> None:
        self._request_action(notification_id, payload)

    def _request_action(self, notification_id: str, payload: str) -> None:
        self.service.mark_read(notification_id)
        self.action_requested.emit(str(payload))
        self.refresh()
        self.feedback.show_message("Notification action opened.", tone="success")

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
