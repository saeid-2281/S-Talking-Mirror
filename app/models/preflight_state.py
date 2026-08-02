from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.models.generation_planning import BatchGenerationPlan


@dataclass(frozen=True)
class PreflightIssue:
    severity: str
    row: int | None
    filename: str
    message: str
    suggested_action: str
    code: str = ""
    overridable: bool = False
    overridden: bool = False
    override_reason: str = ""


@dataclass(frozen=True)
class PreflightFix:
    row: int
    original_filename: str
    new_filename: str
    reason: str


@dataclass
class PreflightState:
    total_jobs: int = 0
    valid_jobs: int = 0
    blocking_errors: int = 0
    warnings: int = 0
    duplicate_filenames: list[str] = field(default_factory=list)
    duplicate_texts: list[int] = field(default_factory=list)
    empty_texts: list[int] = field(default_factory=list)
    invalid_filenames: list[int] = field(default_factory=list)
    excessively_long_texts: list[int] = field(default_factory=list)
    existing_outputs: list[str] = field(default_factory=list)
    estimated_characters: int = 0
    estimated_files: int = 0
    estimated_duration_seconds: float = 0.0
    estimated_provider_requests: int = 0
    estimated_cost: float | None = None
    generation_plan: BatchGenerationPlan | None = None
    provider_ready: bool = False
    output_directory_ready: bool = False
    can_start: bool = False
    quota_snapshot: dict[str, int | str | None] | None = None
    issues: list[PreflightIssue] = field(default_factory=list)
    report_dir: Path | None = None
    revision: str = ""
    account_fingerprint: str = ""
    catalog_revision: str = ""
    settings_revision: str = ""

    @property
    def status(self) -> str:
        if self.total_jobs and self.estimated_files == 0 and any(issue.code == "no_pending_jobs" for issue in self.issues):
            return "No pending jobs"
        if self.remaining_blocking_errors:
            return "Blocked by errors"
        if self.warnings:
            return "Ready with warnings"
        if self.total_jobs:
            return "Ready"
        return "Not checked"

    @property
    def remaining_blocking_errors(self) -> int:
        return sum(
            1
            for issue in self.issues
            if issue.severity in {"hard_error", "overridable_error", "error"}
            and not (issue.overridable and issue.overridden)
        )

    def override_issue(self, code: str, reason: str = "") -> bool:
        changed = False
        for issue in self.issues:
            if issue.code == code and issue.overridable:
                object.__setattr__(issue, "overridden", True)
                object.__setattr__(issue, "override_reason", reason)
                changed = True
        self.blocking_errors = self.remaining_blocking_errors
        self.can_start = self.remaining_blocking_errors == 0 and self.estimated_files > 0 and self.output_directory_ready and self.provider_ready
        return changed

    def override_all_eligible(self, reason: str = "") -> int:
        count = 0
        for issue in self.issues:
            if issue.overridable and not issue.overridden:
                object.__setattr__(issue, "overridden", True)
                object.__setattr__(issue, "override_reason", reason)
                count += 1
        self.blocking_errors = self.remaining_blocking_errors
        self.can_start = self.remaining_blocking_errors == 0 and self.estimated_files > 0 and self.output_directory_ready and self.provider_ready
        return count
