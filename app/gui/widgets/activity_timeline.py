from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.professional_components import EmptyStateCard, InlineFeedbackBar
from app.models.product_events import ActivityEvent
from app.services.activity_timeline_service import ActivityTimelineService


class ActivityEventCard(QFrame):
    """Compact event card that keeps category, time and message readable."""

    def __init__(self, event: ActivityEvent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("activityEventCard")
        self.setProperty("category", event.category.casefold())
        self.setAccessibleName(event.title)
        self.setAccessibleDescription(event.message)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(7)
        icon = QLabel()
        icon.setObjectName("activityEventIcon")
        icon.setPixmap(action_icon(self._icon_name(event.category), size=16).pixmap(16, 16))
        title = QLabel(event.title)
        title.setObjectName("activityEventTitle")
        title.setWordWrap(True)
        category = QLabel(event.category.title())
        category.setObjectName("activityEventCategory")
        category.setProperty("category", event.category.casefold())
        timestamp = QLabel(event.created_at.replace("T", " ")[:19])
        timestamp.setObjectName("activityEventTimestamp")
        heading.addWidget(icon)
        heading.addWidget(title, 1)
        heading.addWidget(category)
        heading.addWidget(timestamp)

        message = QLabel(event.message or "No additional details")
        message.setObjectName("activityEventMessage")
        message.setWordWrap(True)
        root.addLayout(heading)
        root.addWidget(message)

    @staticmethod
    def _icon_name(category: str) -> str:
        return {
            "project": "project.open",
            "import": "project.add_sources",
            "provider": "provider.accounts",
            "generation": "generation.start",
            "preflight": "generation.preflight",
            "report": "report",
        }.get(category.casefold(), "activity")


class ActivityTimelineWidget(QWidget):
    """Searchable project activity with readable cards and event details."""

    def __init__(self, service: ActivityTimelineService, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setObjectName("activityTimeline")
        self.project_id: int | None = None
        self.visible_events: list[ActivityEvent] = []
        self._events_by_id: dict[str, ActivityEvent] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(7)

        self.header = QFrame()
        self.header.setObjectName("activityTimelineHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(8)
        title_column = QVBoxLayout()
        title_column.setContentsMargins(0, 0, 0, 0)
        title_column.setSpacing(1)
        title = QLabel("Operational activity")
        title.setObjectName("activityTimelineTitle")
        subtitle = QLabel("Review project, provider, generation and report events in one chronological stream.")
        subtitle.setObjectName("activityTimelineSubtitle")
        subtitle.setWordWrap(True)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        self.count_badge = QLabel("0 events")
        self.count_badge.setObjectName("activityTimelineCount")
        header_layout.addLayout(title_column, 1)
        header_layout.addWidget(self.count_badge)
        root.addWidget(self.header)

        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("activityTimelineFilterBar")
        filters = QHBoxLayout(self.filter_bar)
        filters.setContentsMargins(9, 7, 9, 7)
        filters.setSpacing(7)
        self.category = QComboBox()
        self.category.setObjectName("activityCategoryFilter")
        self.category.addItems(["All", "Project", "Import", "Provider", "Generation", "Preflight", "Report"])
        self.search = QLineEdit()
        self.search.setObjectName("activitySearch")
        self.search.setPlaceholderText("Search title or details…")
        self.search.setClearButtonEnabled(True)
        self.copy_button = QPushButton("Copy selected")
        self.copy_button.setObjectName("activityCopyButton")
        self.copy_button.setIcon(action_icon("general.copy"))
        self.copy_visible_button = QPushButton("Copy visible")
        self.copy_visible_button.setObjectName("activityCopyVisibleButton")
        self.copy_visible_button.setIcon(action_icon("general.copy"))
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("activityClearButton")
        self.clear_button.setIcon(action_icon("general.clear"))
        filters.addWidget(self.category)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.copy_button)
        filters.addWidget(self.copy_visible_button)
        filters.addWidget(self.clear_button)
        root.addWidget(self.filter_bar)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("activityTimelineStack")
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("activityTimelineList")
        self.list_widget.setSpacing(5)
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.content_stack.addWidget(self.list_widget)

        self.empty_state = EmptyStateCard(
            "No activity matches this view",
            "Activity appears here after importing sources, running preflight, generating audio or opening reports.",
            icon_name="activity",
        )
        self.empty_state.setObjectName("activityTimelineEmptyState")
        self.empty_state.add_action("Clear filters", self.clear_filters, icon_name="general.clear", primary=True)
        empty_host = QWidget()
        empty_layout = QVBoxLayout(empty_host)
        empty_layout.setContentsMargins(16, 16, 16, 16)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_state, 0, Qt.AlignHCenter)
        empty_layout.addStretch(1)
        self.content_stack.addWidget(empty_host)
        root.addWidget(self.content_stack, 1)

        self.details = QPlainTextEdit()
        self.details.setObjectName("activityTimelineDetails")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(112)
        self.details.setPlaceholderText("Select an event to inspect category, timestamp and metadata.")
        root.addWidget(self.details)

        self.feedback = InlineFeedbackBar()
        self.feedback.setObjectName("activityTimelineFeedback")
        root.addWidget(self.feedback)

        self.search.textChanged.connect(self.refresh)
        self.category.currentTextChanged.connect(self.refresh)
        self.copy_button.clicked.connect(self.copy_selected)
        self.copy_visible_button.clicked.connect(self.copy_visible)
        self.clear_button.clicked.connect(self.clear)
        self.list_widget.itemSelectionChanged.connect(self.update_details)
        self._unsubscribe = self.service.subscribe(lambda _event: self.refresh())
        self.refresh()

    def set_project_id(self, project_id: int | None) -> None:
        self.project_id = project_id
        self.refresh()

    def refresh(self) -> None:
        query = self.search.text().strip().casefold()
        category = self.category.currentText().casefold()
        self.visible_events = []
        self._events_by_id = {}
        selected_id = self.current_event_id()
        self.list_widget.clear()
        for event in self.service.list(project_id=self.project_id):
            if category != "all" and event.category.casefold() != category:
                continue
            haystack = f"{event.title} {event.message} {event.category}".casefold()
            if query and query not in haystack:
                continue
            self.visible_events.append(event)
            self._events_by_id[event.event_id] = event
            timestamp = event.created_at.replace("T", " ")[:19]
            item = QListWidgetItem(f"{timestamp}  {event.title}\n{event.message}")
            item.setData(Qt.UserRole, event.event_id)
            item.setToolTip(event.category)
            card = ActivityEventCard(event)
            item.setSizeHint(card.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, card)
            if selected_id and selected_id == event.event_id:
                item.setSelected(True)
                self.list_widget.setCurrentItem(item)

        count = len(self.visible_events)
        self.count_badge.setText(f"{count:,} event" if count == 1 else f"{count:,} events")
        self.content_stack.setCurrentIndex(0 if count else 1)
        self.copy_button.setEnabled(bool(self.list_widget.currentItem()))
        self.copy_visible_button.setEnabled(bool(count))
        self.clear_button.setEnabled(bool(self.service.list(project_id=self.project_id, limit=1)))
        self.feedback.show_message(
            f"Showing {count:,} event(s)" + (" for the current project" if self.project_id is not None else " across the workspace"),
            tone="info" if count else "neutral",
        )
        self.update_details()

    def current_event_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def selected_event(self) -> ActivityEvent | None:
        event_id = self.current_event_id()
        return self._events_by_id.get(event_id or "")

    def update_details(self) -> None:
        event = self.selected_event()
        self.copy_button.setEnabled(event is not None)
        if event is None:
            self.details.clear()
            return
        metadata = json.dumps(event.metadata, ensure_ascii=False, indent=2, default=str) if event.metadata else "None"
        self.details.setPlainText(
            "\n".join(
                [
                    f"Title: {event.title}",
                    f"Category: {event.category.title()}",
                    f"Timestamp: {event.created_at}",
                    f"Project: {event.project_id if event.project_id is not None else 'Global'}",
                    f"Details: {event.message or '—'}",
                    f"Metadata: {metadata}",
                ]
            )
        )

    def copy_selected(self) -> None:
        event = self.selected_event()
        if event is None:
            self.feedback.show_message("Select an event before copying.", tone="warning")
            return
        QApplication.clipboard().setText(self._event_text(event))
        self.feedback.show_message("Selected event copied to the clipboard.", tone="success")

    def copy_visible(self) -> None:
        if not self.visible_events:
            self.feedback.show_message("There are no visible events to copy.", tone="warning")
            return
        QApplication.clipboard().setText("\n\n".join(self._event_text(event) for event in self.visible_events))
        self.feedback.show_message(f"Copied {len(self.visible_events):,} visible event(s).", tone="success")

    def clear_filters(self) -> None:
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.refresh()

    def clear(self) -> None:
        count = len(self.service.list(project_id=self.project_id))
        self.service.clear(project_id=self.project_id)
        self.refresh()
        self.feedback.show_message(f"Cleared {count:,} activity event(s).", tone="success")

    @staticmethod
    def _event_text(event: ActivityEvent) -> str:
        metadata = json.dumps(event.metadata, ensure_ascii=False, default=str) if event.metadata else "{}"
        return (
            f"{event.created_at} · {event.category.title()} · {event.title}\n"
            f"{event.message}\nMetadata: {metadata}"
        )

    def closeEvent(self, event) -> None:
        self._unsubscribe()
        super().closeEvent(event)
