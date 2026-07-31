from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationSloPolicy:
    project_id: int | None = None
    enabled: bool = True
    window_days: int = 30
    minimum_sessions: int = 3
    target_job_success_rate: float = 99.0
    max_retry_rate: float = 5.0
    max_mtta_minutes: float = 60.0
    max_mttr_minutes: float = 480.0
    max_incident_recurrence_rate: float = 20.0
    min_runbook_success_rate: float = 80.0
    min_corrective_action_completion_rate: float = 90.0
    warning_burn_rate: float = 1.0
    critical_burn_rate: float = 2.0
    alert_cooldown_minutes: int = 240
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationProviderReliability:
    provider: str
    session_count: int = 0
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    retry_events: int = 0
    job_success_rate: float = 0.0
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    average_files_per_minute: float = 0.0
    average_health_score: float = 0.0


@dataclass(frozen=True)
class GenerationReliabilitySnapshot:
    snapshot_id: str
    project_id: int | None
    period_start: str
    period_end: str
    created_at: str
    state: str = "insufficient_data"
    trend: str = "unknown"
    session_count: int = 0
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    retry_events: int = 0
    job_success_rate: float = 0.0
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    average_files_per_minute: float = 0.0
    average_health_score: float = 0.0
    incident_count: int = 0
    recurring_incident_count: int = 0
    critical_incident_count: int = 0
    acknowledged_incident_count: int = 0
    resolved_incident_count: int = 0
    mtta_minutes: float = 0.0
    mttr_minutes: float = 0.0
    runbook_execution_count: int = 0
    runbook_success_rate: float = 0.0
    corrective_action_count: int = 0
    corrective_action_completion_rate: float = 0.0
    error_budget_allowed_jobs: float = 0.0
    error_budget_consumed_jobs: float = 0.0
    error_budget_remaining_percent: float = 100.0
    burn_rate: float = 0.0
    reasons: tuple[str, ...] = ()
    provider_metrics: tuple[GenerationProviderReliability, ...] = ()
    alert_fingerprint: str | None = None
    alert_notification_id: str | None = None


@dataclass(frozen=True)
class GenerationReliabilityDashboard:
    policy: GenerationSloPolicy
    snapshot: GenerationReliabilitySnapshot
    previous_snapshot: GenerationReliabilitySnapshot | None = None
    history: tuple[GenerationReliabilitySnapshot, ...] = ()
    target_status: dict[str, str] = field(default_factory=dict)
