from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationLiveSnapshot:
    run_id: str
    state: str
    total: int
    processed: int
    completed: int
    failed: int
    pending: int
    running: int
    skipped: int
    retries: int
    retryable_failed: int
    percent: int
    eta_seconds: float
    average_seconds: float
    current_filename: str
    current_status: str
    latest_output: str
    active: bool
    paused: bool

    @property
    def progress_text(self) -> str:
        return f"{self.processed:,} / {self.total:,} · {self.percent}%" if self.total else "No active queue"

    @property
    def eta_confidence(self) -> str:
        if self.completed >= 10:
            return "high"
        if self.completed >= 3:
            return "medium"
        return "low"

    @property
    def can_pause(self) -> bool:
        return self.active

    @property
    def can_stop(self) -> bool:
        return self.active

    @property
    def can_retry(self) -> bool:
        return (not self.active) and self.retryable_failed > 0

    @property
    def can_review_failures(self) -> bool:
        return self.failed > 0

    @property
    def can_open_output(self) -> bool:
        return bool(self.latest_output)
