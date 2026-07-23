from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardState:
    total_files: int = 0
    total_characters: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    pending: int = 0
    estimated_seconds: float = 0.0
    elapsed_seconds: float = 0.0

    @property
    def estimated_minutes(self) -> float:
        return self.estimated_seconds / 60 if self.estimated_seconds else 0.0
