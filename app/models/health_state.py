from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class HealthCheckState:
    """Latest automated development-check outcome."""

    available: bool = False
    success: bool = False
    tests_passed: int = 0
    compile_passed: bool = False
    ruff_passed: bool = False
    summary: str = "No development check has been run yet."
    artifact_directory: Path | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class HealthScoreItem:
    """One scored health category."""

    name: str
    points: int
    maximum: int
    status: str
    detail: str


@dataclass(frozen=True)
class HealthState:
    """One snapshot of application, repository, and project health."""

    score: int
    level: str
    label: str
    branch: str
    git_clean: bool
    project_name: str
    provider: str
    queue_total: int
    queue_completed: int
    queue_failed: int
    latest_report: Path | None
    latest_diagnostics: Path | None
    check: HealthCheckState
    breakdown: tuple[HealthScoreItem, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    runtime_domain: str = "source"
    development_available: bool = True
    packaged_runtime: bool = False

    @property
    def icon(self) -> str:
        return {"healthy": "●", "warning": "●", "error": "●"}.get(self.level, "●")
