from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationKnownProblem:
    problem_id: str
    project_id: int | None
    problem_key: str
    title: str
    description: str = ""
    status: str = "investigating"
    severity: str = "critical"
    root_cause_category: str = "unknown"
    workaround: str = ""
    permanent_fix: str = ""
    owner: str | None = None
    fingerprints: tuple[str, ...] = ()
    incident_ids: tuple[str, ...] = ()
    occurrence_count: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    monitoring_until: str | None = None
    created_at: str = ""
    updated_at: str = ""
    closed_at: str | None = None


@dataclass(frozen=True)
class GenerationProblemMatch:
    problem_id: str
    incident_id: str
    score: int
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationProblemSummary:
    total: int = 0
    investigating_count: int = 0
    known_error_count: int = 0
    fix_planned_count: int = 0
    monitoring_count: int = 0
    closed_count: int = 0
    open_occurrences: int = 0
    linked_incidents: int = 0
    unassigned_count: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
