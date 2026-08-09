from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

from app.models.domain import JobStatus, TTSJob
from app.models.queue_batch_operations import QueueBatchGroup, QueueBatchSnapshot


class QueueBatchOperationsService:
    """Read-only planning helpers for large queue operations.

    The service never mutates jobs, order, scope or retry state.  It returns
    stable row identities that MainWindow can pass to the existing queue view
    and existing mutation commands.
    """

    GROUPS = {"status", "provider", "voice"}
    LENSES = {"all", "pending", "failed", "selected", "quota"}

    def snapshot(
        self,
        jobs: Sequence[TTSJob],
        *,
        selected_rows: Iterable[int] = (),
        quota_remaining: int | None = None,
        group_by: str = "status",
        default_provider: str = "",
        default_voice: str = "",
    ) -> QueueBatchSnapshot:
        selected = {int(row) for row in selected_rows}
        visible = list(jobs)
        quota_jobs = self.lens_jobs(
            "quota",
            visible,
            selected_rows=selected,
            quota_remaining=quota_remaining,
        )
        normalized_group = group_by if group_by in self.GROUPS else "status"
        groups = self._groups(
            visible,
            normalized_group,
            default_provider=default_provider,
            default_voice=default_voice,
        )
        return QueueBatchSnapshot(
            visible_jobs=len(visible),
            visible_characters=sum(job.character_count for job in visible),
            selected_jobs=sum(1 for job in visible if job.row_number in selected),
            selected_characters=sum(
                job.character_count for job in visible if job.row_number in selected
            ),
            pending_jobs=sum(1 for job in visible if job.status == JobStatus.PENDING),
            failed_jobs=sum(1 for job in visible if job.status == JobStatus.FAILED),
            quota_jobs=len(quota_jobs),
            quota_characters=sum(job.character_count for job in quota_jobs),
            group_by=normalized_group,
            groups=groups,
        )

    def lens_job_ids(
        self,
        lens: str,
        jobs: Sequence[TTSJob],
        *,
        selected_rows: Iterable[int] = (),
        quota_remaining: int | None = None,
    ) -> tuple[int, ...]:
        return tuple(
            int(job.row_number)
            for job in self.lens_jobs(
                lens,
                jobs,
                selected_rows=selected_rows,
                quota_remaining=quota_remaining,
            )
        )

    def lens_jobs(
        self,
        lens: str,
        jobs: Sequence[TTSJob],
        *,
        selected_rows: Iterable[int] = (),
        quota_remaining: int | None = None,
    ) -> list[TTSJob]:
        normalized = lens if lens in self.LENSES else "all"
        visible = list(jobs)
        if normalized == "all":
            return visible
        if normalized == "pending":
            return [job for job in visible if job.status == JobStatus.PENDING]
        if normalized == "failed":
            return [job for job in visible if job.status == JobStatus.FAILED]
        if normalized == "selected":
            selected = {int(row) for row in selected_rows}
            return [job for job in visible if job.row_number in selected]
        if quota_remaining is None or quota_remaining <= 0:
            return []
        result: list[TTSJob] = []
        used = 0
        for job in visible:
            if job.status != JobStatus.PENDING:
                continue
            next_used = used + job.character_count
            if next_used > quota_remaining:
                break
            result.append(job)
            used = next_used
        return result

    @staticmethod
    def _groups(
        jobs: Sequence[TTSJob],
        group_by: str,
        *,
        default_provider: str,
        default_voice: str,
    ) -> tuple[QueueBatchGroup, ...]:
        buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        labels: dict[str, str] = {}
        for job in jobs:
            if group_by == "provider":
                label = (job.provider_override or default_provider or "Unassigned").strip()
            elif group_by == "voice":
                label = (job.voice_override or default_voice or "Unassigned").strip()
            else:
                label = job.status.value.title()
            key = label.casefold()
            buckets[key][0] += 1
            buckets[key][1] += job.character_count
            labels[key] = label
        ordered = sorted(buckets, key=lambda key: (-buckets[key][0], labels[key].casefold()))
        return tuple(
            QueueBatchGroup(
                key=key,
                label=labels[key],
                job_count=buckets[key][0],
                character_count=buckets[key][1],
            )
            for key in ordered
        )
