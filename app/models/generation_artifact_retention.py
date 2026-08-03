from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationArtifactRetentionPolicy:
    """Retention policy for immutable generation governance artifacts."""

    project_name: str = ""
    enabled: bool = True
    launch_receipt_days: int = 365
    execution_run_days: int = 365
    recovery_receipt_days: int = 180
    approval_record_days: int = 365
    budget_record_days: int = 180
    orphan_grace_days: int = 14
    archive_before_delete: bool = True
    keep_integrity_issues: bool = True
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationArtifactRetentionCandidate:
    """One file-backed or index-backed artifact considered for retention."""

    candidate_id: str
    project_name: str
    artifact_type: str
    identifier: str
    path: Path
    created_at: str
    age_days: int
    size_bytes: int
    action: str
    reason: str
    integrity_status: str = "unknown"
    related_paths: tuple[Path, ...] = field(default_factory=tuple)
    virtual_record: bool = False
    protected: bool = False


@dataclass(frozen=True)
class GenerationArtifactRetentionPreview:
    """Immutable dry-run result used to authorize a cleanup operation."""

    preview_id: str
    generated_at: str
    project_name: str
    policy: GenerationArtifactRetentionPolicy
    candidates: tuple[GenerationArtifactRetentionCandidate, ...] = field(default_factory=tuple)
    total_bytes: int = 0
    archive_count: int = 0
    delete_count: int = 0
    review_count: int = 0
    orphan_count: int = 0
    integrity_issue_count: int = 0

    @property
    def actionable_count(self) -> int:
        return self.archive_count + self.delete_count

    @property
    def protected_count(self) -> int:
        return sum(item.protected for item in self.candidates)


@dataclass(frozen=True)
class GenerationArtifactRetentionRun:
    """Auditable result of one dry-run or applied artifact-retention operation."""

    run_id: str
    preview_id: str
    project_name: str
    status: str
    dry_run: bool
    started_at: str
    finished_at: str
    archive_path: Path | None = None
    manifest_path: Path | None = None
    archive_sha256: str = ""
    candidate_count: int = 0
    archived_count: int = 0
    deleted_count: int = 0
    skipped_count: int = 0
    reclaimed_bytes: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)
