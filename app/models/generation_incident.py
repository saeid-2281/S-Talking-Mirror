from __future__ import annotations

from dataclasses import dataclass, field

from app.models.generation_automation import GenerationAutomationAction


@dataclass(frozen=True)
class GenerationIncident:
    incident_id: str
    project_id: int | None
    alert_fingerprint: str
    severity: str
    status: str
    title: str
    summary: str
    first_session_id: str
    latest_session_id: str
    occurrence_count: int
    session_ids: tuple[str, ...] = ()
    created_at: str = ""
    updated_at: str = ""
    acknowledged_at: str | None = None
    resolved_at: str | None = None
    resolution_note: str | None = None
    assigned_to: str | None = None
    priority: str = "p1"
    response_due_at: str | None = None
    resolution_due_at: str | None = None
    sla_state: str = "not_configured"
    escalation_level: int = 0
    escalated_at: str | None = None
    last_sla_notification_level: int = 0
    problem_id: str | None = None
    problem_status: str = "none"


@dataclass(frozen=True)
class GenerationIncidentSummary:
    total: int = 0
    open_count: int = 0
    acknowledged_count: int = 0
    resolved_count: int = 0
    dismissed_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    total_occurrences: int = 0
    unassigned_count: int = 0
    response_overdue_count: int = 0
    resolution_overdue_count: int = 0
    escalated_count: int = 0
    by_project: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationIncidentSlaPolicy:
    project_id: int | None = None
    enabled: bool = True
    critical_response_minutes: int = 15
    critical_resolution_minutes: int = 240
    warning_response_minutes: int = 60
    warning_resolution_minutes: int = 1440
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationIncidentUpdate:
    update_id: str
    incident_id: str
    kind: str
    message: str
    created_at: str
    actor: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationIncidentRunbook:
    runbook_id: str
    project_id: int | None
    name: str
    description: str = ""
    severity_filter: str = "any"
    fingerprint_pattern: str = ""
    steps: tuple[str, ...] = ()
    enabled: bool = True
    automation_enabled: bool = False
    automation_trigger: str = "manual"
    automation_actions: tuple[GenerationAutomationAction, ...] = ()
    dry_run_only: bool = True
    max_auto_runs: int = 1
    cooldown_minutes: int = 60
    rollback_instructions: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationRemediationStep:
    position: int
    title: str
    status: str = "pending"
    note: str = ""
    actor: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True)
class GenerationIncidentRemediation:
    remediation_id: str
    incident_id: str
    runbook_id: str | None
    runbook_name: str
    status: str
    steps: tuple[GenerationRemediationStep, ...] = ()
    started_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    actor: str | None = None

    @property
    def completed_steps(self) -> int:
        return sum(step.status in {"completed", "skipped"} for step in self.steps)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def progress_percent(self) -> int:
        if not self.steps:
            return 0
        return round((self.completed_steps / len(self.steps)) * 100)


@dataclass(frozen=True)
class GenerationIncidentReview:
    review_id: str
    incident_id: str
    status: str = "draft"
    impact_summary: str = ""
    root_cause_category: str = "unknown"
    root_cause: str = ""
    contributing_factors: tuple[str, ...] = ()
    detection_gap: str = ""
    resolution_summary: str = ""
    lessons_learned: str = ""
    reviewer: str | None = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None


@dataclass(frozen=True)
class GenerationIncidentActionItem:
    action_id: str
    review_id: str
    incident_id: str
    title: str
    status: str = "open"
    priority: str = "p2"
    owner: str | None = None
    due_at: str | None = None
    note: str = ""
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    overdue_notified_at: str | None = None
    problem_id: str | None = None
