from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationHistorySummary:
    session_count: int = 0
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    skipped_jobs: int = 0
    total_characters: int = 0
    retry_events: int = 0
    elapsed_seconds: float = 0.0
    active_seconds: float = 0.0
    completion_rate: float = 0.0
    average_elapsed_seconds: float = 0.0
    average_files_per_minute: float = 0.0
    average_characters_per_minute: float = 0.0
    average_health_score: float = 0.0
    warning_regressions: int = 0
    critical_regressions: int = 0
    insufficient_baselines: int = 0
    providers: dict[str, int] = field(default_factory=dict)
    results: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationSessionComparison:
    baseline_session_id: str
    candidate_session_id: str
    completion_rate_delta: float = 0.0
    elapsed_seconds_delta: float = 0.0
    files_per_minute_delta: float = 0.0
    characters_per_minute_delta: float = 0.0
    retry_events_delta: int = 0
    failed_jobs_delta: int = 0
    health_score_delta: float = 0.0
