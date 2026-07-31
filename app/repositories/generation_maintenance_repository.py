from __future__ import annotations

import json
from datetime import datetime, timezone

from app.database.connection import Database
from app.models.generation_maintenance import (
    GenerationMaintenancePolicy,
    GenerationMaintenanceRun,
)


class GenerationMaintenanceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_policy(
        self,
        policy: GenerationMaintenancePolicy,
    ) -> GenerationMaintenancePolicy:
        updated_at = policy.updated_at or self._now()
        policy_key = self._policy_key(policy.project_id)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO generation_maintenance_policies(
                    policy_key, project_id, enabled, session_retention_days,
                    notification_retention_days, activity_retention_days,
                    snapshot_retention_days, maintenance_run_retention_days,
                    backup_retention_count, run_quick_check_on_startup, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    session_retention_days = excluded.session_retention_days,
                    notification_retention_days = excluded.notification_retention_days,
                    activity_retention_days = excluded.activity_retention_days,
                    snapshot_retention_days = excluded.snapshot_retention_days,
                    maintenance_run_retention_days = excluded.maintenance_run_retention_days,
                    backup_retention_count = excluded.backup_retention_count,
                    run_quick_check_on_startup = excluded.run_quick_check_on_startup,
                    updated_at = excluded.updated_at
                """,
                (
                    policy_key,
                    policy.project_id,
                    int(policy.enabled),
                    max(1, int(policy.session_retention_days)),
                    max(1, int(policy.notification_retention_days)),
                    max(1, int(policy.activity_retention_days)),
                    max(1, int(policy.snapshot_retention_days)),
                    max(1, int(policy.maintenance_run_retention_days)),
                    max(1, int(policy.backup_retention_count)),
                    int(policy.run_quick_check_on_startup),
                    updated_at,
                ),
            )
        return GenerationMaintenancePolicy(
            project_id=policy.project_id,
            enabled=bool(policy.enabled),
            session_retention_days=max(1, int(policy.session_retention_days)),
            notification_retention_days=max(
                1,
                int(policy.notification_retention_days),
            ),
            activity_retention_days=max(1, int(policy.activity_retention_days)),
            snapshot_retention_days=max(1, int(policy.snapshot_retention_days)),
            maintenance_run_retention_days=max(
                1,
                int(policy.maintenance_run_retention_days),
            ),
            backup_retention_count=max(1, int(policy.backup_retention_count)),
            run_quick_check_on_startup=bool(policy.run_quick_check_on_startup),
            updated_at=updated_at,
        )

    def get_policy(self, project_id: int | None) -> GenerationMaintenancePolicy | None:
        keys = [self._policy_key(project_id)]
        if project_id is not None:
            keys.append(self._policy_key(None))
        placeholders = ",".join("?" for _item in keys)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM generation_maintenance_policies
                WHERE policy_key IN ({placeholders})
                """,
                tuple(keys),
            ).fetchall()
        by_key = {str(row["policy_key"]): row for row in rows}
        selected = by_key.get(keys[0]) or (
            by_key.get(self._policy_key(None)) if project_id is not None else None
        )
        if selected is None:
            return None
        return self._policy_from_row(selected, requested_project_id=project_id)

    def add_run(self, run: GenerationMaintenanceRun) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO generation_maintenance_runs(
                    run_id, project_id, operation, status, started_at, finished_at,
                    summary_json, artifact_path, artifact_sha256
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    finished_at = excluded.finished_at,
                    summary_json = excluded.summary_json,
                    artifact_path = excluded.artifact_path,
                    artifact_sha256 = excluded.artifact_sha256
                """,
                (
                    run.run_id,
                    run.project_id,
                    run.operation,
                    run.status,
                    run.started_at,
                    run.finished_at,
                    json.dumps(run.summary, ensure_ascii=False, sort_keys=True),
                    run.artifact_path,
                    run.artifact_sha256,
                ),
            )

    def list_runs(
        self,
        *,
        project_id: int | None = None,
        limit: int = 100,
    ) -> list[GenerationMaintenanceRun]:
        query = "SELECT * FROM generation_maintenance_runs"
        parameters: list[object] = []
        if project_id is not None:
            query += " WHERE project_id = ?"
            parameters.append(project_id)
        query += " ORDER BY started_at DESC LIMIT ?"
        parameters.append(max(1, int(limit)))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [self._run_from_row(row) for row in rows]

    def delete_runs_before(
        self,
        cutoff: str,
        *,
        project_id: int | None = None,
    ) -> int:
        query = "DELETE FROM generation_maintenance_runs WHERE started_at < ?"
        parameters: list[object] = [cutoff]
        if project_id is not None:
            query += " AND project_id = ?"
            parameters.append(project_id)
        with self.database.transaction() as connection:
            cursor = connection.execute(query, tuple(parameters))
            return int(cursor.rowcount or 0)

    @staticmethod
    def _policy_key(project_id: int | None) -> str:
        return "global" if project_id is None else f"project:{project_id}"

    @staticmethod
    def _policy_from_row(
        row: object,
        *,
        requested_project_id: int | None,
    ) -> GenerationMaintenancePolicy:
        return GenerationMaintenancePolicy(
            project_id=requested_project_id,
            enabled=bool(row["enabled"]),
            session_retention_days=int(row["session_retention_days"]),
            notification_retention_days=int(row["notification_retention_days"]),
            activity_retention_days=int(row["activity_retention_days"]),
            snapshot_retention_days=int(row["snapshot_retention_days"]),
            maintenance_run_retention_days=int(
                row["maintenance_run_retention_days"]
            ),
            backup_retention_count=int(row["backup_retention_count"]),
            run_quick_check_on_startup=bool(row["run_quick_check_on_startup"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _run_from_row(row: object) -> GenerationMaintenanceRun:
        try:
            summary = json.loads(str(row["summary_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            summary = {}
        return GenerationMaintenanceRun(
            run_id=str(row["run_id"]),
            project_id=row["project_id"],
            operation=str(row["operation"]),
            status=str(row["status"]),
            started_at=str(row["started_at"]),
            finished_at=row["finished_at"],
            summary=summary if isinstance(summary, dict) else {},
            artifact_path=row["artifact_path"],
            artifact_sha256=row["artifact_sha256"],
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
