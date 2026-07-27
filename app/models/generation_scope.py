from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models.domain import TTSJob


class GenerationScopeMode(StrEnum):
    ENTIRE_QUEUE = "entire_queue"
    CURRENT_SOURCE = "current_source"
    FILTERED = "filtered"
    SELECTED = "selected"
    ROW_RANGE = "row_range"
    DISPLAY_RANGE = "display_range"
    QUOTA_BATCH = "quota_batch"


class ExecutionOrderMode(StrEnum):
    CSV = "csv"
    FILENAME_ASC = "filename_asc"
    FILENAME_DESC = "filename_desc"
    CHARACTER_SHORTEST = "character_shortest"
    CHARACTER_LONGEST = "character_longest"
    STATUS = "status"
    CUSTOM = "custom"


@dataclass(frozen=True)
class GenerationPlan:
    jobs: tuple[TTSJob, ...]
    scope_mode: GenerationScopeMode
    execution_order: ExecutionOrderMode
    total_jobs: int
    total_characters: int
    reserved_characters: int = 0
    quota_remaining: int | None = None

    @property
    def pending_jobs(self) -> tuple[TTSJob, ...]:
        return tuple(job for job in self.jobs if job.status.value == "pending")

    @property
    def display_range(self) -> tuple[int | None, int | None]:
        if not self.jobs:
            return None, None
        rows = [job.row_number for job in self.jobs]
        return min(rows), max(rows)
