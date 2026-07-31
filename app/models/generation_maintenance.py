from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationMaintenancePolicy:
    project_id: int | None = None
    enabled: bool = True
    session_retention_days: int = 365
    notification_retention_days: int = 90
    activity_retention_days: int = 180
    snapshot_retention_days: int = 180
    maintenance_run_retention_days: int = 365
    backup_retention_count: int = 10
    run_quick_check_on_startup: bool = True
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationMaintenanceRun:
    run_id: str
    project_id: int | None
    operation: str
    status: str
    started_at: str
    finished_at: str | None = None
    summary: dict[str, object] = field(default_factory=dict)
    artifact_path: str | None = None
    artifact_sha256: str | None = None


@dataclass(frozen=True)
class GenerationRetentionPreview:
    project_id: int | None
    generated_at: str
    cutoffs: dict[str, str] = field(default_factory=dict)
    candidate_counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_candidates(self) -> int:
        return sum(max(0, int(value)) for value in self.candidate_counts.values())


@dataclass(frozen=True)
class GenerationDatabaseHealth:
    database_path: Path
    database_size_bytes: int
    schema_version: int
    expected_schema_version: int
    applied_versions: tuple[int, ...]
    missing_versions: tuple[int, ...]
    quick_check: str
    foreign_key_violations: tuple[dict[str, object], ...] = ()
    table_counts: dict[str, int] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    checked_at: str = ""

    @property
    def ready(self) -> bool:
        return (
            self.schema_version == self.expected_schema_version
            and not self.missing_versions
            and self.quick_check == "ok"
            and not self.foreign_key_violations
            and not self.issues
        )


@dataclass(frozen=True)
class GenerationBackupArtifact:
    path: Path
    sha256: str
    size_bytes: int
    created_at: str
    schema_version: int
    quick_check: str = "ok"


@dataclass(frozen=True)
class GenerationHardeningDashboard:
    policy: GenerationMaintenancePolicy
    health: GenerationDatabaseHealth
    retention: GenerationRetentionPreview
    recent_runs: tuple[GenerationMaintenanceRun, ...] = ()
    backups: tuple[GenerationBackupArtifact, ...] = ()
