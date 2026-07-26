from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord
from app.repositories.product_event_repository import ProductEventRepository


class ProductActivityService:
    def __init__(self, repository: ProductEventRepository) -> None:
        self.repository = repository

    def notify(self, severity: str, title: str, message: str, *, action_label: str | None = None, action_payload: str | None = None) -> NotificationRecord:
        record = NotificationRecord(
            notification_id=uuid.uuid4().hex,
            severity=severity,
            title=title,
            message=message,
            created_at=self._now(),
            action_label=action_label,
            action_payload=action_payload,
        )
        self.repository.add_notification(record)
        return record

    def activity(self, category: str, title: str, message: str, *, project_id: int | None = None, metadata: dict[str, object] | None = None) -> ActivityEvent:
        event = ActivityEvent(
            event_id=uuid.uuid4().hex,
            project_id=project_id,
            category=category,
            title=title,
            message=message,
            created_at=self._now(),
            metadata=metadata or {},
        )
        self.repository.add_activity(event)
        return event

    def record_batch(self, record: BatchSessionRecord) -> None:
        self.repository.add_batch_session(record)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
