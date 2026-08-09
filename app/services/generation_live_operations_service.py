from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.models.domain import TTSJob
from app.models.generation_live_operations import GenerationLiveSnapshot


class GenerationLiveOperationsService:
    """Build a read-only live-run decision snapshot.

    This service never pauses, stops, retries, reorders, or starts generation. It only
    derives UI state from the existing generation controller, monitor state, and failure
    summary so MainWindow can route actions to the commands that already own mutation
    semantics.
    """

    def snapshot(
        self,
        jobs: Sequence[TTSJob],
        *,
        monitor_state: Any,
        active: bool,
        paused: bool,
        run_id: str = "",
        latest_output: Path | str | None = None,
        failure_summary: Mapping[str, object] | None = None,
    ) -> GenerationLiveSnapshot:
        counts = {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        }
        for job in jobs:
            status = str(getattr(getattr(job, "status", None), "value", "pending") or "pending").casefold()
            if status in counts:
                counts[status] += 1

        observed_total = self._as_int(getattr(monitor_state, "total", 0))
        total = max(observed_total, len(jobs))
        derived_processed = counts["completed"] + counts["failed"] + counts["skipped"]
        processed = max(derived_processed, self._as_int(getattr(monitor_state, "processed", 0)))
        processed = min(processed, total) if total else 0
        percent = int((processed / total) * 100) if total else 0

        retryable = self._as_int((failure_summary or {}).get("retryable", 0))
        retries = self._as_int(getattr(monitor_state, "retries", 0))
        eta = max(0.0, self._as_float(getattr(monitor_state, "remaining_eta_seconds", 0.0)))
        average = max(0.0, self._as_float(getattr(monitor_state, "average_seconds_per_completed_job", 0.0)))
        current_filename = str(getattr(monitor_state, "current_filename", "") or "")
        current_status = str(getattr(monitor_state, "current_status", "") or "")
        state = self._state(
            active=active,
            paused=paused,
            current_status=current_status,
            total=total,
            pending=counts["pending"],
            running=counts["running"],
            failed=counts["failed"],
        )
        output_text = str(latest_output or "")

        return GenerationLiveSnapshot(
            run_id=str(run_id or ""),
            state=state,
            total=total,
            processed=processed,
            completed=counts["completed"],
            failed=counts["failed"],
            pending=counts["pending"],
            running=counts["running"],
            skipped=counts["skipped"],
            retries=retries,
            retryable_failed=retryable,
            percent=percent,
            eta_seconds=eta,
            average_seconds=average,
            current_filename=current_filename,
            current_status=current_status,
            latest_output=output_text,
            active=bool(active),
            paused=bool(paused),
        )

    @staticmethod
    def _state(
        *,
        active: bool,
        paused: bool,
        current_status: str,
        total: int,
        pending: int,
        running: int,
        failed: int,
    ) -> str:
        lowered = current_status.casefold()
        if active:
            if "stop" in lowered:
                return "Stopping"
            if paused:
                return "Paused"
            return "Running"
        if total <= 0:
            return "Ready"
        if failed and pending == 0 and running == 0:
            return "Needs attention"
        if pending > 0:
            return "Ready"
        return "Completed"

    @staticmethod
    def _as_int(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _as_float(value: object) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
