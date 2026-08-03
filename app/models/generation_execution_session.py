from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationExecutionJob:
    """Secret-free snapshot of one job inside an execution session."""

    row_number: int
    filename: str
    source_id: str = ""
    source_name: str = ""
    source_sheet: str = ""
    source_row: int | None = None
    character_count: int = 0
    status: str = "pending"
    retry_count: int = 0
    duration_seconds: float = 0.0
    output_path: str = ""
    error: str = ""
    error_code: str = ""
    error_fingerprint: str = ""
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""


@dataclass(frozen=True)
class GenerationExecutionSession:
    """Persisted identity and lifecycle record for one real generation run."""

    path: Path
    markdown_path: Path
    schema_version: int = 1
    run_id: str = ""
    status: str = "running"
    project_name: str = ""
    project_id: int | None = None
    project_key: str = ""
    launch_receipt_id: str = ""
    launch_receipt_path: str = ""
    launch_fingerprint: str = ""
    decision_trace_id: str = ""
    guard_approval_id: str = ""
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""
    generation_scope: str = ""
    execution_order: str = ""
    output_directory: str = ""
    report_path: str = ""
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    total_jobs: int = 0
    pending_jobs: int = 0
    running_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    skipped_jobs: int = 0
    total_characters: int = 0
    processed_characters: int = 0
    retry_events: int = 0
    elapsed_seconds: float = 0.0
    jobs: tuple[GenerationExecutionJob, ...] = field(default_factory=tuple)
    integrity_status: str = "verified"
    integrity_message: str = "Execution session integrity verified."

    @property
    def processed_jobs(self) -> int:
        return self.completed_jobs + self.failed_jobs + self.skipped_jobs

    @property
    def progress_percent(self) -> float:
        if self.total_jobs <= 0:
            return 0.0
        return min(100.0, max(0.0, self.processed_jobs / self.total_jobs * 100.0))

    @property
    def active(self) -> bool:
        return self.status in {"starting", "running", "paused", "stopping"}

    @property
    def requires_attention(self) -> bool:
        return self.integrity_status in {"mismatch", "unreadable"} or self.status in {
            "failed",
            "partial",
            "cancelled",
        }


@dataclass(frozen=True)
class GenerationExecutionSessionSummary:
    total_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    partial_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    integrity_issue_count: int = 0
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    skipped_jobs: int = 0
