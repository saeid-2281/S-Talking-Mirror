from __future__ import annotations

from collections.abc import Callable

from app.models.product_events import ActivityEvent
from app.repositories.product_event_repository import ProductEventRepository


class ActivityTimelineService:
    """Persistent activity timeline with bounded history and subscriptions."""

    def __init__(self, repository: ProductEventRepository, *, max_history: int = 500) -> None:
        self.repository = repository
        self.max_history = max(50, int(max_history))
        self._listeners: list[Callable[[ActivityEvent], None]] = []

    def subscribe(self, listener: Callable[[ActivityEvent], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener) if listener in self._listeners else None

    def record(self, event: ActivityEvent) -> ActivityEvent:
        self.repository.add_activity(event)
        self.repository.prune_activity(self.max_history)
        for listener in tuple(self._listeners):
            listener(event)
        return event

    def list(self, *, project_id: int | None = None, limit: int | None = None) -> list[ActivityEvent]:
        return self.repository.list_activity(project_id=project_id, limit=limit or self.max_history)

    def clear(self, *, project_id: int | None = None) -> None:
        self.repository.clear_activity(project_id=project_id)
