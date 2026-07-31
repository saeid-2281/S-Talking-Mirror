from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.domain import JobStatus, TTSJob


@dataclass(frozen=True)
class GenerationSession:
    """Serializable live summary of one generation run."""

    session_id: str
    status: str
    started_at: str
    updated_at: str
    total_jobs: int
    pending_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    skipped_jobs: int
    retried_jobs: int
    processed_jobs: int
    total_characters: int
    processed_characters: int
    elapsed_seconds: float
    active_seconds: float
    jobs_per_minute: float
    characters_per_second: float
    eta_seconds: float
    progress_percent: float
    stalled: bool = False

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        status: str,
        started_at: str,
        jobs: list[TTSJob],
        elapsed_seconds: float,
        active_seconds: float,
        retried_jobs: int,
        jobs_per_minute: float,
        characters_per_second: float,
        eta_seconds: float,
        stalled: bool,
    ) -> "GenerationSession":
        pending = sum(job.status == JobStatus.PENDING for job in jobs)
        running = sum(job.status == JobStatus.RUNNING for job in jobs)
        completed = sum(job.status == JobStatus.COMPLETED for job in jobs)
        failed = sum(job.status == JobStatus.FAILED for job in jobs)
        skipped = sum(job.status == JobStatus.SKIPPED for job in jobs)
        processed = completed + failed + skipped
        total_characters = sum(job.character_count for job in jobs)
        processed_characters = sum(
            job.character_count
            for job in jobs
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.SKIPPED}
        )
        total_jobs = len(jobs)
        progress = (processed / total_jobs * 100.0) if total_jobs else 0.0
        return cls(
            session_id=session_id,
            status=status,
            started_at=started_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
            total_jobs=total_jobs,
            pending_jobs=pending,
            running_jobs=running,
            completed_jobs=completed,
            failed_jobs=failed,
            skipped_jobs=skipped,
            retried_jobs=max(0, retried_jobs),
            processed_jobs=processed,
            total_characters=total_characters,
            processed_characters=processed_characters,
            elapsed_seconds=max(0.0, elapsed_seconds),
            active_seconds=max(0.0, active_seconds),
            jobs_per_minute=max(0.0, jobs_per_minute),
            characters_per_second=max(0.0, characters_per_second),
            eta_seconds=max(0.0, eta_seconds),
            progress_percent=max(0.0, min(100.0, progress)),
            stalled=bool(stalled),
        )
