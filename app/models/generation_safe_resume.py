from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationResumeCandidate:
    """One current queue job matched to a parent execution output."""

    row_number: int
    filename: str
    parent_disposition: str
    parent_job_status: str
    expected_path: str = ""
    actual_path: str = ""
    output_exists: bool = False
    parent_character_count: int = 0
    current_character_count: int = 0
    selected: bool = False
    current_job_found: bool = True
    reason: str = ""

    @property
    def unresolved(self) -> bool:
        return self.parent_disposition in {"failed", "missing", "incomplete"}


@dataclass(frozen=True)
class GenerationResumePreview:
    """Immutable safe-resume evaluation before a recovery receipt is persisted."""

    project_name: str
    parent_run_id: str
    parent_execution_receipt_id: str
    parent_execution_receipt_path: str
    scope: str
    provider: str
    model_id: str
    voice_id: str
    output_directory: str
    skip_existing: bool = True
    overwrite_existing: bool = False
    selected_rows: tuple[int, ...] = field(default_factory=tuple)
    candidates: tuple[GenerationResumeCandidate, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return bool(self.selected_rows) and not self.blockers

    @property
    def selected_count(self) -> int:
        return len(self.selected_rows)

    @property
    def matched_count(self) -> int:
        return sum(item.current_job_found for item in self.candidates)


@dataclass(frozen=True)
class GenerationResumeReceipt:
    """Integrity-protected record of a planned or started recovery run."""

    path: Path
    markdown_path: Path
    schema_version: int = 1
    resume_id: str = ""
    status: str = "planned"
    created_at: str = ""
    updated_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    cancelled_at: str = ""
    project_name: str = ""
    parent_run_id: str = ""
    parent_execution_receipt_id: str = ""
    parent_execution_receipt_path: str = ""
    new_run_id: str = ""
    result: str = ""
    execution_receipt_id: str = ""
    execution_receipt_path: str = ""
    scope: str = "unresolved"
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""
    output_directory: str = ""
    skip_existing: bool = True
    overwrite_existing: bool = False
    selected_rows: tuple[int, ...] = field(default_factory=tuple)
    candidates: tuple[GenerationResumeCandidate, ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)
    integrity_status: str = "verified"
    integrity_message: str = "Resume receipt integrity verified."

    @property
    def allowed(self) -> bool:
        return bool(self.selected_rows) and not self.blockers

    @property
    def selected_count(self) -> int:
        return len(self.selected_rows)

    @property
    def active(self) -> bool:
        return self.status in {"planned", "started"}
