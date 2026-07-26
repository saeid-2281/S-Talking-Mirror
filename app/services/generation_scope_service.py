from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import JobStatus, TTSJob
from app.models.generation_scope import ExecutionOrderMode, GenerationPlan, GenerationScopeMode


@dataclass(frozen=True)
class QuotaBatchPreview:
    jobs: tuple[TTSJob, ...]
    required_characters: int
    remaining_characters: int | None
    reserved_characters: int
    omitted_pending_jobs: int

    @property
    def can_apply(self) -> bool:
        return bool(self.jobs)


class GenerationScopeService:
    """Builds the exact set and order of jobs used by preflight/generation/report."""

    def build_plan(
        self,
        jobs: list[TTSJob],
        *,
        scope_mode: str = "entire_queue",
        execution_order: str = "csv",
        filtered_jobs: list[TTSJob] | None = None,
        selected_rows: set[int] | None = None,
        row_range: tuple[int | None, int | None] = (None, None),
        quota_remaining: int | None = None,
    ) -> GenerationPlan:
        mode = self._scope(scope_mode)
        order = self._order(execution_order)
        scoped = self._scope_jobs(
            jobs,
            mode=mode,
            filtered_jobs=filtered_jobs,
            selected_rows=selected_rows,
            row_range=row_range,
        )
        ordered = self.order_jobs(scoped, order)
        reserved = self.quota_reserve(quota_remaining) if mode == GenerationScopeMode.QUOTA_BATCH else 0
        if mode == GenerationScopeMode.QUOTA_BATCH:
            ordered = list(self.quota_batch(ordered, quota_remaining=quota_remaining).jobs)
        return GenerationPlan(
            jobs=tuple(ordered),
            scope_mode=mode,
            execution_order=order,
            total_jobs=len(ordered),
            total_characters=sum(job.character_count for job in ordered),
            reserved_characters=reserved,
            quota_remaining=quota_remaining,
        )

    def order_jobs(self, jobs: list[TTSJob], order: ExecutionOrderMode) -> list[TTSJob]:
        if order == ExecutionOrderMode.FILENAME_ASC:
            return sorted(jobs, key=lambda job: job.filename.casefold())
        if order == ExecutionOrderMode.FILENAME_DESC:
            return sorted(jobs, key=lambda job: job.filename.casefold(), reverse=True)
        if order == ExecutionOrderMode.CHARACTER_SHORTEST:
            return sorted(jobs, key=lambda job: (job.character_count, job.row_number))
        if order == ExecutionOrderMode.CHARACTER_LONGEST:
            return sorted(jobs, key=lambda job: (job.character_count, job.row_number), reverse=True)
        if order == ExecutionOrderMode.STATUS:
            status_rank = {
                JobStatus.RUNNING: 0,
                JobStatus.PENDING: 1,
                JobStatus.FAILED: 2,
                JobStatus.SKIPPED: 3,
                JobStatus.COMPLETED: 4,
            }
            return sorted(jobs, key=lambda job: (status_rank.get(job.status, 99), job.row_number))
        if order == ExecutionOrderMode.CUSTOM:
            return sorted(jobs, key=lambda job: (job.custom_order if job.custom_order is not None else job.row_number, job.row_number))
        return sorted(jobs, key=lambda job: (job.original_order if job.original_order is not None else job.row_number, job.row_number))

    def use_current_order_as_custom(self, jobs: list[TTSJob]) -> None:
        for index, job in enumerate(jobs, 1):
            job.custom_order = index

    def move_custom(self, jobs: list[TTSJob], row_numbers: set[int], command: str) -> None:
        ordered = self.order_jobs(jobs, ExecutionOrderMode.CUSTOM)
        selected = [job for job in ordered if job.row_number in row_numbers]
        remaining = [job for job in ordered if job.row_number not in row_numbers]
        if not selected:
            return
        if command == "top":
            new_order = selected + remaining
        elif command == "bottom":
            new_order = remaining + selected
        else:
            new_order = ordered[:]
            for job in selected:
                index = new_order.index(job)
                target = index - 1 if command == "up" else index + 1
                if 0 <= target < len(new_order) and new_order[target].row_number not in row_numbers:
                    new_order[index], new_order[target] = new_order[target], new_order[index]
        self.use_current_order_as_custom(new_order)

    def quota_batch(self, jobs: list[TTSJob], *, quota_remaining: int | None) -> QuotaBatchPreview:
        pending = [job for job in jobs if job.status == JobStatus.PENDING]
        if quota_remaining is None:
            return QuotaBatchPreview(tuple(), 0, None, 0, len(pending))
        reserve = self.quota_reserve(quota_remaining)
        available = max(quota_remaining - reserve, 0)
        selected: list[TTSJob] = []
        used = 0
        for job in pending:
            if job.character_count > available - used:
                continue
            selected.append(job)
            used += job.character_count
        return QuotaBatchPreview(tuple(selected), used, quota_remaining, reserve, max(0, len(pending) - len(selected)))

    @staticmethod
    def quota_reserve(quota_remaining: int | None) -> int:
        if quota_remaining is None:
            return 0
        return max(500, int(quota_remaining * 0.02))

    def _scope_jobs(
        self,
        jobs: list[TTSJob],
        *,
        mode: GenerationScopeMode,
        filtered_jobs: list[TTSJob] | None,
        selected_rows: set[int] | None,
        row_range: tuple[int | None, int | None],
    ) -> list[TTSJob]:
        if mode == GenerationScopeMode.FILTERED:
            return list(filtered_jobs or [])
        if mode == GenerationScopeMode.SELECTED:
            return [job for job in jobs if selected_rows and job.row_number in selected_rows]
        if mode == GenerationScopeMode.ROW_RANGE:
            start, end = row_range
            scoped = jobs
            if start is not None:
                scoped = [job for job in scoped if job.row_number >= start]
            if end is not None:
                scoped = [job for job in scoped if job.row_number <= end]
            return list(scoped)
        return list(jobs)

    @staticmethod
    def _scope(value: str) -> GenerationScopeMode:
        try:
            return GenerationScopeMode(value)
        except ValueError:
            return GenerationScopeMode.ENTIRE_QUEUE

    @staticmethod
    def _order(value: str) -> ExecutionOrderMode:
        try:
            return ExecutionOrderMode(value)
        except ValueError:
            return ExecutionOrderMode.CSV
