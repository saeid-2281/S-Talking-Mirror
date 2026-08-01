from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.models.domain import AppSettings


class ProviderCircuitStatus(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RoutingMode(StrEnum):
    PRIORITY = "priority"
    WEIGHTED = "weighted"
    ADAPTIVE = "adaptive"


class SchedulingMode(StrEnum):
    STATIC = "static"
    ADAPTIVE = "adaptive"


class OrchestrationPreset(StrEnum):
    SAFE = "safe"
    BALANCED = "balanced"
    THROUGHPUT = "throughput"
    DEADLINE = "deadline"


class DeadlineRiskLevel(StrEnum):
    ON_TRACK = "on_track"
    WATCH = "watch"
    AT_RISK = "at_risk"
    MISSED = "missed"
    INSUFFICIENT_DATA = "insufficient_data"


class OrchestrationAttentionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class GenerationOrchestrationPolicy:
    policy_key: str = "global"
    project_id: int | None = None
    enabled: bool = True
    auto_failover: bool = True
    failure_threshold: int = 2
    circuit_cooldown_seconds: int = 300
    max_switches_per_run: int = 2
    sticky_successful_profile: bool = True
    notify_on_circuit_open: bool = True
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationAdaptiveRoutingPolicy:
    policy_key: str = "global"
    project_id: int | None = None
    enabled: bool = False
    mode: RoutingMode = RoutingMode.PRIORITY
    health_weight: float = 0.45
    capacity_weight: float = 0.30
    latency_weight: float = 0.15
    priority_weight: float = 0.10
    minimum_quota_reserve: int = 0
    max_profile_share_percent: int = 70
    sample_window: int = 50
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationSchedulingPolicy:
    policy_key: str = "global"
    project_id: int | None = None
    enabled: bool = False
    mode: SchedulingMode = SchedulingMode.ADAPTIVE
    minimum_concurrency: int = 1
    initial_concurrency: int = 2
    maximum_concurrency: int = 4
    per_profile_concurrency: int = 2
    success_window: int = 5
    error_window: int = 5
    increase_step: int = 1
    decrease_factor: float = 0.5
    rate_limit_cooldown_seconds: int = 30
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationDeadlinePolicy:
    policy_key: str = "global"
    project_id: int | None = None
    enabled: bool = False
    target_completion_minutes: int = 60
    warning_slack_minutes: int = 15
    allow_concurrency_boost: bool = True
    maximum_deadline_concurrency: int = 8
    fallback_characters_per_minute: int = 1200
    safety_margin_percent: int = 15
    persist_forecasts: bool = True
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationQueueForecast:
    forecast_id: str
    project_id: int | None
    provider: str
    job_count: int
    total_characters: int
    current_concurrency: int
    recommended_concurrency: int
    characters_per_minute: float
    estimated_duration_seconds: float
    estimated_finish_at: str
    deadline_at: str
    slack_seconds: float
    risk_score: float
    risk_level: DeadlineRiskLevel
    recommendation: str
    source: str
    created_at: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationOrchestrationViewPreferences:
    preference_key: str = "global"
    project_id: int | None = None
    selected_tab: int = 0
    auto_refresh: bool = False
    refresh_interval_seconds: int = 10
    table_density: str = "comfortable"
    search_text: str = ""
    status_filter: str = "all"
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationOrchestrationSavedView:
    view_id: str
    project_id: int | None
    name: str
    selected_tab: int = 0
    table_density: str = "comfortable"
    search_text: str = ""
    status_filter: str = "all"
    is_default: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationOrchestrationAttentionItem:
    attention_id: str
    project_id: int | None
    severity: OrchestrationAttentionSeverity
    category: str
    provider: str
    profile_id: str | None
    profile_name: str
    title: str
    detail: str
    recommendation: str
    action_type: str
    target_key: str
    updated_at: str


@dataclass(frozen=True)
class GenerationOrchestrationOperatorAction:
    action_id: str
    project_id: int | None
    action_type: str
    target_type: str
    target_count: int
    summary: str
    created_at: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationOrchestrationDashboardSummary:
    healthy_profiles: int = 0
    degraded_profiles: int = 0
    open_circuits: int = 0
    half_open_circuits: int = 0
    current_concurrency: int = 1
    rate_limited_profiles: int = 0
    provider_events: int = 0
    failover_switches: int = 0
    latest_deadline_risk: DeadlineRiskLevel = DeadlineRiskLevel.INSUFFICIENT_DATA
    latest_deadline_slack_seconds: float | None = None
    recommended_concurrency: int = 1
    severity: str = "neutral"
    recommendation: str = "No orchestration telemetry is available yet."


@dataclass(frozen=True)
class ProviderThrottleSnapshot:
    throttle_key: str
    project_id: int | None
    provider: str
    profile_id: str | None
    profile_name: str
    current_concurrency: int = 1
    recent_rate_limits: int = 0
    cooldown_until: str | None = None
    last_rate_limit_at: str | None = None
    last_recovered_at: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationSchedulerEvent:
    event_id: str
    project_id: int | None
    provider: str
    profile_id: str | None
    profile_name: str
    event_type: str
    from_concurrency: int
    to_concurrency: int
    pending_jobs: int
    active_jobs: int
    reason: str
    created_at: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderCircuitSnapshot:
    state_key: str
    project_id: int | None
    provider: str
    profile_id: str | None
    profile_name: str
    status: ProviderCircuitStatus = ProviderCircuitStatus.CLOSED
    consecutive_failures: int = 0
    opened_at: str | None = None
    retry_after: str | None = None
    last_failure_category: str | None = None
    last_failure_code: str | None = None
    last_failure_at: str | None = None
    last_success_at: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class ProviderRoutingMetric:
    metric_key: str
    project_id: int | None
    provider: str
    profile_id: str | None
    profile_name: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_seconds: float = 0.0
    total_characters: int = 0
    ewma_latency_seconds: float | None = None
    health_score: float = 85.0
    last_selected_at: str | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    updated_at: str = ""

    @property
    def success_rate(self) -> float:
        if self.attempts <= 0:
            return 0.85
        return max(0.0, min(1.0, self.successes / self.attempts))


@dataclass(frozen=True)
class ProviderExecutionCandidate:
    candidate_id: str
    provider: str
    profile_id: str | None
    profile_name: str
    settings: AppSettings
    priority: int = 100
    circuit_status: ProviderCircuitStatus = ProviderCircuitStatus.CLOSED
    consecutive_failures: int = 0
    retry_after: str | None = None
    remaining_characters: int | None = None
    character_limit: int | None = None
    capacity_ratio: float | None = None
    historical_success_rate: float | None = None
    ewma_latency_seconds: float | None = None
    routing_score: float = 0.0
    routing_weight: int = 1


@dataclass(frozen=True)
class GenerationExecutionPlan:
    project_id: int | None
    provider: str
    mode: str
    enabled: bool
    max_switches: int
    failure_threshold: int
    circuit_cooldown_seconds: int
    sticky_successful_profile: bool
    candidates: tuple[ProviderExecutionCandidate, ...] = ()
    excluded: tuple[dict[str, str], ...] = ()
    blocked_reason: str | None = None
    routing_enabled: bool = False
    routing_mode: RoutingMode = RoutingMode.PRIORITY
    max_profile_share_percent: int = 100
    routing_sequence: tuple[str, ...] = ()
    predicted_distribution: tuple[dict[str, object], ...] = ()
    scheduling_enabled: bool = False
    scheduling_mode: SchedulingMode = SchedulingMode.STATIC
    minimum_concurrency: int = 1
    initial_concurrency: int = 1
    maximum_concurrency: int = 1
    per_profile_concurrency: int = 1
    success_window: int = 5
    error_window: int = 5
    increase_step: int = 1
    decrease_factor: float = 0.5
    rate_limit_cooldown_seconds: int = 30
    deadline_enabled: bool = False
    deadline_at: str | None = None
    deadline_risk_level: DeadlineRiskLevel = DeadlineRiskLevel.INSUFFICIENT_DATA
    deadline_risk_score: float = 0.0
    deadline_recommended_concurrency: int = 1
    deadline_estimated_finish_at: str | None = None
    deadline_recommendation: str = ""
    queue_forecast_id: str | None = None

    @property
    def primary(self) -> ProviderExecutionCandidate | None:
        return self.candidates[0] if self.candidates else None

    @property
    def backup_count(self) -> int:
        return max(0, len(self.candidates) - 1)


@dataclass(frozen=True)
class GenerationFailoverEvent:
    event_id: str
    project_id: int | None
    job_row_number: int | None
    filename: str
    provider: str
    from_profile_id: str | None
    from_profile_name: str
    to_profile_id: str | None
    to_profile_name: str | None
    failure_category: str
    error_code: str
    outcome: str
    switch_number: int
    consecutive_failures: int
    circuit_opened: bool
    created_at: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationRoutingDecision:
    decision_id: str
    project_id: int | None
    job_row_number: int | None
    filename: str
    provider: str
    profile_id: str | None
    profile_name: str
    routing_mode: RoutingMode
    routing_score: float
    routing_weight: int
    estimated_characters: int
    reason: str
    created_at: str
    metadata: dict[str, object] = field(default_factory=dict)
