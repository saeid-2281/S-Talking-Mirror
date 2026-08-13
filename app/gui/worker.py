from __future__ import annotations

import math
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.database import JobDatabase
from app.exceptions import ProviderError
from app.models import AppSettings, TTSJob
from app.models.generation_orchestration import (
    GenerationExecutionPlan,
    ProviderExecutionCandidate,
)
from app.models.retry_policy import FailureCategory, RetryHistoryEntry
from app.provider_factory import create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.services.failure_analysis_service import FailureAnalysisService
from app.services.language_assurance_service import LanguageAssuranceService
from app.services.output_validation_service import OutputValidationService
from app.services.pronunciation_service import PronunciationService


class GenerationWorker(QObject):
    """Generate queued audio with pause, stop, retry and provider failover."""

    progress = Signal(int, int, str, str, float, int, str)
    log = Signal(str)
    failover = Signal(dict)
    scheduler = Signal(dict)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        database_path: Path,
        project_key: str,
        orchestration_plan: GenerationExecutionPlan | None = None,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.settings = settings
        self.output_dir = output_dir
        self.database_path = database_path
        self.project_key = project_key
        self.orchestration_plan = orchestration_plan
        self._paused = threading.Event()
        self._paused.set()
        self._stop_event = threading.Event()
        self._provider = None
        self._active_providers: set[object] = set()
        self._state_lock = threading.RLock()
        self.failure_analysis = FailureAnalysisService()
        self.language_assurance = LanguageAssuranceService()
        self._candidate_index = 0
        self._switches = 0
        self._runtime_failures: dict[str, int] = {
            candidate.candidate_id: candidate.consecutive_failures
            for candidate in (orchestration_plan.candidates if orchestration_plan else ())
        }
        self._runtime_open: set[str] = {
            candidate.candidate_id
            for candidate in (orchestration_plan.candidates if orchestration_plan else ())
            if str(candidate.circuit_status) == "open"
        }

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def pause(self) -> None:
        self._paused.clear()
        self.log.emit("Paused after current request.")

    def resume(self) -> None:
        self._paused.set()
        self.log.emit("Resumed.")

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        providers = [self._provider]
        with self._state_lock:
            providers.extend(self._active_providers)
        for provider in providers:
            cancel = getattr(provider, "cancel", None)
            if callable(cancel):
                cancel()
        self._paused.set()
        self.log.emit("Stop requested. Finishing the current provider request, if any…")

    def _wait_until_runnable(self) -> bool:
        while not self._stop_event.is_set():
            if self._paused.wait(timeout=0.05):
                return not self._stop_event.is_set()
        return False

    def _interruptible_delay(self, seconds: float) -> bool:
        if seconds <= 0:
            return not self._stop_event.is_set()
        return not self._stop_event.wait(timeout=seconds)

    @Slot()
    def run(self) -> None:
        if self._concurrent_scheduling():
            self._run_concurrent()
            return
        self._run_serial()

    def _run_serial(self) -> None:
        summary = {
            "total": len(self.jobs),
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "stopped": False,
            "stop_reason": None,
            "failover_switches": 0,
            "provider_sequence": [],
            "provider_diagnostics": {
                "provider": self.settings.provider,
                "voice_id": self.settings.voice_id,
                "model_id": self.settings.model_id,
                "temporary_files_cleaned": 0,
                "last_error": None,
            },
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        summary["provider_diagnostics"]["temporary_files_cleaned"] = self._cleanup_temporary_files()
        db = JobDatabase(self.database_path)
        db.sync_jobs(self.project_key, self.jobs)
        db.reset_running(self.project_key)

        try:
            for index, job in enumerate(self.jobs, 1):
                if not self._wait_until_runnable():
                    summary["stopped"] = True
                    summary["stop_reason"] = "user"
                    break

                if self._adaptive_routing():
                    self._select_routed_candidate(index)
                elif not self._sticky_profile() and self._candidate_index != 0:
                    self._switch_candidate(0)

                active_settings = self._active_settings()
                extension = DEFAULT_PROVIDER_REGISTRY.output_extension(active_settings.provider, active_settings.file_extension)
                output_path = job.output_path(self.output_dir, extension)

                if db.status_for(self.project_key, job) == "completed" and output_path.exists():
                    summary["skipped"] += 1
                    self.progress.emit(index, len(self.jobs), str(output_path), "skipped", 0, job.retry_count, "")
                    continue

                if output_path.exists() and active_settings.skip_existing:
                    db.mark_result(self.project_key, job, "skipped")
                    summary["skipped"] += 1
                    self.progress.emit(index, len(self.jobs), str(output_path), "skipped", 0, job.retry_count, "")
                    continue

                if not self._wait_for_retry_window(job, index, len(self.jobs)):
                    summary["stopped"] = True
                    summary["stop_reason"] = "user"
                    break

                job_switches = 0
                attempt_offset = 0
                routing_emitted = False
                attempted_candidates: set[str] = set()
                while True:
                    active_settings = self._active_settings()
                    candidate = self._active_candidate()
                    if candidate is not None:
                        attempted_candidates.add(candidate.candidate_id)
                    if self._adaptive_routing() and candidate is not None and not routing_emitted:
                        routing_emitted = True
                        self._emit_orchestration_event(
                            job,
                            candidate,
                            None,
                            failure_category="none",
                            error_code="none",
                            outcome="routed",
                            circuit_opened=False,
                            characters=len(job.text),
                            reason="adaptive queue assignment",
                        )
                    started = time.perf_counter()
                    attempt = job.retry_count + attempt_offset + 1
                    try:
                        job_settings = self.language_assurance.settings_for_job(job, active_settings)
                        provider = self._ensure_provider(job_settings)
                        self._append_provider_sequence(summary, candidate, active_settings)
                        job.next_retry_at = None
                        job.retry_history.append(
                            RetryHistoryEntry(
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                event="attempt_started",
                                attempt=attempt,
                                category=job.failure_category or FailureCategory.UNKNOWN,
                                error_code=job.error_code,
                                fingerprint=job.error_fingerprint,
                                retryable=bool(job.retryable),
                                message=f"provider_profile={candidate.profile_name if candidate else 'current'}",
                            )
                        )
                        db.mark_running(self.project_key, job)
                        self.progress.emit(index, len(self.jobs), job.filename, "running", 0, attempt, "")
                        prepared = PronunciationService().prepare_job(job, job_settings)
                        if prepared.aid_applied:
                            summary["provider_diagnostics"].setdefault("pronunciation_aid", 0)
                            summary["provider_diagnostics"]["pronunciation_aid"] += 1
                        audio = provider.synthesize(prepared.provider_text, job_settings)
                        summary["provider_diagnostics"]["language_lock"] = (
                            job_settings.language_code or ""
                        )
                        if self._stop_event.is_set():
                            raise ProviderError("Generation cancelled by user.", provider_code="cancelled")
                        self._write_atomic(output_path, audio)
                        duration = time.perf_counter() - started
                        job.next_retry_at = None
                        job.retry_exhausted = False
                        job.retry_history.append(
                            RetryHistoryEntry(
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                event="completed",
                                attempt=attempt,
                                category=job.failure_category or FailureCategory.UNKNOWN,
                                error_code=job.error_code,
                                fingerprint=job.error_fingerprint,
                                retryable=bool(job.retryable),
                            )
                        )
                        if candidate is not None and (
                            self._adaptive_routing()
                            or self._runtime_failures.get(candidate.candidate_id, 0) > 0
                            or job_switches > 0
                        ):
                            self._runtime_failures[candidate.candidate_id] = 0
                            self._runtime_open.discard(candidate.candidate_id)
                            self._emit_orchestration_event(
                                job,
                                candidate,
                                None,
                                failure_category="none",
                                error_code="none",
                                outcome="success",
                                circuit_opened=False,
                                duration_seconds=duration,
                                characters=len(job.text),
                            )
                        db.mark_result(self.project_key, job, "completed", duration)
                        summary["completed"] += 1
                        self.progress.emit(index, len(self.jobs), str(output_path), "completed", duration, attempt, "")
                        break
                    except Exception as exc:
                        duration = time.perf_counter() - started
                        if self._is_cancelled_error(exc):
                            job.status = type(job.status).PENDING
                            db.mark_result(self.project_key, job, "pending", duration, None)
                            self.progress.emit(index, len(self.jobs), job.filename, "pending", duration, job.retry_count, "")
                            summary["stopped"] = True
                            summary["stop_reason"] = "user"
                            break

                        error = self._safe_error(exc)
                        analysis = self.failure_analysis.analyze(exc)
                        summary["provider_diagnostics"]["last_error"] = self._error_info(exc)
                        summary["provider_diagnostics"]["failure_category"] = analysis.category.value
                        summary["provider_diagnostics"]["error_fingerprint"] = analysis.fingerprint
                        summary["provider_diagnostics"]["retryable"] = analysis.retryable

                        next_index = self._next_candidate_index(analysis.category, attempted_candidates)
                        failures = self._increment_candidate_failure(candidate)
                        circuit_opened = self._circuit_opened(candidate, failures)
                        if candidate is not None and circuit_opened:
                            self._runtime_open.add(candidate.candidate_id)

                        if next_index is not None:
                            target = self._plan_candidates()[next_index]
                            self._switches += 1
                            job_switches += 1
                            attempt_offset += 1
                            summary["failover_switches"] = self._switches
                            self._emit_orchestration_event(
                                job,
                                candidate,
                                target,
                                failure_category=analysis.category.value,
                                error_code=analysis.error_code,
                                outcome="switched",
                                circuit_opened=circuit_opened,
                                duration_seconds=duration,
                                characters=len(job.text),
                            )
                            job.retry_history.append(
                                RetryHistoryEntry(
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    event="provider_failover",
                                    attempt=attempt,
                                    category=analysis.category,
                                    error_code=analysis.error_code,
                                    fingerprint=analysis.fingerprint,
                                    retryable=True,
                                    message=f"{candidate.profile_name if candidate else 'current'} -> {target.profile_name}",
                                )
                            )
                            self.log.emit(
                                f"Failover {job.filename}: "
                                f"{candidate.profile_name if candidate else 'current'} → {target.profile_name} "
                                f"({analysis.category.value}/{analysis.error_code})."
                            )
                            self._switch_candidate(next_index)
                            continue

                        if candidate is not None and self._observe_failures():
                            self._emit_orchestration_event(
                                job,
                                candidate,
                                None,
                                failure_category=analysis.category.value,
                                error_code=analysis.error_code,
                                outcome="exhausted",
                                circuit_opened=circuit_opened,
                                duration_seconds=duration,
                                characters=len(job.text),
                            )
                        job.error = error
                        FailureAnalysisService.apply(
                            job,
                            analysis,
                            attempt=attempt,
                            max_retries=active_settings.max_retries,
                        )
                        db.mark_result(self.project_key, job, "failed", duration, error)
                        summary["failed"] += 1
                        self.progress.emit(index, len(self.jobs), job.filename, "failed", duration, attempt, error)
                        self.log.emit(f"ERROR {job.filename}: {error}")
                        break

                if summary["stopped"]:
                    break
                if self._stop_event.is_set():
                    summary["stopped"] = True
                    summary["stop_reason"] = "user"
                    break
                if self.settings.delay_seconds and index < len(self.jobs):
                    if not self._interruptible_delay(self.settings.delay_seconds):
                        summary["stopped"] = True
                        summary["stop_reason"] = "user"
                        break

            if summary["stopped"]:
                self.log.emit("Generation stopped by user.")
            active = self._active_candidate()
            summary["provider_diagnostics"]["final_profile"] = active.profile_name if active else "Current provider"
            self.finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self._close_provider()
            summary["provider_diagnostics"]["temporary_files_cleaned"] += self._cleanup_temporary_files()
            db.close()

    def _concurrent_scheduling(self) -> bool:
        plan = self.orchestration_plan
        return bool(
            plan is not None
            and plan.scheduling_enabled
            and plan.maximum_concurrency > 1
            and len(self.jobs) > 1
        )

    def _run_concurrent(self) -> None:
        plan = self.orchestration_plan
        if plan is None:
            self._run_serial()
            return
        summary: dict[str, object] = {
            "total": len(self.jobs),
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "stopped": False,
            "stop_reason": None,
            "failover_switches": 0,
            "provider_sequence": [],
            "scheduler": {
                "mode": str(plan.scheduling_mode),
                "initial_concurrency": plan.initial_concurrency,
                "maximum_concurrency": plan.maximum_concurrency,
                "peak_concurrency": 0,
                "backpressure_events": 0,
                "recovery_events": 0,
            },
            "provider_diagnostics": {
                "provider": self.settings.provider,
                "voice_id": self.settings.voice_id,
                "model_id": self.settings.model_id,
                "temporary_files_cleaned": 0,
                "last_error": None,
            },
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        diagnostics = summary["provider_diagnostics"]
        assert isinstance(diagnostics, dict)
        diagnostics["temporary_files_cleaned"] = self._cleanup_temporary_files()
        db = JobDatabase(self.database_path)
        db.sync_jobs(self.project_key, self.jobs)
        db.reset_running(self.project_key)
        current_limit = max(
            plan.minimum_concurrency,
            min(plan.maximum_concurrency, plan.initial_concurrency),
        )
        success_streak = 0
        recent_rate_limits: deque[bool] = deque(maxlen=plan.error_window)
        active_counts = {candidate.candidate_id: 0 for candidate in plan.candidates}
        cooldowns: dict[str, float] = {}
        pending: deque[tuple[int, TTSJob]] = deque()
        active: dict[Future[dict[str, object]], tuple[int, TTSJob, ProviderExecutionCandidate]] = {}
        self._emit_scheduler_event(
            None,
            "scheduler_started",
            current_limit,
            current_limit,
            len(self.jobs),
            0,
            "dynamic scheduling enabled",
        )
        try:
            for index, job in enumerate(self.jobs, 1):
                active_settings = self.settings
                extension = DEFAULT_PROVIDER_REGISTRY.output_extension(
                    active_settings.provider, active_settings.file_extension
                )
                output_path = job.output_path(self.output_dir, extension)
                if db.status_for(self.project_key, job) == "completed" and output_path.exists():
                    summary["skipped"] = int(summary["skipped"]) + 1
                    self.progress.emit(
                        index, len(self.jobs), str(output_path), "skipped", 0, job.retry_count, ""
                    )
                    continue
                if output_path.exists() and active_settings.skip_existing:
                    db.mark_result(self.project_key, job, "skipped")
                    summary["skipped"] = int(summary["skipped"]) + 1
                    self.progress.emit(
                        index, len(self.jobs), str(output_path), "skipped", 0, job.retry_count, ""
                    )
                    continue
                pending.append((index, job))

            with ThreadPoolExecutor(
                max_workers=plan.maximum_concurrency,
                thread_name_prefix="s-talking-generation",
            ) as executor:
                while pending or active:
                    if self._stop_event.is_set():
                        summary["stopped"] = True
                        summary["stop_reason"] = "user"
                        pending.clear()
                    dispatch_gate = threading.Event()
                    submitted_in_batch = 0
                    while (
                        pending
                        and len(active) < current_limit
                        and self._paused.is_set()
                        and not self._stop_event.is_set()
                    ):
                        index, job = pending[0]
                        if not self._retry_window_ready(job):
                            pending.rotate(-1)
                            if all(not self._retry_window_ready(item[1]) for item in pending):
                                break
                            continue
                        candidate = self._scheduler_candidate(
                            index, active_counts=active_counts, cooldowns=cooldowns
                        )
                        if candidate is None:
                            break
                        pending.popleft()
                        active_counts[candidate.candidate_id] += 1
                        db.mark_running(self.project_key, job)
                        self.progress.emit(
                            index,
                            len(self.jobs),
                            job.filename,
                            "running",
                            0,
                            job.retry_count + 1,
                            "",
                        )
                        future = executor.submit(
                            self._execute_concurrent_job,
                            job,
                            candidate,
                            cooldowns,
                            dispatch_gate,
                        )
                        active[future] = (index, job, candidate)
                        submitted_in_batch += 1
                        scheduler = summary["scheduler"]
                        assert isinstance(scheduler, dict)
                        scheduler["peak_concurrency"] = max(
                            int(scheduler["peak_concurrency"]), len(active)
                        )

                    # Release the whole dispatch batch only after every available
                    # slot has been submitted.  On Windows this prevents the first
                    # fast-starting worker from monopolising a batch before the
                    # remaining ThreadPool workers have entered the job body.
                    if submitted_in_batch:
                        dispatch_gate.set()

                    if not active:
                        if pending and not self._stop_event.is_set():
                            if self._all_runtime_candidates_open():
                                error = "All provider circuits opened during generation."
                                while pending:
                                    index, job = pending.popleft()
                                    job.error = error
                                    db.mark_result(
                                        self.project_key, job, "failed", 0.0, error
                                    )
                                    summary["failed"] = int(summary["failed"]) + 1
                                    self.progress.emit(
                                        index,
                                        len(self.jobs),
                                        job.filename,
                                        "failed",
                                        0.0,
                                        job.retry_count + 1,
                                        error,
                                    )
                                break
                            time.sleep(
                                min(0.05, self._next_cooldown_delay(cooldowns))
                            )
                            continue
                        break

                    done, _ = wait(tuple(active), timeout=0.05, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        index, job, assigned = active.pop(future)
                        active_counts[assigned.candidate_id] = max(
                            0, active_counts[assigned.candidate_id] - 1
                        )
                        result = future.result()
                        for event in result.get("orchestration_events", ()):
                            if isinstance(event, dict):
                                self.failover.emit(event)
                        candidate = result.get("candidate")
                        if isinstance(candidate, ProviderExecutionCandidate):
                            active_counts[candidate.candidate_id] = max(
                                0, active_counts.get(candidate.candidate_id, 0)
                            )
                            self._append_provider_sequence(summary, candidate, candidate.settings)
                        duration = float(result.get("duration") or 0.0)
                        status = str(result.get("status") or "failed")
                        attempt = int(result.get("attempt") or job.retry_count + 1)
                        if status == "completed":
                            output_path = Path(str(result["output_path"]))
                            db.mark_result(self.project_key, job, "completed", duration)
                            summary["completed"] = int(summary["completed"]) + 1
                            self.progress.emit(
                                index,
                                len(self.jobs),
                                str(output_path),
                                "completed",
                                duration,
                                attempt,
                                "",
                            )
                            success_streak += 1
                            if (
                                str(plan.scheduling_mode) == "adaptive"
                                and success_streak >= plan.success_window
                                and current_limit < plan.maximum_concurrency
                            ):
                                previous = current_limit
                                current_limit = min(
                                    plan.maximum_concurrency,
                                    current_limit + plan.increase_step,
                                )
                                success_streak = 0
                                scheduler = summary["scheduler"]
                                assert isinstance(scheduler, dict)
                                scheduler["recovery_events"] = int(
                                    scheduler["recovery_events"]
                                ) + 1
                                self._emit_scheduler_event(
                                    candidate if isinstance(candidate, ProviderExecutionCandidate) else assigned,
                                    "concurrency_increased",
                                    previous,
                                    current_limit,
                                    len(pending),
                                    len(active),
                                    "success window completed",
                                )
                        elif status == "cancelled":
                            db.mark_result(self.project_key, job, "pending", duration, None)
                            self.progress.emit(
                                index, len(self.jobs), job.filename, "pending", duration, attempt, ""
                            )
                            summary["stopped"] = True
                            summary["stop_reason"] = "user"
                        else:
                            error = str(result.get("error") or "Unknown generation failure")
                            diagnostics["last_error"] = error
                            analysis = result.get("analysis")
                            if analysis is not None:
                                FailureAnalysisService.apply(
                                    job,
                                    analysis,
                                    attempt=attempt,
                                    max_retries=(
                                        candidate.settings.max_retries
                                        if isinstance(candidate, ProviderExecutionCandidate)
                                        else self.settings.max_retries
                                    ),
                                )
                            job.error = error
                            db.mark_result(self.project_key, job, "failed", duration, error)
                            summary["failed"] = int(summary["failed"]) + 1
                            self.progress.emit(
                                index, len(self.jobs), job.filename, "failed", duration, attempt, error
                            )
                            self.log.emit(f"ERROR {job.filename}: {error}")
                            success_streak = 0
                        rate_limit_result = bool(result.get("rate_limited"))
                        recent_rate_limits.append(rate_limit_result)
                        if rate_limit_result:
                            success_streak = 0
                            limited_candidate = result.get("rate_limited_candidate")
                            scheduler_candidate = (
                                limited_candidate
                                if isinstance(
                                    limited_candidate,
                                    ProviderExecutionCandidate,
                                )
                                else (
                                    candidate
                                    if isinstance(
                                        candidate,
                                        ProviderExecutionCandidate,
                                    )
                                    else assigned
                                )
                            )
                            self._emit_scheduler_event(
                                scheduler_candidate,
                                "rate_limited",
                                plan.per_profile_concurrency,
                                1,
                                len(pending),
                                len(active),
                                "provider returned a rate-limit response",
                                metadata={
                                    "cooldown_until": result.get("cooldown_until")
                                },
                            )
                            if (
                                str(plan.scheduling_mode) == "adaptive"
                                and any(recent_rate_limits)
                            ):
                                previous = current_limit
                                current_limit = max(
                                    plan.minimum_concurrency,
                                    int(math.floor(current_limit * plan.decrease_factor)),
                                )
                                if current_limit != previous:
                                    scheduler = summary["scheduler"]
                                    assert isinstance(scheduler, dict)
                                    scheduler["backpressure_events"] = int(
                                        scheduler["backpressure_events"]
                                    ) + 1
                                    self._emit_scheduler_event(
                                        scheduler_candidate,
                                        "backpressure",
                                        previous,
                                        current_limit,
                                        len(pending),
                                        len(active),
                                        "provider rate limit",
                                        metadata={
                                            "cooldown_until": result.get("cooldown_until")
                                        },
                                    )
                    summary["failover_switches"] = self._switches

            if summary["stopped"]:
                self.log.emit("Generation stopped by user.")
            self.finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            with self._state_lock:
                providers = list(self._active_providers)
                self._active_providers.clear()
            for provider in providers:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
            diagnostics["temporary_files_cleaned"] = int(
                diagnostics["temporary_files_cleaned"]
            ) + self._cleanup_temporary_files()
            db.close()

    def _execute_concurrent_job(
        self,
        job: TTSJob,
        initial_candidate: ProviderExecutionCandidate,
        cooldowns: dict[str, float],
        start_gate: threading.Event | None = None,
    ) -> dict[str, object]:
        plan = self.orchestration_plan
        assert plan is not None
        if start_gate is not None:
            while not start_gate.wait(timeout=0.05):
                if self._stop_event.is_set():
                    return {
                        "status": "cancelled",
                        "duration": 0.0,
                        "attempt": job.retry_count + 1,
                        "candidate": initial_candidate,
                        "orchestration_events": [],
                    }
        candidate = initial_candidate
        attempted: set[str] = set()
        attempt_offset = 0
        rate_limited = False
        rate_limited_candidate: ProviderExecutionCandidate | None = None
        cooldown_until: str | None = None
        orchestration_events: list[dict[str, object]] = []
        while True:
            attempted.add(candidate.candidate_id)
            attempt = job.retry_count + attempt_offset + 1
            started = time.perf_counter()
            provider = None
            try:
                job.next_retry_at = None
                job.retry_history.append(
                    RetryHistoryEntry(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        event="attempt_started",
                        attempt=attempt,
                        category=job.failure_category or FailureCategory.UNKNOWN,
                        error_code=job.error_code,
                        fingerprint=job.error_fingerprint,
                        retryable=bool(job.retryable),
                        message=f"provider_profile={candidate.profile_name}",
                    )
                )
                job_settings = self.language_assurance.settings_for_job(job, candidate.settings)
                provider = create_provider(job_settings)
                with self._state_lock:
                    self._active_providers.add(provider)
                self._append_orchestration_event(
                    orchestration_events,
                    job,
                    candidate,
                    None,
                    failure_category="none",
                    error_code="none",
                    outcome="routed",
                    circuit_opened=False,
                    characters=len(job.text),
                    reason="concurrent scheduler assignment",
                )
                prepared = PronunciationService().prepare_job(job, job_settings)
                audio = provider.synthesize(prepared.provider_text, job_settings)
                if self._stop_event.is_set():
                    raise ProviderError(
                        "Generation cancelled by user.", provider_code="cancelled"
                    )
                extension = DEFAULT_PROVIDER_REGISTRY.output_extension(
                    job_settings.provider, job_settings.file_extension
                )
                output_path = job.output_path(self.output_dir, extension)
                self._write_atomic(output_path, audio)
                duration = time.perf_counter() - started
                job.next_retry_at = None
                job.retry_exhausted = False
                job.retry_history.append(
                    RetryHistoryEntry(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        event="completed",
                        attempt=attempt,
                        category=job.failure_category or FailureCategory.UNKNOWN,
                        error_code=job.error_code,
                        fingerprint=job.error_fingerprint,
                        retryable=bool(job.retryable),
                    )
                )
                with self._state_lock:
                    self._runtime_failures[candidate.candidate_id] = 0
                    self._runtime_open.discard(candidate.candidate_id)
                self._append_orchestration_event(
                    orchestration_events,
                    job,
                    candidate,
                    None,
                    failure_category="none",
                    error_code="none",
                    outcome="success",
                    circuit_opened=False,
                    duration_seconds=duration,
                    characters=len(job.text),
                )
                return {
                    "status": "completed",
                    "duration": duration,
                    "attempt": attempt,
                    "output_path": output_path,
                    "candidate": candidate,
                    "rate_limited": rate_limited,
                    "rate_limited_candidate": rate_limited_candidate,
                    "cooldown_until": cooldown_until,
                    "orchestration_events": orchestration_events,
                }
            except Exception as exc:
                duration = time.perf_counter() - started
                if self._is_cancelled_error(exc):
                    return {
                        "status": "cancelled",
                        "duration": duration,
                        "attempt": attempt,
                        "candidate": candidate,
                        "orchestration_events": orchestration_events,
                    }
                analysis = self.failure_analysis.analyze(exc)
                if analysis.category == FailureCategory.RATE_LIMIT:
                    rate_limited = True
                    rate_limited_candidate = candidate
                    cooldown_seconds = max(0, plan.rate_limit_cooldown_seconds)
                    with self._state_lock:
                        cooldowns[candidate.candidate_id] = time.monotonic() + cooldown_seconds
                    cooldown_until = (
                        datetime.now(timezone.utc)
                        + timedelta(seconds=cooldown_seconds)
                    ).isoformat()
                with self._state_lock:
                    failures = self._runtime_failures.get(candidate.candidate_id, 0) + 1
                    self._runtime_failures[candidate.candidate_id] = failures
                    circuit_opened = failures >= plan.failure_threshold
                    if circuit_opened:
                        self._runtime_open.add(candidate.candidate_id)
                    next_candidate = self._next_concurrent_candidate(
                        candidate, attempted, cooldowns
                    )
                    can_switch = (
                        next_candidate is not None
                        and analysis.category
                        in {
                            FailureCategory.NETWORK,
                            FailureCategory.RATE_LIMIT,
                            FailureCategory.SERVER,
                            FailureCategory.AUTHENTICATION,
                            FailureCategory.QUOTA,
                        }
                        and self._switches < plan.max_switches
                    )
                    if can_switch:
                        self._switches += 1
                if can_switch and next_candidate is not None:
                    self._append_orchestration_event(
                        orchestration_events,
                        job,
                        candidate,
                        next_candidate,
                        failure_category=analysis.category.value,
                        error_code=analysis.error_code,
                        outcome="switched",
                        circuit_opened=circuit_opened,
                        duration_seconds=duration,
                        characters=len(job.text),
                    )
                    candidate = next_candidate
                    attempt_offset += 1
                    continue
                self._append_orchestration_event(
                    orchestration_events,
                    job,
                    candidate,
                    None,
                    failure_category=analysis.category.value,
                    error_code=analysis.error_code,
                    outcome="exhausted",
                    circuit_opened=circuit_opened,
                    duration_seconds=duration,
                    characters=len(job.text),
                )
                return {
                    "status": "failed",
                    "duration": duration,
                    "attempt": attempt,
                    "candidate": candidate,
                    "analysis": analysis,
                    "error": self._safe_error(exc),
                    "rate_limited": rate_limited,
                    "rate_limited_candidate": rate_limited_candidate,
                    "cooldown_until": cooldown_until,
                    "orchestration_events": orchestration_events,
                }
            finally:
                if provider is not None:
                    with self._state_lock:
                        self._active_providers.discard(provider)
                    close = getattr(provider, "close", None)
                    if callable(close):
                        close()

    def _scheduler_candidate(
        self,
        job_index: int,
        *,
        active_counts: dict[str, int],
        cooldowns: dict[str, float],
    ) -> ProviderExecutionCandidate | None:
        candidates = self._plan_candidates()
        if not candidates:
            return None
        plan = self.orchestration_plan
        assert plan is not None
        preferred_id = (
            plan.routing_sequence[(job_index - 1) % len(plan.routing_sequence)]
            if plan.routing_sequence
            else candidates[0].candidate_id
        )
        ordered = sorted(
            candidates,
            key=lambda item: (
                item.candidate_id != preferred_id,
                active_counts.get(item.candidate_id, 0),
                -item.routing_score,
                item.priority,
            ),
        )
        now = time.monotonic()
        for candidate in ordered:
            if candidate.candidate_id in self._runtime_open:
                continue
            if cooldowns.get(candidate.candidate_id, 0.0) > now:
                continue
            if active_counts.get(candidate.candidate_id, 0) >= plan.per_profile_concurrency:
                continue
            return candidate
        return None

    def _next_concurrent_candidate(
        self,
        current: ProviderExecutionCandidate,
        attempted: set[str],
        cooldowns: dict[str, float],
    ) -> ProviderExecutionCandidate | None:
        now = time.monotonic()
        for candidate in self._plan_candidates():
            if candidate.candidate_id == current.candidate_id:
                continue
            if candidate.candidate_id in attempted or candidate.candidate_id in self._runtime_open:
                continue
            if cooldowns.get(candidate.candidate_id, 0.0) > now:
                continue
            return candidate
        return None

    def _all_runtime_candidates_open(self) -> bool:
        candidates = self._plan_candidates()
        return bool(candidates) and all(
            candidate.candidate_id in self._runtime_open for candidate in candidates
        )

    @staticmethod
    def _next_cooldown_delay(cooldowns: dict[str, float]) -> float:
        now = time.monotonic()
        remaining = [value - now for value in cooldowns.values() if value > now]
        return max(0.01, min(remaining)) if remaining else 0.02

    @staticmethod
    def _retry_window_ready(job: TTSJob) -> bool:
        if not job.next_retry_at:
            return True
        try:
            target = datetime.fromisoformat(job.next_retry_at)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
        except ValueError:
            job.next_retry_at = None
            return True
        if target <= datetime.now(timezone.utc):
            job.next_retry_at = None
            return True
        return False

    def _emit_scheduler_event(
        self,
        candidate: ProviderExecutionCandidate | None,
        event_type: str,
        from_concurrency: int,
        to_concurrency: int,
        pending_jobs: int,
        active_jobs: int,
        reason: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        plan = self.orchestration_plan
        self.scheduler.emit(
            {
                "project_id": plan.project_id if plan else None,
                "provider": candidate.provider if candidate else self.settings.provider,
                "profile_id": candidate.profile_id if candidate else None,
                "profile_name": candidate.profile_name if candidate else "Scheduler",
                "event_type": event_type,
                "from_concurrency": max(1, from_concurrency),
                "to_concurrency": max(1, to_concurrency),
                "pending_jobs": max(0, pending_jobs),
                "active_jobs": max(0, active_jobs),
                "reason": reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": dict(metadata or {}),
            }
        )

    def _plan_candidates(self) -> tuple[ProviderExecutionCandidate, ...]:
        return self.orchestration_plan.candidates if self.orchestration_plan else ()

    def _active_candidate(self) -> ProviderExecutionCandidate | None:
        candidates = self._plan_candidates()
        return candidates[self._candidate_index] if 0 <= self._candidate_index < len(candidates) else None

    def _active_settings(self) -> AppSettings:
        candidate = self._active_candidate()
        return candidate.settings if candidate is not None else self.settings

    def _ensure_provider(self, settings: AppSettings):
        if self._provider is None:
            self._provider = create_provider(settings)
        return self._provider

    def _switch_candidate(self, index: int) -> None:
        if index == self._candidate_index and self._provider is not None:
            return
        self._close_provider()
        self._candidate_index = index

    def _close_provider(self) -> None:
        provider = self._provider
        self._provider = None
        close = getattr(provider, "close", None)
        if callable(close):
            close()

    def _adaptive_routing(self) -> bool:
        return bool(
            self.orchestration_plan is not None
            and self.orchestration_plan.routing_enabled
            and self.orchestration_plan.routing_sequence
        )

    def _select_routed_candidate(self, job_index: int) -> None:
        plan = self.orchestration_plan
        if plan is None or not plan.routing_sequence:
            return
        candidate_id = plan.routing_sequence[(job_index - 1) % len(plan.routing_sequence)]
        candidates = self._plan_candidates()
        preferred = next(
            (index for index, item in enumerate(candidates) if item.candidate_id == candidate_id),
            None,
        )
        if preferred is not None and candidates[preferred].candidate_id not in self._runtime_open:
            self._switch_candidate(preferred)
            return
        for index, candidate in enumerate(candidates):
            if candidate.candidate_id not in self._runtime_open:
                self._switch_candidate(index)
                return

    def _next_candidate_index(
        self,
        category: FailureCategory,
        attempted_candidates: set[str],
    ) -> int | None:
        plan = self.orchestration_plan
        if plan is None or not plan.enabled or category not in {
            FailureCategory.NETWORK,
            FailureCategory.RATE_LIMIT,
            FailureCategory.SERVER,
            FailureCategory.AUTHENTICATION,
            FailureCategory.QUOTA,
        }:
            return None
        if self._switches >= plan.max_switches:
            return None
        candidates = plan.candidates
        for offset in range(1, len(candidates) + 1):
            index = (self._candidate_index + offset) % len(candidates)
            if index == self._candidate_index:
                continue
            if candidates[index].candidate_id in self._runtime_open:
                continue
            if candidates[index].candidate_id in attempted_candidates:
                continue
            return index
        return None

    def _increment_candidate_failure(self, candidate: ProviderExecutionCandidate | None) -> int:
        if candidate is None:
            return 1
        failures = self._runtime_failures.get(candidate.candidate_id, 0) + 1
        self._runtime_failures[candidate.candidate_id] = failures
        return failures

    def _circuit_opened(self, candidate: ProviderExecutionCandidate | None, failures: int) -> bool:
        return bool(
            candidate is not None
            and self.orchestration_plan is not None
            and failures >= self.orchestration_plan.failure_threshold
        )

    def _sticky_profile(self) -> bool:
        return bool(self.orchestration_plan is None or self.orchestration_plan.sticky_successful_profile)

    def _observe_failures(self) -> bool:
        return bool(self.orchestration_plan is not None and self.orchestration_plan.mode != "never")

    def _orchestration_event_payload(
        self,
        job: TTSJob,
        source: ProviderExecutionCandidate | None,
        target: ProviderExecutionCandidate | None,
        *,
        failure_category: str,
        error_code: str,
        outcome: str,
        circuit_opened: bool,
        duration_seconds: float = 0.0,
        characters: int = 0,
        reason: str = "",
    ) -> dict[str, object] | None:
        if source is None:
            return None
        plan = self.orchestration_plan
        return {
            "project_id": plan.project_id if plan else None,
            "job_row_number": job.row_number,
            "filename": job.filename,
            "provider": source.provider,
            "from_profile_id": source.profile_id,
            "from_profile_name": source.profile_name,
            "to_profile_id": target.profile_id if target else None,
            "to_profile_name": target.profile_name if target else None,
            "failure_category": failure_category,
            "error_code": error_code,
            "outcome": outcome,
            "switch_number": self._switches,
            "consecutive_failures": self._runtime_failures.get(source.candidate_id, 0),
            "circuit_opened": circuit_opened,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "project_key": self.project_key,
                "routing_mode": str(plan.routing_mode) if plan else "priority",
                "routing_score": source.routing_score,
                "routing_weight": source.routing_weight,
                "duration_seconds": max(0.0, duration_seconds),
                "characters": max(0, characters),
                "reason": reason,
            },
        }

    def _append_orchestration_event(
        self,
        events: list[dict[str, object]],
        job: TTSJob,
        source: ProviderExecutionCandidate | None,
        target: ProviderExecutionCandidate | None,
        *,
        failure_category: str,
        error_code: str,
        outcome: str,
        circuit_opened: bool,
        duration_seconds: float = 0.0,
        characters: int = 0,
        reason: str = "",
    ) -> None:
        payload = self._orchestration_event_payload(
            job,
            source,
            target,
            failure_category=failure_category,
            error_code=error_code,
            outcome=outcome,
            circuit_opened=circuit_opened,
            duration_seconds=duration_seconds,
            characters=characters,
            reason=reason,
        )
        if payload is not None:
            events.append(payload)

    def _emit_orchestration_event(
        self,
        job: TTSJob,
        source: ProviderExecutionCandidate | None,
        target: ProviderExecutionCandidate | None,
        *,
        failure_category: str,
        error_code: str,
        outcome: str,
        circuit_opened: bool,
        duration_seconds: float = 0.0,
        characters: int = 0,
        reason: str = "",
    ) -> None:
        payload = self._orchestration_event_payload(
            job,
            source,
            target,
            failure_category=failure_category,
            error_code=error_code,
            outcome=outcome,
            circuit_opened=circuit_opened,
            duration_seconds=duration_seconds,
            characters=characters,
            reason=reason,
        )
        if payload is not None:
            self.failover.emit(payload)

    @staticmethod
    def _append_provider_sequence(
        summary: dict[str, object],
        candidate: ProviderExecutionCandidate | None,
        settings: AppSettings,
    ) -> None:
        sequence = summary.setdefault("provider_sequence", [])
        label = candidate.profile_name if candidate is not None else settings.provider
        if isinstance(sequence, list) and (not sequence or sequence[-1] != label):
            sequence.append(label)

    def _wait_for_retry_window(self, job: TTSJob, index: int, total: int) -> bool:
        if not job.next_retry_at:
            return not self._stop_event.is_set()
        try:
            target = datetime.fromisoformat(job.next_retry_at)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
        except ValueError:
            job.next_retry_at = None
            return not self._stop_event.is_set()
        last_countdown: int | None = None
        while not self._stop_event.is_set():
            remaining = max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
            if remaining <= 0:
                job.next_retry_at = None
                return True
            countdown = max(1, int(remaining + 0.999))
            if countdown != last_countdown:
                last_countdown = countdown
                self.progress.emit(
                    index,
                    total,
                    job.filename,
                    "retrying",
                    remaining,
                    job.retry_count + 1,
                    f"Retry in {countdown}s",
                )
                self.log.emit(f"Retry countdown {job.filename}: {countdown}s")
            if self._stop_event.wait(timeout=min(1.0, remaining)):
                return False
        return False

    def _write_atomic(self, output_path: Path, audio: bytes) -> None:
        OutputValidationService.finalize_atomic(output_path, audio)

    def _cleanup_temporary_files(self) -> int:
        if not self.output_dir.exists():
            return 0
        cleaned = 0
        for path in self.output_dir.glob(".*.tmp"):
            try:
                path.unlink()
                cleaned += 1
            except OSError:
                pass
        return cleaned

    @staticmethod
    def _is_cancelled_error(exc: Exception) -> bool:
        return isinstance(exc, ProviderError) and (
            exc.provider_code == "cancelled" or "cancelled" in str(exc).lower()
        )

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if not isinstance(exc, ProviderError):
            return str(exc)
        parts = [exc.user_message]
        if exc.provider_code:
            parts.append(f"code={exc.provider_code}")
        if exc.http_status:
            parts.append(f"status={exc.http_status}")
        if exc.request_id:
            parts.append(f"request_id={exc.request_id}")
        return f"{parts[0]} [" + " ".join(parts[1:]) + "]" if len(parts) > 1 else parts[0]

    @staticmethod
    def _error_info(exc: Exception) -> dict[str, object] | None:
        if not isinstance(exc, ProviderError):
            return {"message": str(exc)}
        return {
            "message": exc.user_message,
            "retryable": exc.retryable,
            "http_status": exc.http_status,
            "provider_code": exc.provider_code,
            "request_id": exc.request_id,
            "technical_details": exc.technical_details,
        }
