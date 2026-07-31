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
    elapsed_seconds: float = 0.0
    active_seconds: float = 0.0
    paused_seconds: float = 0.0
    retry_events: int = 0
    files_per_minute: float = 0.0
    characters_per_minute: float = 0.0
    failure_summary: dict[str, object] = field(default_factory=dict)
    monitor_metrics: dict[str, object] = field(default_factory=dict)
    health_score: float = 0.0
    baseline_session_id: str | None = None
    regression_severity: str = "insufficient_data"
    regression_reasons: list[str] = field(default_factory=list)
    baseline_metrics: dict[str, object] = field(default_factory=dict)
    performance_deltas: dict[str, float] = field(default_factory=dict)
    alert_fingerprint: str | None = None
    alert_state: str = "none"
    alert_notification_id: str | None = None
    alert_created_at: str | None = None
    alert_acknowledged_at: str | None = None
    incident_id: str | None = None
    incident_status: str = "none"
