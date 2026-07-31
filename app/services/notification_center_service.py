from __future__ import annotations

from collections.abc import Callable

from app.models.product_events import NotificationRecord
from app.repositories.product_event_repository import ProductEventRepository


class NotificationCenterService:
    """Persistent notification history with lightweight subscriptions."""

    def __init__(self, repository: ProductEventRepository, *, max_history: int = 250) -> None:
        self.repository = repository
        self.max_history = max(25, int(max_history))
        self._listeners: list[Callable[[NotificationRecord], None]] = []

    def subscribe(self, listener: Callable[[NotificationRecord], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def publish(self, record: NotificationRecord) -> NotificationRecord:
        self.repository.add_notification(record)
        self.repository.prune_notifications(self.max_history)
        for listener in tuple(self._listeners):
            listener(record)
        return record

    def list(self, *, unread_only: bool = False, limit: int | None = None) -> list[NotificationRecord]:
        return self.repository.list_notifications(unread_only=unread_only, limit=limit or self.max_history)

    def unread_count(self) -> int:
        return len(self.list(unread_only=True))

    def mark_read(self, notification_id: str) -> None:
        self.repository.mark_notification_read(notification_id)

    def dismiss(self, notification_id: str) -> None:
        self.repository.delete_notification(notification_id)

    def clear(self) -> None:
        self.repository.clear_notifications()
