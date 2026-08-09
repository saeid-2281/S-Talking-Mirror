from __future__ import annotations

from pathlib import Path

from app.database.connection import Database
from app.models.product_events import BatchSessionRecord
from app.models.project_session_workflow import (
    ProjectContinuationSummary,
    ProjectRunSummary,
    ProjectSessionWorkflowSnapshot,
    SessionContinuationSummary,
)
from app.models.persistence import ProjectRecord
from app.repositories import ProjectRepository
from app.repositories.product_event_repository import ProductEventRepository
from app.services.startup_recovery_service import SessionRestoreService


class ProjectSessionWorkflowService:
    """Read-only project/session continuity view over existing persistence.

    Phase 95 deliberately does not create a second session store. It combines
    existing project records, saved queue state, batch history and the existing
    SessionRestoreService so the UI can offer explicit continuation actions.
    """

    def __init__(
        self,
        database: Database,
        project_repository: ProjectRepository,
        product_event_repository: ProductEventRepository,
        session_restore_service: SessionRestoreService,
    ) -> None:
        self.database = database
        self.projects = project_repository
        self.product_events = product_event_repository
        self.session_restore = session_restore_service

    def snapshot(self, *, limit: int = 10) -> ProjectSessionWorkflowSnapshot:
        recent = tuple(self._project_summary(project) for project in self.projects.list_recent(limit))
        return ProjectSessionWorkflowSnapshot(session=self.session_summary(), projects=recent)

    def session_summary(self) -> SessionContinuationSummary:
        state = self.session_restore.load()
        path = state.last_project_path
        record = self.projects.get_by_project_file(str(path)) if path else None
        return SessionContinuationSummary(
            auto_restore_enabled=state.auto_restore_enabled,
            project_path=str(path) if path else None,
            project_name=record.name if record else (path.stem if path else None),
            project_id=record.id if record else None,
            project_exists=bool(path and path.exists()),
            queue_filter=state.queue_filter,
            selected_row=state.selected_row,
        )

    def project_summary(self, project_id: int) -> ProjectContinuationSummary | None:
        record = self.projects.get_by_id(project_id)
        return self._project_summary(record) if record else None

    def recent_runs(self, project_id: int, *, limit: int = 12) -> tuple[ProjectRunSummary, ...]:
        return tuple(
            self._run_summary(record)
            for record in self.product_events.list_batch_sessions(project_id=project_id, limit=limit)
        )

    def _project_summary(self, project: ProjectRecord) -> ProjectContinuationSummary:
        counts = self._job_counts(project.id)
        runs = self.product_events.list_batch_sessions(project_id=project.id, limit=1)
        project_path = Path(project.project_file) if project.project_file else None
        source_path = Path(project.csv_path) if project.csv_path else None
        output_path = Path(project.output_path) if project.output_path else None
        return ProjectContinuationSummary(
            project_id=project.id,
            name=project.name,
            project_file=project.project_file,
            csv_path=project.csv_path,
            output_path=project.output_path,
            provider=project.provider,
            last_opened_at=project.last_opened_at or project.updated_at,
            project_file_exists=bool(project_path and project_path.exists()),
            source_exists=bool(source_path and source_path.exists()),
            output_exists=bool(output_path and output_path.exists()),
            saved_jobs=sum(counts.values()),
            pending_jobs=counts.get("pending", 0),
            completed_jobs=counts.get("completed", 0),
            failed_jobs=counts.get("failed", 0),
            skipped_jobs=counts.get("skipped", 0),
            latest_run=self._run_summary(runs[0]) if runs else None,
            latest_audio_path=self._latest_audio_path(project.id),
        )

    def _job_counts(self, project_id: int) -> dict[str, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs WHERE project_id = ? GROUP BY status",
                (project_id,),
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def _latest_audio_path(self, project_id: int) -> str | None:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT output_path FROM jobs
                WHERE project_id = ? AND status = 'completed' AND output_path IS NOT NULL
                ORDER BY COALESCE(completed_at, updated_at) DESC, row_number DESC
                LIMIT 50
                """,
                (project_id,),
            ).fetchall()
        for row in rows:
            candidate = Path(str(row["output_path"]))
            if candidate.is_file():
                return str(candidate)
        return None

    @staticmethod
    def _run_summary(record: BatchSessionRecord) -> ProjectRunSummary:
        return ProjectRunSummary(
            session_id=record.session_id,
            project_id=record.project_id,
            result=record.result,
            provider=record.provider,
            model=record.model,
            voice=record.voice,
            completed_jobs=record.completed_jobs,
            failed_jobs=record.failed_jobs,
            skipped_jobs=record.skipped_jobs,
            total_jobs=record.total_jobs,
            started_at=record.started_at,
            finished_at=record.finished_at,
            elapsed_seconds=record.elapsed_seconds,
            output_path=record.output_path,
            report_path=record.report_path,
        )
