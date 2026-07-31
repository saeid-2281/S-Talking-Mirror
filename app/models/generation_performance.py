from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationPerformanceThresholds:
    minimum_baseline_sessions: int = 3
    baseline_window_size: int = 10
    throughput_drop_warning: float = 0.15
    throughput_drop_critical: float = 0.35
    elapsed_increase_warning: float = 0.25
    elapsed_increase_critical: float = 0.60
    completion_drop_warning: float = 2.0
    completion_drop_critical: float = 10.0
    failure_rate_increase_warning: float = 2.0
    failure_rate_increase_critical: float = 10.0
    retry_rate_increase_warning: float = 2.0
    retry_rate_increase_critical: float = 8.0


@dataclass(frozen=True)
class GenerationPerformanceBudget:
    project_id: int | None = None
    enabled: bool = True
    thresholds: GenerationPerformanceThresholds = field(
        default_factory=GenerationPerformanceThresholds
    )
    alert_cooldown_minutes: int = 60
    silence_until: str | None = None
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationAlertDecision:
    session_id: str
    fingerprint: str | None
    state: str
    notify: bool
    reason: str = ""
    created_at: str | None = None


@dataclass(frozen=True)
class GenerationPerformanceBaseline:
    sample_count: int = 0
    session_ids: tuple[str, ...] = ()
    completion_rate: float = 0.0
    failure_rate: float = 0.0
    seconds_per_job: float = 0.0
    files_per_minute: float = 0.0
    characters_per_minute: float = 0.0
    retries_per_100_jobs: float = 0.0


@dataclass(frozen=True)
class GenerationPerformanceAnalysis:
    session_id: str
    health_score: float
    severity: str
    reasons: tuple[str, ...] = ()
    baseline_session_id: str | None = None
    baseline: GenerationPerformanceBaseline = field(default_factory=GenerationPerformanceBaseline)
    deltas: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationPerformanceTrend:
    direction: str = "unknown"
    session_count: int = 0
    recent_average_health: float = 0.0
    previous_average_health: float = 0.0
    health_delta: float = 0.0
    warning_count: int = 0
    critical_count: int = 0
    best_session_id: str | None = None
    worst_session_id: str | None = None
