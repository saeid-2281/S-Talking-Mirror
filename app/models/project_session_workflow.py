from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectRunSummary:
    session_id: str
    project_id: int | None
    result: str
    provider: str
    model: str
    voice: str
    completed_jobs: int
    failed_jobs: int
    skipped_jobs: int
    total_jobs: int
    started_at: str
    finished_at: str | None
    elapsed_seconds: float
    output_path: str | None
    report_path: str | None


@dataclass(frozen=True)
class ProjectContinuationSummary:
    project_id: int
    name: str
    project_file: str | None
    csv_path: str | None
    output_path: str | None
    provider: str
    last_opened_at: str
    project_file_exists: bool
    source_exists: bool
    output_exists: bool
    saved_jobs: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int
    skipped_jobs: int
    latest_run: ProjectRunSummary | None = None
    latest_audio_path: str | None = None

    @property
    def can_continue(self) -> bool:
        return bool(self.project_file and self.project_file_exists)

    @property
    def queue_summary(self) -> str:
        if not self.saved_jobs:
            return "No saved queue"
        return (
            f"{self.saved_jobs:,} jobs · {self.pending_jobs:,} pending · "
            f"{self.failed_jobs:,} failed"
        )


@dataclass(frozen=True)
class SessionContinuationSummary:
    auto_restore_enabled: bool
    project_path: str | None
    project_name: str | None
    project_id: int | None
    project_exists: bool
    queue_filter: str
    selected_row: int | None

    @property
    def can_continue(self) -> bool:
        return bool(self.project_path and self.project_exists)


@dataclass(frozen=True)
class ProjectSessionWorkflowSnapshot:
    session: SessionContinuationSummary
    projects: tuple[ProjectContinuationSummary, ...]
