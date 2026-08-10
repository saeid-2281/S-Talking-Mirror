from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.domain import AppSettings, JobStatus, TTSJob
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.repositories.job_repository import JobRepository
from app.models.retry_policy import FailureCategory, RetryBatchResult
from app.services.failure_analysis_service import FailureAnalysisService, RetryPolicyService

QUEUE_FILTERS = ("all", "pending", "running", "completed", "failed", "skipped")


@dataclass(frozen=True)
class QueueMetrics:
    total: int
    processed: int
    pending: int
    running: int
    completed: int
    failed: int
    skipped: int
    eta_seconds: float


class QueueService:
    """Owns queue state rules that should not live in MainWindow."""

    def __init__(self, repository: JobRepository | None = None, fallback_seconds_per_job: float = 3.0) -> None:
        self.repository = repository
        self.fallback_seconds_per_job = fallback_seconds_per_job
        self.failure_analysis = FailureAnalysisService()
        self.retry_policy = RetryPolicyService()
        self.last_retry_result = RetryBatchResult()

    def sync_project_jobs(
        self,
        project_id: int | None,
        jobs: list[TTSJob],
        *,
        output_dir: Path | None = None,
        settings: AppSettings | None = None,
    ) -> list[TTSJob]:
        for index, job in enumerate(jobs, 1):
            if job.original_order is None:
                job.original_order = index
            if settings and job.row_number in settings.job_pronunciation_overrides:
                job.pronunciation_override = settings.job_pronunciation_overrides[job.row_number]
        if project_id is None or self.repository is None:
            return jobs
        extension = self.extension_for(settings) if settings else ".wav"
        self.repository.upsert_jobs(project_id, jobs, output_dir=output_dir, extension=extension)
        return self.repository.restore_jobs(project_id, output_dir=output_dir)

    def restore_project_jobs(
        self,
        project_id: int | None,
        *,
        output_dir: Path | None = None,
    ) -> list[TTSJob]:
        if project_id is None or self.repository is None:
            return []
        return self.repository.restore_jobs(project_id, output_dir=output_dir)

    def visible_jobs(self, jobs: list[TTSJob], status_filter: str) -> list[TTSJob]:
        normalized = self.normalize_filter(status_filter)
        if normalized == "all":
            return list(jobs)
        return [job for job in jobs if job.status.value == normalized]

    def pending_jobs(self, jobs: list[TTSJob]) -> list[TTSJob]:
        return [job for job in jobs if job.status == JobStatus.PENDING]

    def retry_failed(self, project_id: int | None, jobs: list[TTSJob]) -> int:
        """Compatibility reset: clear failed state without applying Phase 4 policy."""
        return self.reset_jobs(project_id, jobs, [job for job in jobs if job.status == JobStatus.FAILED])

    def retry_selected(self, project_id: int | None, jobs: list[TTSJob], selected_jobs: list[TTSJob]) -> int:
        retryable = [job for job in selected_jobs if job.status == JobStatus.FAILED]
        return self.reset_jobs(project_id, jobs, retryable)

    def retry_jobs(
        self,
        project_id: int | None,
        jobs: list[TTSJob],
        selected_jobs: list[TTSJob],
        *,
        max_retries: int,
        transient_only: bool = False,
        category: FailureCategory | str | None = None,
        manual_override: bool = False,
    ) -> RetryBatchResult:
        selected_rows = {job.row_number for job in selected_jobs}
        actual = [job for job in jobs if job.row_number in selected_rows]
        for job in actual:
            if job.status == JobStatus.FAILED and (
                job.failure_category is None
                or job.retryable is None
                or not job.error_fingerprint
            ):
                analysis = self.failure_analysis.analyze(job.error)
                job.failure_category = analysis.category
                job.error_code = analysis.error_code
                job.error_fingerprint = analysis.fingerprint
                job.retryable = analysis.retryable
        result = self.retry_policy.prepare(
            actual,
            max_retries=max_retries,
            transient_only=transient_only,
            category=category,
            manual_override=manual_override,
        )
        scheduled = [job for job in actual if job.row_number in result.row_numbers]
        if project_id is not None and self.repository is not None:
            self.repository.update_retry_state(project_id, scheduled)
        self.last_retry_result = result
        return result

    def failure_summary(self, jobs: list[TTSJob]) -> dict[str, object]:
        return self.failure_analysis.summary(jobs)

    def reset_jobs(self, project_id: int | None, jobs: list[TTSJob], selected_jobs: list[TTSJob]) -> int:
        row_numbers = [job.row_number for job in selected_jobs if job.status != JobStatus.RUNNING]
        for job in jobs:
            if job.row_number in row_numbers:
                job.status = JobStatus.PENDING
                job.error = None
                job.duration_seconds = 0.0
                job.retry_count = 0
                job.failure_category = None
                job.error_code = None
                job.error_fingerprint = None
                job.retryable = None
                job.retry_exhausted = False
                job.next_retry_at = None
                job.retry_history = []
                job.generated_output_path = None
        if project_id is not None and self.repository is not None:
            self.repository.reset_rows(project_id, row_numbers)
        return len(row_numbers)

    def skip_selected(self, project_id: int | None, jobs: list[TTSJob], selected_jobs: list[TTSJob]) -> int:
        row_numbers = [job.row_number for job in selected_jobs if job.status != JobStatus.COMPLETED]
        for job in jobs:
            if job.row_number in row_numbers:
                job.status = JobStatus.SKIPPED
                job.error = None
        if project_id is not None and self.repository is not None:
            self.repository.skip_rows(project_id, row_numbers)
        return len(row_numbers)

    def clear_completed(
        self,
        project_id: int | None,
        jobs: list[TTSJob],
        *,
        status_filter: str = "all",
    ) -> int:
        visible = self.visible_jobs(jobs, status_filter)
        completed_rows = [job.row_number for job in visible if job.status == JobStatus.COMPLETED]
        jobs[:] = [job for job in jobs if job.row_number not in completed_rows]
        if project_id is not None and self.repository is not None:
            self.repository.delete_completed(project_id, completed_rows)
        return len(completed_rows)

    def output_path_for(
        self,
        job: TTSJob,
        output_dir: Path,
        settings: AppSettings,
    ) -> Path:
        if job.generated_output_path:
            return Path(job.generated_output_path)
        return job.output_path(output_dir, self.extension_for(settings))

    def metrics(
        self,
        jobs: list[TTSJob],
        *,
        project_id: int | None = None,
    ) -> QueueMetrics:
        total = len(jobs)
        pending = sum(1 for job in jobs if job.status == JobStatus.PENDING)
        running = sum(1 for job in jobs if job.status == JobStatus.RUNNING)
        completed = sum(1 for job in jobs if job.status == JobStatus.COMPLETED)
        failed = sum(1 for job in jobs if job.status == JobStatus.FAILED)
        skipped = sum(1 for job in jobs if job.status == JobStatus.SKIPPED)
        average = self._average_duration(project_id)
        eta_jobs = pending + running
        return QueueMetrics(
            total=total,
            processed=completed + failed + skipped,
            pending=pending,
            running=running,
            completed=completed,
            failed=failed,
            skipped=skipped,
            eta_seconds=eta_jobs * average,
        )

    def mark_running(self, project_id: int | None, job: TTSJob) -> None:
        job.status = JobStatus.RUNNING
        job.error = None
        job.retry_count += 1
        if project_id is not None and self.repository is not None:
            self.repository.mark_running(project_id, job)

    def mark_result(
        self,
        project_id: int | None,
        job: TTSJob,
        status: JobStatus,
        *,
        duration_seconds: float = 0.0,
        error: str | None = None,
        output_path: Path | str | None = None,
    ) -> None:
        job.status = status
        job.error = error
        job.duration_seconds = duration_seconds
        if output_path:
            job.generated_output_path = str(output_path)
        if project_id is not None and self.repository is not None:
            self.repository.mark_result(
                project_id,
                job,
                status,
                duration_seconds=duration_seconds,
                error=error,
                output_path=output_path,
            )

    def _average_duration(self, project_id: int | None) -> float:
        if self.repository is not None:
            average = self.repository.average_completed_duration(project_id)
            if average:
                return average
        return self.fallback_seconds_per_job

    @staticmethod
    def normalize_filter(status_filter: str) -> str:
        normalized = status_filter.strip().lower()
        return normalized if normalized in QUEUE_FILTERS else "all"

    @staticmethod
    def extension_for(settings: AppSettings | None) -> str:
        if settings is None:
            return ".wav"
        return DEFAULT_PROVIDER_REGISTRY.output_extension(settings.provider, settings.file_extension)
