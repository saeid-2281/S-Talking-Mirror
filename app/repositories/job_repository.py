from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.domain import JobStatus, TTSJob
from app.models.retry_policy import FailureCategory, RetryHistoryEntry
from app.models.persistence import JobRecord


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_jobs(
        self,
        project_id: int,
        jobs: list[TTSJob],
        *,
        output_dir: Path | None = None,
        extension: str = ".wav",
    ) -> None:
        now = self._now()
        rows = [
            (
                project_id,
                job.row_number,
                job.filename,
                job.text,
                self._text_hash(job.text),
                job.status.value,
                job.retry_count,
                job.error,
                job.failure_category.value if job.failure_category else None,
                job.error_code,
                job.error_fingerprint,
                None if job.retryable is None else int(job.retryable),
                int(job.retry_exhausted),
                job.next_retry_at,
                json.dumps([entry.model_dump(mode="json") for entry in job.retry_history], ensure_ascii=False),
                job.duration_seconds,
                str(job.output_path(output_dir, extension)) if output_dir else job.generated_output_path,
                job.source_id,
                job.source_display_name,
                job.source_sheet,
                job.source_row,
                job.provider_override,
                job.account_profile_override,
                job.voice_override,
                job.model_override,
                job.language_override,
                job.output_subfolder,
                now,
                now if job.status == JobStatus.COMPLETED else None,
                now,
            )
            for job in jobs
        ]
        with self.database.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO jobs(
                    project_id, row_number, filename, text, text_hash, status,
                    retry_count, error, failure_category, error_code, error_fingerprint, retryable,
                    retry_exhausted, next_retry_at, retry_history_json, duration_seconds, output_path, source_id, source_display_name,
                    source_sheet, source_row, provider_override, account_profile_override, voice_override,
                    model_override, language_override, output_subfolder, created_at, completed_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, row_number) DO UPDATE SET
                    filename = excluded.filename,
                    text = excluded.text,
                    text_hash = excluded.text_hash,
                    source_id = excluded.source_id,
                    source_display_name = excluded.source_display_name,
                    source_sheet = excluded.source_sheet,
                    source_row = excluded.source_row,
                    provider_override = excluded.provider_override,
                    account_profile_override = excluded.account_profile_override,
                    voice_override = excluded.voice_override,
                    model_override = excluded.model_override,
                    language_override = excluded.language_override,
                    output_subfolder = excluded.output_subfolder,
                    output_path = COALESCE(jobs.output_path, excluded.output_path),
                    status = CASE
                        WHEN jobs.text_hash != excluded.text_hash THEN 'pending'
                        ELSE jobs.status
                    END,
                    retry_count = CASE
                        WHEN jobs.text_hash != excluded.text_hash THEN 0
                        ELSE jobs.retry_count
                    END,
                    error = CASE
                        WHEN jobs.text_hash != excluded.text_hash THEN NULL
                        ELSE jobs.error
                    END,
                    failure_category = CASE WHEN jobs.text_hash != excluded.text_hash THEN NULL ELSE jobs.failure_category END,
                    error_code = CASE WHEN jobs.text_hash != excluded.text_hash THEN NULL ELSE jobs.error_code END,
                    error_fingerprint = CASE WHEN jobs.text_hash != excluded.text_hash THEN NULL ELSE jobs.error_fingerprint END,
                    retryable = CASE WHEN jobs.text_hash != excluded.text_hash THEN NULL ELSE jobs.retryable END,
                    retry_exhausted = CASE WHEN jobs.text_hash != excluded.text_hash THEN 0 ELSE jobs.retry_exhausted END,
                    next_retry_at = CASE WHEN jobs.text_hash != excluded.text_hash THEN NULL ELSE jobs.next_retry_at END,
                    retry_history_json = CASE WHEN jobs.text_hash != excluded.text_hash THEN '[]' ELSE jobs.retry_history_json END,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def list_by_project(self, project_id: int) -> list[JobRecord]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE project_id = ?
                ORDER BY row_number
                """,
                (project_id,),
            ).fetchall()
        return [JobRecord.from_row(row) for row in rows]

    def restore_jobs(self, project_id: int, *, output_dir: Path | None = None) -> list[TTSJob]:
        self.reset_interrupted(project_id)
        records = self.list_by_project(project_id)
        jobs = [self._job_from_record(record) for record in records]
        if output_dir:
            self.reset_missing_completed_outputs(project_id, jobs)
            records = self.list_by_project(project_id)
            jobs = [self._job_from_record(record) for record in records]
        return jobs

    def reset_interrupted(self, project_id: int) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'pending', updated_at = ?
                WHERE project_id = ? AND status = 'running'
                """,
                (self._now(), project_id),
            )

    def reset_all_interrupted(self) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'pending', updated_at = ?
                WHERE status = 'running'
                """,
                (self._now(),),
            )
            return int(cursor.rowcount or 0)

    def reset_missing_completed_outputs(self, project_id: int, jobs: list[TTSJob]) -> None:
        missing_rows = [
            job.row_number
            for job in jobs
            if job.status == JobStatus.COMPLETED
            and job.generated_output_path
            and not Path(job.generated_output_path).exists()
        ]
        if missing_rows:
            self.reset_rows(project_id, missing_rows)

    def mark_running(self, project_id: int, job: TTSJob) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    retry_count = retry_count + 1,
                    error = NULL,
                    next_retry_at = NULL,
                    retry_history_json = ?,
                    updated_at = ?
                WHERE project_id = ? AND row_number = ?
                """,
                (
                    json.dumps([entry.model_dump(mode="json") for entry in job.retry_history], ensure_ascii=False),
                    self._now(),
                    project_id,
                    job.row_number,
                ),
            )

    def mark_result(
        self,
        project_id: int,
        job: TTSJob,
        status: JobStatus,
        *,
        duration_seconds: float = 0.0,
        error: str | None = None,
        output_path: Path | str | None = None,
    ) -> None:
        completed_at = self._now() if status == JobStatus.COMPLETED else None
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?,
                    duration_seconds = ?,
                    error = ?,
                    failure_category = ?,
                    error_code = ?,
                    error_fingerprint = ?,
                    retryable = ?,
                    retry_exhausted = ?,
                    next_retry_at = ?,
                    retry_history_json = ?,
                    output_path = COALESCE(?, output_path),
                    completed_at = ?,
                    updated_at = ?
                WHERE project_id = ? AND row_number = ?
                """,
                (
                    status.value,
                    duration_seconds,
                    error,
                    job.failure_category.value if job.failure_category else None,
                    job.error_code,
                    job.error_fingerprint,
                    None if job.retryable is None else int(job.retryable),
                    int(job.retry_exhausted),
                    job.next_retry_at,
                    json.dumps([entry.model_dump(mode="json") for entry in job.retry_history], ensure_ascii=False),
                    str(output_path) if output_path else None,
                    completed_at,
                    self._now(),
                    project_id,
                    job.row_number,
                ),
            )

    def reset_rows(self, project_id: int, row_numbers: list[int]) -> None:
        if not row_numbers:
            return
        placeholders = ",".join("?" for _ in row_numbers)
        with self.database.transaction() as connection:
            connection.execute(
                f"""
                UPDATE jobs
                SET status = 'pending',
                    retry_count = 0,
                    error = NULL,
                    failure_category = NULL,
                    error_code = NULL,
                    error_fingerprint = NULL,
                    retryable = NULL,
                    retry_exhausted = 0,
                    next_retry_at = NULL,
                    retry_history_json = '[]',
                    duration_seconds = 0,
                    output_path = NULL,
                    completed_at = NULL,
                    updated_at = ?
                WHERE project_id = ? AND row_number IN ({placeholders})
                """,
                (self._now(), project_id, *row_numbers),
            )

    def update_retry_state(self, project_id: int, jobs: list[TTSJob]) -> None:
        if not jobs:
            return
        with self.database.transaction() as connection:
            connection.executemany(
                """
                UPDATE jobs
                SET status = ?,
                    error = ?,
                    failure_category = ?,
                    error_code = ?,
                    error_fingerprint = ?,
                    retryable = ?,
                    retry_exhausted = ?,
                    next_retry_at = ?,
                    retry_history_json = ?,
                    updated_at = ?
                WHERE project_id = ? AND row_number = ?
                """,
                [
                    (
                        job.status.value,
                        job.error,
                        job.failure_category.value if job.failure_category else None,
                        job.error_code,
                        job.error_fingerprint,
                        None if job.retryable is None else int(job.retryable),
                        int(job.retry_exhausted),
                        job.next_retry_at,
                        json.dumps([entry.model_dump(mode="json") for entry in job.retry_history], ensure_ascii=False),
                        self._now(),
                        project_id,
                        job.row_number,
                    )
                    for job in jobs
                ],
            )

    def skip_rows(self, project_id: int, row_numbers: list[int]) -> None:
        if not row_numbers:
            return
        placeholders = ",".join("?" for _ in row_numbers)
        with self.database.transaction() as connection:
            connection.execute(
                f"""
                UPDATE jobs
                SET status = 'skipped',
                    error = NULL,
                    updated_at = ?
                WHERE project_id = ? AND row_number IN ({placeholders})
                """,
                (self._now(), project_id, *row_numbers),
            )

    def delete_completed(self, project_id: int, row_numbers: list[int]) -> None:
        if not row_numbers:
            return
        placeholders = ",".join("?" for _ in row_numbers)
        with self.database.transaction() as connection:
            connection.execute(
                f"""
                DELETE FROM jobs
                WHERE project_id = ? AND status = 'completed' AND row_number IN ({placeholders})
                """,
                (project_id, *row_numbers),
            )

    def average_completed_duration(self, project_id: int | None = None) -> float | None:
        with self.database.connect() as connection:
            if project_id is None:
                row = connection.execute(
                    """
                    SELECT AVG(duration_seconds) AS average
                    FROM jobs
                    WHERE status = 'completed'
                      AND duration_seconds IS NOT NULL
                      AND duration_seconds > 0
                    """,
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT AVG(duration_seconds) AS average
                    FROM jobs
                    WHERE project_id = ?
                      AND status = 'completed'
                      AND duration_seconds IS NOT NULL
                      AND duration_seconds > 0
                    """,
                    (project_id,),
                ).fetchone()
        average = row["average"] if row else None
        return float(average) if average else None

    def _job_from_record(self, record: JobRecord) -> TTSJob:
        return TTSJob(
            row_number=record.row_number,
            filename=record.filename,
            text=record.text,
            status=JobStatus(record.status),
            error=record.error,
            retry_count=record.retry_count,
            failure_category=self._failure_category(record.failure_category),
            error_code=record.error_code,
            error_fingerprint=record.error_fingerprint,
            retryable=None if record.retryable is None else bool(record.retryable),
            retry_exhausted=bool(record.retry_exhausted),
            next_retry_at=record.next_retry_at,
            retry_history=self._retry_history(record.retry_history_json),
            duration_seconds=record.duration_seconds or 0.0,
            generated_output_path=record.output_path,
            source_id=getattr(record, "source_id", None),
            source_display_name=getattr(record, "source_display_name", None),
            source_sheet=getattr(record, "source_sheet", None),
            source_row=getattr(record, "source_row", None),
            provider_override=getattr(record, "provider_override", None),
            account_profile_override=getattr(record, "account_profile_override", None),
            voice_override=getattr(record, "voice_override", None),
            model_override=getattr(record, "model_override", None),
            language_override=getattr(record, "language_override", None),
            output_subfolder=getattr(record, "output_subfolder", None),
        )

    @staticmethod
    def _failure_category(value: str | None) -> FailureCategory | None:
        if not value:
            return None
        try:
            return FailureCategory(value)
        except ValueError:
            return FailureCategory.UNKNOWN

    @staticmethod
    def _retry_history(value: str | None) -> list[RetryHistoryEntry]:
        try:
            raw = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        history: list[RetryHistoryEntry] = []
        for item in raw:
            try:
                history.append(RetryHistoryEntry.model_validate(item))
            except (TypeError, ValueError):
                continue
        return history

    @staticmethod
    def _text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
