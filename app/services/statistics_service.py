from __future__ import annotations

import sqlite3
from pathlib import Path

from app.models import DashboardState, JobStatus, TTSJob


class StatisticsService:
    def __init__(self, database_path: Path, fallback_seconds_per_job: float = 3.0) -> None:
        self.database_path = database_path
        self.fallback_seconds_per_job = fallback_seconds_per_job

    def dashboard_for_jobs(
        self,
        jobs: list[TTSJob],
        *,
        project_key: str | None = None,
        elapsed_seconds: float = 0.0,
    ) -> DashboardState:
        total = len(jobs)
        completed = self._count(jobs, JobStatus.COMPLETED)
        failed = self._count(jobs, JobStatus.FAILED)
        skipped = self._count(jobs, JobStatus.SKIPPED)
        pending = max(0, total - completed - failed - skipped)
        seconds_per_job = self.average_completed_duration(project_key) or self.fallback_seconds_per_job
        return DashboardState(
            total_files=total,
            total_characters=sum(len(job.text) for job in jobs),
            completed=completed,
            failed=failed,
            skipped=skipped,
            pending=pending,
            estimated_seconds=pending * seconds_per_job,
            elapsed_seconds=elapsed_seconds,
        )

    def average_completed_duration(self, project_key: str | None = None) -> float | None:
        if not self.database_path.exists():
            return None
        try:
            with sqlite3.connect(self.database_path) as connection:
                if project_key:
                    row = connection.execute(
                        """
                        SELECT AVG(duration_seconds) AS average
                        FROM jobs
                        WHERE project_key = ?
                          AND status = 'completed'
                          AND duration_seconds IS NOT NULL
                          AND duration_seconds > 0
                        """,
                        (project_key,),
                    ).fetchone()
                else:
                    row = connection.execute(
                        """
                        SELECT AVG(duration_seconds) AS average
                        FROM jobs
                        WHERE status = 'completed'
                          AND duration_seconds IS NOT NULL
                          AND duration_seconds > 0
                        """,
                    ).fetchone()
        except sqlite3.Error:
            return None
        average = row[0] if row else None
        return float(average) if average else None

    def _count(self, jobs: list[TTSJob], status: JobStatus) -> int:
        return sum(1 for job in jobs if job.status == status)
