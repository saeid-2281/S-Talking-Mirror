from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from app.models.domain import AppSettings, JobStatus, TTSJob
from app.models.generation_monitor_state import GenerationMonitorState
from app.services.queue_service import QueueService


class GenerationMonitorService(QObject):
    """Builds the live monitor state from queue and progress events."""

    updated = Signal(object)
    event = Signal(str)

    def __init__(self, clock: Callable[[], float] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.clock = clock or time.monotonic
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.queue_service = QueueService()
        self.state = GenerationMonitorState()
        self.jobs: list[TTSJob] = []
        self.provider = "Not selected"
        self.output_dir = Path()
        self.settings = AppSettings(provider="mock")
        self.started_at_wall: datetime | None = None
        self.started_at: float | None = None
        self.paused_at: float | None = None
        self.paused_total = 0.0
        self.current_job_started_at: float | None = None
        self.current_row_number: int | None = None
        self.completed_durations: list[float] = []
        self.log_events: list[str] = []

    def reset(self) -> GenerationMonitorState:
        self.timer.stop()
        self.jobs = []
        self.started_at_wall = None
        self.started_at = None
        self.paused_at = None
        self.paused_total = 0.0
        self.current_job_started_at = None
        self.current_row_number = None
        self.completed_durations = []
        self.log_events = []
        return self._publish(GenerationMonitorState())

    def refresh_queue(
        self,
        jobs: list[TTSJob],
        *,
        provider: str,
        output_dir: Path,
        settings: AppSettings,
    ) -> GenerationMonitorState:
        self.jobs = jobs
        self.provider = provider
        self.output_dir = output_dir
        self.settings = settings
        status = self.state.current_status if self.state.current_status != "Idle" else "Ready"
        return self._rebuild(status)

    def start_run(
        self,
        jobs: list[TTSJob],
        *,
        provider: str,
        output_dir: Path,
        settings: AppSettings,
    ) -> GenerationMonitorState:
        self.jobs = jobs
        self.provider = provider
        self.output_dir = output_dir
        self.settings = settings
        self.started_at_wall = datetime.now(timezone.utc)
        self.started_at = self.clock()
        self.paused_at = None
        self.paused_total = 0.0
        self.current_job_started_at = None
        self.current_row_number = None
        self.completed_durations = []
        self.log_events = []
        self._log("run started")
        self.timer.start()
        return self._rebuild("Running")

    def handle_progress(
        self,
        jobs: list[TTSJob],
        *,
        status: str,
        name: str,
        duration: float,
        retry: int,
        error: str,
    ) -> GenerationMonitorState:
        self.jobs = jobs
        job = self._current_job() or self._job_for_name(name)
        if status == JobStatus.RUNNING.value and job:
            if self.current_row_number != job.row_number:
                self.current_row_number = job.row_number
                self.current_job_started_at = self.clock()
                self._log(f"job started: {job.filename}")
        elif status == JobStatus.COMPLETED.value:
            if duration > 0:
                self.completed_durations.append(duration)
            self._log(f"job completed: {Path(name).name or (job.filename if job else '')}".rstrip())
            self.current_job_started_at = None
            self.current_row_number = None
        elif status == JobStatus.FAILED.value:
            self._log(f"job failed: {Path(name).name or (job.filename if job else '')}".rstrip())
            self.current_job_started_at = None
            self.current_row_number = None
        elif status == JobStatus.SKIPPED.value:
            self._log(f"job skipped: {Path(name).name or (job.filename if job else '')}".rstrip())
            self.current_job_started_at = None
            self.current_row_number = None
        state = self._rebuild(status.title(), last_error=error, retry=retry)
        return self._publish(
            GenerationMonitorState(
                **{
                    **asdict(state),
                    "provider_request_seconds": duration if status in {"completed", "failed"} else 0.0,
                    "total_job_seconds": duration if status in {"completed", "failed"} else state.current_job_elapsed_seconds,
                    "inter_file_delay_seconds": self.settings.delay_seconds if status == "completed" else 0.0,
                }
            )
        )

    def pause(self) -> GenerationMonitorState:
        if self.paused_at is None:
            self.paused_at = self.clock()
            self._log("paused")
        return self._rebuild("Paused")

    def resume(self) -> GenerationMonitorState:
        if self.paused_at is not None:
            self.paused_total += max(0.0, self.clock() - self.paused_at)
            self.paused_at = None
            self._log("resumed")
        return self._rebuild("Running")

    def stop_requested(self) -> GenerationMonitorState:
        self._log("stop requested")
        return self._rebuild("Stopping", stopped=True)

    def finish(self, summary: dict | None = None) -> GenerationMonitorState:
        self.timer.stop()
        stopped = bool((summary or {}).get("stopped", False))
        self._log("stopped" if stopped else "run finished")
        return self._rebuild("Stopped by user" if stopped else "Finished", stopped=stopped)

    def tick(self) -> GenerationMonitorState:
        return self._rebuild(self.state.current_status, stopped=self.state.stopped_by_user)

    def report_metrics(self) -> dict[str, float | bool | int | dict[str, int]]:
        return {
            "average_seconds_per_job": self.state.average_seconds_per_completed_job,
            "files_per_minute": self.state.files_per_minute,
            "characters_per_minute": self.state.characters_per_minute,
            "active_generation_time": self.state.active_elapsed_seconds,
            "paused_time": self.state.paused_seconds,
            "stopped_by_user": self.state.stopped_by_user,
            "peak_concurrent_jobs": self.state.peak_concurrent_jobs,
            "final_queue_counts": {
                "pending": self.state.pending,
                "running": self.state.running,
                "completed": self.state.completed,
                "failed": self.state.failed,
                "skipped": self.state.skipped,
            },
        }

    def _rebuild(
        self,
        status: str,
        *,
        last_error: str = "",
        retry: int | None = None,
        stopped: bool = False,
    ) -> GenerationMonitorState:
        metrics = self.queue_service.metrics(self.jobs)
        current = self._current_job()
        next_job = self._next_job()
        active_seconds = self._active_elapsed()
        completed = [job for job in self.jobs if job.status == JobStatus.COMPLETED]
        characters_done = sum(len(job.text) for job in completed)
        current_elapsed = 0.0
        if current and self.current_job_started_at is not None and self.paused_at is None:
            current_elapsed = max(0.0, self.clock() - self.current_job_started_at)
        average = sum(self.completed_durations) / len(self.completed_durations) if self.completed_durations else 0.0
        files_per_minute = (len(completed) / active_seconds * 60) if active_seconds > 0 else 0.0
        chars_per_minute = (characters_done / active_seconds * 60) if active_seconds > 0 else 0.0
        eta_source = average or self.queue_service.fallback_seconds_per_job
        start_text = self.started_at_wall.isoformat() if self.started_at_wall else "Not started"
        state = GenerationMonitorState(
            current_filename=current.filename if current else "None",
            current_row_number=current.row_number if current else None,
            current_provider=self.provider,
            current_status=status,
            current_attempt=retry if retry is not None else (current.retry_count if current else 0),
            current_job_elapsed_seconds=current_elapsed,
            current_job_characters=len(current.text) if current else 0,
            next_filename=next_job.filename if next_job else "None",
            processed=metrics.processed,
            total=metrics.total,
            pending=metrics.pending,
            running=metrics.running,
            completed=metrics.completed,
            failed=metrics.failed,
            skipped=metrics.skipped,
            average_seconds_per_completed_job=average,
            files_per_minute=files_per_minute,
            characters_per_minute=chars_per_minute,
            remaining_eta_seconds=(metrics.pending + metrics.running) * eta_source,
            generation_start_time=start_text,
            total_elapsed_seconds=self._total_elapsed(),
            active_elapsed_seconds=active_seconds,
            paused_seconds=self._paused_elapsed(),
            last_provider_error=last_error or self.state.last_provider_error,
            current_output_path=str(self._output_path(current)) if current else "",
            stopped_by_user=stopped or self.state.stopped_by_user,
        )
        return self._publish(state)

    def _publish(self, state: GenerationMonitorState) -> GenerationMonitorState:
        self.state = state
        self.updated.emit(state)
        return state

    def _log(self, message: str) -> None:
        if self.log_events and self.log_events[-1].endswith(message):
            return
        line = f"Monitor: {message}"
        self.log_events.append(line)
        self.event.emit(line)

    def _current_job(self) -> TTSJob | None:
        return next((job for job in self.jobs if job.status == JobStatus.RUNNING), None)

    def _next_job(self) -> TTSJob | None:
        return next((job for job in self.jobs if job.status == JobStatus.PENDING), None)

    def _job_for_name(self, name: str) -> TTSJob | None:
        stem = Path(name).name
        return next((job for job in self.jobs if job.filename == stem), None)

    def _output_path(self, job: TTSJob | None) -> Path | None:
        if job is None:
            return None
        return self.queue_service.output_path_for(job, self.output_dir, self.settings)

    def _total_elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, self.clock() - self.started_at)

    def _active_elapsed(self) -> float:
        return max(0.0, self._total_elapsed() - self._paused_elapsed())

    def _paused_elapsed(self) -> float:
        current_pause = max(0.0, self.clock() - self.paused_at) if self.paused_at is not None else 0.0
        return self.paused_total + current_pause
