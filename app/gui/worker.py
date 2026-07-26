from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from app.database import JobDatabase
from app.exceptions import ProviderError
from app.models import AppSettings, TTSJob
from app.provider_factory import create_provider
from app.services.pronunciation_service import PronunciationService


class GenerationWorker(QObject):
    """Generate queued audio while supporting cooperative pause and stop.

    A provider request that is already in flight cannot always be cancelled
    safely. In that case the current request is allowed to finish, then the
    queue stops before starting another job. Pauses and inter-file delays are
    immediately interruptible.
    """

    progress = Signal(int, int, str, str, float, int, str)
    log = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        database_path: Path,
        project_key: str,
    ) -> None:
        super().__init__()
        self.jobs = jobs
        self.settings = settings
        self.output_dir = output_dir
        self.database_path = database_path
        self.project_key = project_key
        self._paused = threading.Event()
        self._paused.set()
        self._stop_event = threading.Event()
        self._provider = None

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
        cancel = getattr(self._provider, "cancel", None)
        if callable(cancel):
            cancel()
        # Release a paused worker immediately so it can observe the stop flag.
        self._paused.set()
        self.log.emit("Stop requested. Finishing the current provider request, if any…")

    def _wait_until_runnable(self) -> bool:
        """Wait while paused and return False when a stop was requested."""
        while not self._stop_event.is_set():
            if self._paused.wait(timeout=0.05):
                return not self._stop_event.is_set()
        return False

    def _interruptible_delay(self, seconds: float) -> bool:
        """Wait between files; return False when interrupted by Stop."""
        if seconds <= 0:
            return not self._stop_event.is_set()
        return not self._stop_event.wait(timeout=seconds)

    @Slot()
    def run(self) -> None:
        summary = {
            "total": len(self.jobs),
            "completed": 0,
            "skipped": 0,
            "failed": 0,
            "stopped": False,
            "stop_reason": None,
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
        provider = None

        try:
            provider = create_provider(self.settings)
            self._provider = provider
            for index, job in enumerate(self.jobs, 1):
                if not self._wait_until_runnable():
                    summary["stopped"] = True
                    summary["stop_reason"] = "user"
                    break

                extension = ".wav" if self.settings.provider in {"mock", "piper"} else self.settings.file_extension
                output_path = job.output_path(self.output_dir, extension)

                if db.status_for(self.project_key, job) == "completed" and output_path.exists():
                    summary["skipped"] += 1
                    self.progress.emit(index, len(self.jobs), str(output_path), "skipped", 0, job.retry_count, "")
                    continue

                if output_path.exists() and self.settings.skip_existing:
                    db.mark_result(self.project_key, job, "skipped")
                    summary["skipped"] += 1
                    self.progress.emit(index, len(self.jobs), str(output_path), "skipped", 0, job.retry_count, "")
                    continue

                started = time.perf_counter()
                try:
                    attempt = job.retry_count + 1
                    db.mark_running(self.project_key, job)
                    self.progress.emit(index, len(self.jobs), job.filename, "running", 0, attempt, "")
                    prepared = PronunciationService().prepare_job(job, self.settings)
                    if prepared.aid_applied:
                        summary["provider_diagnostics"].setdefault("pronunciation_aid", 0)
                        summary["provider_diagnostics"]["pronunciation_aid"] += 1
                    audio = provider.synthesize(prepared.provider_text, self.settings)
                    if self._stop_event.is_set():
                        raise ProviderError("Generation cancelled by user.", provider_code="cancelled")
                    self._write_atomic(output_path, audio)
                    duration = time.perf_counter() - started
                    db.mark_result(self.project_key, job, "completed", duration)
                    summary["completed"] += 1
                    self.progress.emit(index, len(self.jobs), str(output_path), "completed", duration, attempt, "")
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
                    summary["provider_diagnostics"]["last_error"] = self._error_info(exc)
                    db.mark_result(self.project_key, job, "failed", duration, error)
                    summary["failed"] += 1
                    self.progress.emit(index, len(self.jobs), job.filename, "failed", duration, job.retry_count + 1, error)
                    self.log.emit(f"ERROR {job.filename}: {error}")

                # A stop pressed during synthesize takes effect immediately
                # after the current provider request has completed.
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
            self.finished.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
            summary["provider_diagnostics"]["temporary_files_cleaned"] += self._cleanup_temporary_files()
            db.close()

    def _write_atomic(self, output_path: Path, audio: bytes) -> None:
        if not audio:
            raise ProviderError("Provider returned empty audio.", retryable=True, provider_code="empty_audio")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_bytes(audio)
            if temp_path.stat().st_size <= 0:
                raise ProviderError("Provider returned empty audio.", retryable=True, provider_code="empty_audio")
            temp_path.replace(output_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

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
        return isinstance(exc, ProviderError) and (exc.provider_code == "cancelled" or "cancelled" in str(exc).lower())

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
