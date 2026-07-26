from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NotificationRecord:
    notification_id: str
    severity: str
    title: str
    message: str
    created_at: str
    read: bool = False
    action_label: str | None = None
    action_payload: str | None = None


@dataclass(frozen=True)
class ActivityEvent:
    event_id: str
    category: str
    title: str
    message: str
    created_at: str
    project_id: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BatchSessionRecord:
    session_id: str
    project_id: int | None
    scope: str
    provider: str
    model: str
    voice: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    skipped_jobs: int
    character_count: int
    report_path: str | None
    output_path: str | None
    result: str
    started_at: str
    finished_at: str | None = None
