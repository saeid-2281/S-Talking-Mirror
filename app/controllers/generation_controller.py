from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app.gui.worker import GenerationWorker
from app.models.domain import AppSettings, JobStatus, TTSJob
from app.models.generation_scope import GenerationPlan
from app.models.ui_state import GenerationUiState
from app.services.generation_scope_service import GenerationScopeService
from app.repositories.job_repository import JobRepository
from app.services.queue_service import QueueMetrics, QueueService


class GenerationController(QObject):
    """Owns generation worker and thread lifetime."""

    progress = Signal(int, int, str, str, float, int, str)
    log = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: Path, job_repository: JobRepository | None = None) -> None:
        super().__init__()
        self.database_path = database_path
        self.queue_service = QueueService(job_repository)
        self.worker: GenerationWorker | None = None
        self.thread: QThread | None = None
        self._state = GenerationUiState(jobs=[])
        self.current_project_key: str | None = None
        self.current_project_id: int | None = None
        self.status_filter = "all"
        self._active_jobs: list[TTSJob] = []
        self.row_range: tuple[int | None, int | None] = (None, None)
        self.generation_selection: set[int] | None = None
        self.scope_mode = "row_range"
        self.execution_order = "csv"
        self.scope_service = GenerationScopeService()
        self.quota_remaining: int | None = None

    @property
    def is_active(self) -> bool:
        return self.worker is not None

    @property
    def is_paused(self) -> bool:
        return self._state.paused

    @property
    def jobs(self) -> list[TTSJob]:
        return self._state.jobs

    def set_jobs(
        self,
        jobs: list[TTSJob],
        *,
        project_id: int | None = None,
        output_dir: Path | None = None,
        settings: AppSettings | None = None,
    ) -> None:
        self.current_project_id = project_id
        self._state.jobs = self.queue_service.sync_project_jobs(
            project_id,
            jobs,
            output_dir=output_dir,
            settings=settings,
        )

    def clear_jobs(self) -> None:
        self._state.jobs = []
        self._state.status = "idle"
        self.current_project_id = None

    def has_jobs(self) -> bool:
        return bool(self._state.jobs)

    def restore_project_queue(self, project_id: int | None, *, output_dir: Path | None = None) -> list[TTSJob]:
        self.current_project_id = project_id
        self._state.jobs = self.queue_service.restore_project_jobs(project_id, output_dir=output_dir)
        return self._state.jobs

    def visible_jobs(self) -> list[TTSJob]:
        jobs = self.queue_service.visible_jobs(self.range_jobs(), self.status_filter)
        return self.scope_service.order_jobs(jobs, self.scope_service._order(self.execution_order))

    def range_jobs(self) -> list[TTSJob]:
        start, end = self.row_range
        jobs = self._state.jobs
        if start is not None:
            jobs = [job for job in jobs if job.row_number >= start]
        if end is not None:
            jobs = [job for job in jobs if job.row_number <= end]
        return list(jobs)

    def set_row_range(self, start: int | None, end: int | None) -> None:
        if start is not None and end is not None and start > end:
            start, end = end, start
        self.row_range = (start, end)

    def range_summary(self) -> tuple[int | None, int | None, int]:
        start, end = self.row_range
        return start, end, len(self.range_jobs())

    def set_generation_selection(self, row_numbers: list[int] | None) -> None:
        self.generation_selection = set(row_numbers) if row_numbers else None
        if self.generation_selection:
            self.scope_mode = "selected"

    def clear_generation_selection(self) -> None:
        self.generation_selection = None
        if self.scope_mode == "selected":
            self.scope_mode = "row_range"

    def generation_jobs(self) -> list[TTSJob]:
        return list(self.generation_plan().jobs)

    def generation_plan(self, *, quota_remaining: int | None = None) -> GenerationPlan:
        return self.scope_service.build_plan(
            self._state.jobs,
            scope_mode=self.scope_mode,
            execution_order=self.execution_order,
            filtered_jobs=self.visible_jobs(),
            selected_rows=self.generation_selection,
            row_range=self.row_range,
            quota_remaining=self.quota_remaining if quota_remaining is None else quota_remaining,
        )

    def set_quota_remaining(self, quota_remaining: int | None) -> None:
        self.quota_remaining = quota_remaining

    def set_scope_mode(self, scope_mode: str) -> None:
        self.scope_mode = scope_mode or "entire_queue"

    def set_execution_order(self, execution_order: str) -> None:
        self.execution_order = execution_order or "csv"

    def use_visible_order_as_generation_order(self) -> None:
        self.scope_service.use_current_order_as_custom(self.visible_jobs())
        self.execution_order = "custom"

    def move_selected_in_custom_order(self, jobs: list[TTSJob], command: str) -> None:
        self.scope_service.move_custom(self._state.jobs, {job.row_number for job in jobs}, command)
        self.execution_order = "custom"

    def set_filter(self, status_filter: str) -> None:
        self.status_filter = self.queue_service.normalize_filter(status_filter)

    def selected_jobs(self, visible_rows: list[int]) -> list[TTSJob]:
        visible = self.visible_jobs()
        return [visible[row] for row in visible_rows if 0 <= row < len(visible)]

    def retry_failed(self) -> int:
        return self.queue_service.retry_failed(self.current_project_id, self._state.jobs)

    def retry_selected(self, jobs: list[TTSJob]) -> int:
        return self.queue_service.retry_selected(self.current_project_id, self._state.jobs, jobs)

    def skip_selected(self, jobs: list[TTSJob]) -> int:
        return self.queue_service.skip_selected(self.current_project_id, self._state.jobs, jobs)

    def reset_selected(self, jobs: list[TTSJob]) -> int:
        return self.queue_service.reset_jobs(self.current_project_id, self._state.jobs, jobs)

    def clear_completed(self) -> int:
        return self.queue_service.clear_completed(
            self.current_project_id,
            self._state.jobs,
            status_filter=self.status_filter,
        )

    def metrics(self) -> QueueMetrics:
        return self.queue_service.metrics(self.range_jobs(), project_id=self.current_project_id)

    def scoped_metrics(self) -> QueueMetrics:
        return self.queue_service.metrics(self.generation_jobs(), project_id=self.current_project_id)

    def output_path_for(self, job: TTSJob, output_dir: Path, settings: AppSettings) -> Path:
        return self.queue_service.output_path_for(job, output_dir, settings)

    def start(
        self,
        parent: QObject,
        *args: object,
    ) -> bool:
        if len(args) == 4 and isinstance(args[0], list):
            jobs, settings, output_dir, project_key = args
            self.set_jobs(jobs)
        elif len(args) == 3:
            settings, output_dir, project_key = args
        else:
            raise TypeError("start expects settings, output_dir, project_key")

        if not isinstance(settings, AppSettings):
            raise TypeError("settings must be AppSettings")
        output_path = Path(output_dir)
        project_key_value = str(project_key)

        if self.is_active or not self.has_jobs():
            return False
        pending_jobs = self.queue_service.pending_jobs(self.generation_jobs())
        if not pending_jobs:
            return False
        self.thread = QThread(parent)
        self.current_project_key = project_key_value
        self._active_jobs = pending_jobs
        self.worker = GenerationWorker(
            pending_jobs,
            settings,
            output_path,
            self.database_path,
            project_key_value,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.log.connect(self.log)
        self.worker.finished.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self._state.status = "running"
        self.thread.start()
        return True

    def pause(self) -> bool:
        if self.worker is None:
            return False
        self._state.paused = True
        self.worker.pause()
        return True

    def resume(self) -> bool:
        if self.worker is None:
            return False
        self._state.paused = False
        self.worker.resume()
        return True

    def stop(self) -> bool:
        if self.worker is None:
            return False
        self._state.paused = False
        self._state.status = "stopping"
        self.worker.stop()
        return True

    def _finished(self, summary: dict) -> None:
        self.finished.emit(summary)
        self._clear()

    def _failed(self, error: str) -> None:
        self.failed.emit(error)
        self._clear()

    def _clear(self) -> None:
        self.worker = None
        self._active_jobs = []
        self.generation_selection = None
        self._state.paused = False
        self._state.status = "idle"

    def _progress(
        self,
        index: int,
        total: int,
        name: str,
        status: str,
        duration: float,
        retry: int,
        error: str,
    ) -> None:
        active_index = index - 1
        active_job = self._active_jobs[active_index] if 0 <= active_index < len(self._active_jobs) else None
        job_index = self._job_index(active_job) if active_job else -1
        if 0 <= job_index < len(self._state.jobs):
            try:
                job_status = JobStatus(status)
            except ValueError:
                job_status = None
            job = self._state.jobs[job_index]
            if job_status is not None:
                if job_status == JobStatus.RUNNING:
                    self.queue_service.mark_running(self.current_project_id, job)
                else:
                    self.queue_service.mark_result(
                        self.current_project_id,
                        job,
                        job_status,
                        duration_seconds=duration,
                        error=error or None,
                        output_path=name if job_status in {JobStatus.COMPLETED, JobStatus.SKIPPED} else None,
                    )
            job.retry_count = retry
        metrics = self.metrics()
        if status == JobStatus.RUNNING.value:
            value = metrics.processed
        else:
            value = metrics.processed
        self.progress.emit(value, metrics.total, name, status, duration, retry, error)

    def _job_index(self, job: TTSJob | None) -> int:
        if job is None:
            return -1
        for index, current in enumerate(self._state.jobs):
            if current.row_number == job.row_number:
                return index
        return -1
