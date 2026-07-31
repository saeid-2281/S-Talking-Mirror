from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.database.connection import Database
from app.models.generation_maintenance import (
    GenerationBackupArtifact,
    GenerationDatabaseHealth,
    GenerationHardeningDashboard,
    GenerationMaintenancePolicy,
    GenerationMaintenanceRun,
    GenerationRetentionPreview,
)
from app.repositories.generation_maintenance_repository import (
    GenerationMaintenanceRepository,
)


class GenerationMaintenanceService:
    """Database hardening, verified backups, restore, and retention operations."""

    _COUNTED_TABLES = (
        "projects",
        "jobs",
        "batch_sessions",
        "generation_incidents",
        "generation_known_problems",
        "generation_incident_reviews",
        "generation_incident_action_items",
        "generation_automated_remediations",
        "generation_reliability_snapshots",
        "generation_cost_capacity_snapshots",
        "generation_maintenance_runs",
    )

    def __init__(
        self,
        database: Database,
        repository: GenerationMaintenanceRepository,
        backup_dir: Path,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.repository = repository
        self.backup_dir = Path(backup_dir)
        self.now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self.last_startup_health: GenerationDatabaseHealth | None = None

    def default_policy(self, project_id: int | None) -> GenerationMaintenancePolicy:
        return GenerationMaintenancePolicy(project_id=project_id)

    def run_startup_check(self) -> GenerationDatabaseHealth | None:
        policy = self.get_policy(None)
        if not policy.run_quick_check_on_startup:
            self.last_startup_health = None
            return None
        try:
            self.last_startup_health = self.run_health_check()
        except sqlite3.Error:
            self.last_startup_health = None
        return self.last_startup_health

    def get_policy(self, project_id: int | None) -> GenerationMaintenancePolicy:
        return self.repository.get_policy(project_id) or self.default_policy(project_id)

    def save_policy(
        self,
        policy: GenerationMaintenancePolicy,
    ) -> GenerationMaintenancePolicy:
        normalized = replace(
            policy,
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
            updated_at=self._now().isoformat(),
        )
        return self.repository.save_policy(normalized)

    def health(self, *, full: bool = False) -> GenerationDatabaseHealth:
        checked_at = self._now().isoformat()
        applied = self.database.applied_schema_versions()
        expected = self.database.expected_schema_version
        missing = tuple(
            version for version in range(1, expected + 1) if version not in applied
        )
        issues: list[str] = []
        try:
            quick_check = self.database.quick_check(full=full)
        except sqlite3.Error as exc:
            quick_check = f"failed: {exc}"
        if quick_check != "ok":
            issues.append(f"Database integrity check returned: {quick_check}")
        try:
            foreign_keys = self.database.foreign_key_violations()
        except sqlite3.Error as exc:
            foreign_keys = ()
            issues.append(f"Foreign-key check failed: {exc}")
        if foreign_keys:
            issues.append(f"{len(foreign_keys)} foreign-key violation(s) detected")
        if missing:
            issues.append(f"Missing schema migration(s): {', '.join(map(str, missing))}")
        counts = self._table_counts()
        size = self.database.path.stat().st_size if self.database.path.exists() else 0
        return GenerationDatabaseHealth(
            database_path=self.database.path,
            database_size_bytes=size,
            schema_version=max(applied, default=0),
            expected_schema_version=expected,
            applied_versions=applied,
            missing_versions=missing,
            quick_check=quick_check,
            foreign_key_violations=foreign_keys,
            table_counts=counts,
            issues=tuple(issues),
            checked_at=checked_at,
        )

    def run_health_check(
        self,
        *,
        project_id: int | None = None,
        full: bool = False,
    ) -> GenerationDatabaseHealth:
        started_at = self._now().isoformat()
        health = self.health(full=full)
        self.repository.add_run(
            GenerationMaintenanceRun(
                run_id=f"maintenance-{uuid.uuid4().hex}",
                project_id=project_id,
                operation="integrity_check" if full else "quick_check",
                status="passed" if health.ready else "failed",
                started_at=started_at,
                finished_at=self._now().isoformat(),
                summary=self._health_payload(health),
            )
        )
        return health

    def create_backup(
        self,
        *,
        project_id: int | None = None,
        label: str = "manual",
        prune: bool = True,
    ) -> GenerationBackupArtifact:
        started_at = self._now().isoformat()
        timestamp = self._now().strftime("%Y%m%dT%H%M%S.%fZ")
        safe_label = "".join(
            character if character.isalnum() or character in {"-", "_"} else "-"
            for character in label.strip().lower()
        ).strip("-") or "manual"
        target = self.backup_dir / f"s-talking-{timestamp}-{safe_label}.db"
        self.database.backup_to(target)
        artifact = self.verify_backup(target)
        self._write_manifest(artifact, label=safe_label)
        self.repository.add_run(
            GenerationMaintenanceRun(
                run_id=f"maintenance-{uuid.uuid4().hex}",
                project_id=project_id,
                operation="backup",
                status="passed",
                started_at=started_at,
                finished_at=self._now().isoformat(),
                summary={
                    "schema_version": artifact.schema_version,
                    "size_bytes": artifact.size_bytes,
                    "quick_check": artifact.quick_check,
                },
                artifact_path=str(artifact.path),
                artifact_sha256=artifact.sha256,
            )
        )
        if prune:
            self.prune_backups(self.get_policy(project_id).backup_retention_count)
        return artifact

    def verify_backup(self, path: Path) -> GenerationBackupArtifact:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        connection = sqlite3.connect(path)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            quick_check = str(result[0]) if result else "no result"
            if quick_check != "ok":
                raise sqlite3.DatabaseError(
                    f"Backup integrity check failed: {quick_check}"
                )
            try:
                row = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()
                schema_version = int(row[0] or 0) if row else 0
            except sqlite3.Error:
                schema_version = 0
        finally:
            connection.close()
        return GenerationBackupArtifact(
            path=path,
            sha256=self._sha256(path),
            size_bytes=path.stat().st_size,
            created_at=datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(),
            schema_version=schema_version,
            quick_check=quick_check,
        )

    def restore_backup(
        self,
        source: Path,
        *,
        project_id: int | None = None,
    ) -> GenerationBackupArtifact:
        started_at = self._now().isoformat()
        source_path = Path(source)
        if source_path.resolve() == self.database.path.resolve():
            raise ValueError("The active database cannot be selected as its own backup")
        source_artifact = self.verify_backup(source_path)
        if source_artifact.schema_version > self.database.expected_schema_version:
            raise ValueError(
                "Backup schema is newer than this application supports: "
                f"{source_artifact.schema_version} > "
                f"{self.database.expected_schema_version}"
            )
        pre_restore = self.create_backup(
            project_id=project_id,
            label="pre-restore",
            prune=False,
        )
        try:
            self.database.restore_from(source_artifact.path)
            self.database.initialize()
            health = self.health(full=True)
            if not health.ready:
                raise sqlite3.DatabaseError(
                    "Restored database failed hardening validation"
                )
        except Exception:
            self.database.restore_from(pre_restore.path)
            self.database.initialize()
            raise
        self.repository.add_run(
            GenerationMaintenanceRun(
                run_id=f"maintenance-{uuid.uuid4().hex}",
                project_id=project_id,
                operation="restore",
                status="passed",
                started_at=started_at,
                finished_at=self._now().isoformat(),
                summary={
                    "restored_schema_version": source_artifact.schema_version,
                    "pre_restore_backup": str(pre_restore.path),
                },
                artifact_path=str(source_artifact.path),
                artifact_sha256=source_artifact.sha256,
            )
        )
        self.prune_backups(self.get_policy(project_id).backup_retention_count)
        return pre_restore

    def retention_preview(
        self,
        *,
        project_id: int | None = None,
        policy: GenerationMaintenancePolicy | None = None,
    ) -> GenerationRetentionPreview:
        active_policy = policy or self.get_policy(project_id)
        now = self._now()
        cutoffs = self._retention_cutoffs(active_policy, now)
        counts: dict[str, int] = {}
        with self.database.connect() as connection:
            counts["batch_sessions"] = self._count(
                connection,
                """
                SELECT COUNT(*) FROM batch_sessions
                WHERE started_at < ? AND finished_at IS NOT NULL
                  AND (incident_id IS NULL OR incident_id = '')
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_incidents
                      WHERE first_session_id = batch_sessions.session_id
                         OR latest_session_id = batch_sessions.session_id
                  )
                """,
                cutoffs["batch_sessions"],
                project_id=project_id,
            )
            counts["notifications"] = 0
            if project_id is None:
                counts["notifications"] = self._scalar_count(
                    connection,
                    "SELECT COUNT(*) FROM notifications WHERE read = 1 AND created_at < ?",
                    (cutoffs["notifications"],),
                )
            counts["activity_timeline"] = self._count(
                connection,
                "SELECT COUNT(*) FROM activity_timeline WHERE created_at < ?",
                cutoffs["activity_timeline"],
                project_id=project_id,
            )
            for table in (
                "generation_reliability_snapshots",
                "generation_cost_capacity_snapshots",
            ):
                counts[table] = self._count(
                    connection,
                    f"SELECT COUNT(*) FROM {table} WHERE created_at < ?",
                    cutoffs["snapshots"],
                    project_id=project_id,
                )
            counts["generation_maintenance_runs"] = self._count(
                connection,
                "SELECT COUNT(*) FROM generation_maintenance_runs WHERE started_at < ?",
                cutoffs["maintenance_runs"],
                project_id=project_id,
            )
        return GenerationRetentionPreview(
            project_id=project_id,
            generated_at=now.isoformat(),
            cutoffs=cutoffs,
            candidate_counts=counts,
        )

    def apply_retention(
        self,
        *,
        project_id: int | None = None,
        policy: GenerationMaintenancePolicy | None = None,
    ) -> GenerationRetentionPreview:
        active_policy = policy or self.get_policy(project_id)
        if not active_policy.enabled:
            raise ValueError("Maintenance retention is disabled for this scope")
        preview = self.retention_preview(
            project_id=project_id,
            policy=active_policy,
        )
        started_at = self._now().isoformat()
        cutoffs = preview.cutoffs
        deleted: dict[str, int] = {}
        with self.database.transaction() as connection:
            deleted["batch_sessions"] = self._delete(
                connection,
                """
                DELETE FROM batch_sessions
                WHERE started_at < ? AND finished_at IS NOT NULL
                  AND (incident_id IS NULL OR incident_id = '')
                  AND NOT EXISTS (
                      SELECT 1 FROM generation_incidents
                      WHERE first_session_id = batch_sessions.session_id
                         OR latest_session_id = batch_sessions.session_id
                  )
                """,
                cutoffs["batch_sessions"],
                project_id=project_id,
            )
            deleted["notifications"] = 0
            if project_id is None:
                cursor = connection.execute(
                    "DELETE FROM notifications WHERE read = 1 AND created_at < ?",
                    (cutoffs["notifications"],),
                )
                deleted["notifications"] = int(cursor.rowcount or 0)
            deleted["activity_timeline"] = self._delete(
                connection,
                "DELETE FROM activity_timeline WHERE created_at < ?",
                cutoffs["activity_timeline"],
                project_id=project_id,
            )
            for table in (
                "generation_reliability_snapshots",
                "generation_cost_capacity_snapshots",
            ):
                deleted[table] = self._delete(
                    connection,
                    f"DELETE FROM {table} WHERE created_at < ?",
                    cutoffs["snapshots"],
                    project_id=project_id,
                )
            deleted["generation_maintenance_runs"] = self._delete(
                connection,
                "DELETE FROM generation_maintenance_runs WHERE started_at < ?",
                cutoffs["maintenance_runs"],
                project_id=project_id,
            )
        self.repository.add_run(
            GenerationMaintenanceRun(
                run_id=f"maintenance-{uuid.uuid4().hex}",
                project_id=project_id,
                operation="retention",
                status="passed",
                started_at=started_at,
                finished_at=self._now().isoformat(),
                summary={"deleted": deleted, "cutoffs": cutoffs},
            )
        )
        self.prune_backups(active_policy.backup_retention_count)
        return GenerationRetentionPreview(
            project_id=project_id,
            generated_at=self._now().isoformat(),
            cutoffs=cutoffs,
            candidate_counts=deleted,
        )

    def dashboard(
        self,
        *,
        project_id: int | None = None,
    ) -> GenerationHardeningDashboard:
        return GenerationHardeningDashboard(
            policy=self.get_policy(project_id),
            health=self.health(),
            retention=self.retention_preview(project_id=project_id),
            recent_runs=tuple(self.repository.list_runs(project_id=project_id, limit=100)),
            backups=tuple(self.list_backups()),
        )

    def list_backups(self) -> list[GenerationBackupArtifact]:
        if not self.backup_dir.exists():
            return []
        artifacts: list[GenerationBackupArtifact] = []
        for path in sorted(
            self.backup_dir.glob("s-talking-*.db"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            try:
                artifacts.append(self.verify_backup(path))
            except (OSError, sqlite3.Error):
                continue
        return artifacts

    def prune_backups(self, retain_count: int) -> int:
        keep = max(1, int(retain_count))
        paths = sorted(
            self.backup_dir.glob("s-talking-*.db")
            if self.backup_dir.exists()
            else (),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        deleted = 0
        for path in paths[keep:]:
            manifest = path.with_suffix(path.suffix + ".json")
            path.unlink(missing_ok=True)
            manifest.unlink(missing_ok=True)
            deleted += 1
        return deleted

    def export_report(
        self,
        export_dir: Path,
        *,
        project_id: int | None = None,
    ) -> tuple[Path, Path]:
        export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)
        dashboard = self.dashboard(project_id=project_id)
        stamp = self._now().strftime("%Y%m%dT%H%M%SZ")
        json_path = export_dir / f"generation-hardening-{stamp}.json"
        csv_path = export_dir / f"generation-hardening-runs-{stamp}.csv"
        payload = {
            "policy": asdict(dashboard.policy),
            "health": self._health_payload(dashboard.health),
            "retention": asdict(dashboard.retention),
            "backups": [self._backup_payload(item) for item in dashboard.backups],
            "recent_runs": [asdict(item) for item in dashboard.recent_runs],
        }
        json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "run_id",
                    "project_id",
                    "operation",
                    "status",
                    "started_at",
                    "finished_at",
                    "artifact_path",
                    "artifact_sha256",
                    "summary_json",
                ],
            )
            writer.writeheader()
            for item in dashboard.recent_runs:
                writer.writerow(
                    {
                        "run_id": item.run_id,
                        "project_id": item.project_id,
                        "operation": item.operation,
                        "status": item.status,
                        "started_at": item.started_at,
                        "finished_at": item.finished_at,
                        "artifact_path": item.artifact_path,
                        "artifact_sha256": item.artifact_sha256,
                        "summary_json": json.dumps(
                            item.summary,
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                )
        return json_path, csv_path

    def _table_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.database.connect() as connection:
            existing = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in self._COUNTED_TABLES:
                if table not in existing:
                    continue
                counts[table] = self._scalar_count(
                    connection,
                    f"SELECT COUNT(*) FROM {table}",
                    (),
                )
        return counts

    @staticmethod
    def _count(
        connection: sqlite3.Connection,
        query: str,
        cutoff: str,
        *,
        project_id: int | None,
    ) -> int:
        if project_id is None:
            return GenerationMaintenanceService._scalar_count(
                connection,
                query,
                (cutoff,),
            )
        return GenerationMaintenanceService._scalar_count(
            connection,
            f"{query} AND project_id = ?",
            (cutoff, project_id),
        )

    @staticmethod
    def _delete(
        connection: sqlite3.Connection,
        query: str,
        cutoff: str,
        *,
        project_id: int | None,
    ) -> int:
        if project_id is None:
            cursor = connection.execute(query, (cutoff,))
        else:
            cursor = connection.execute(f"{query} AND project_id = ?", (cutoff, project_id))
        return int(cursor.rowcount or 0)

    @staticmethod
    def _scalar_count(
        connection: sqlite3.Connection,
        query: str,
        parameters: tuple[object, ...],
    ) -> int:
        row = connection.execute(query, parameters).fetchone()
        return int(row[0] or 0) if row else 0

    @staticmethod
    def _retention_cutoffs(
        policy: GenerationMaintenancePolicy,
        now: datetime,
    ) -> dict[str, str]:
        return {
            "batch_sessions": (
                now - timedelta(days=policy.session_retention_days)
            ).isoformat(),
            "notifications": (
                now - timedelta(days=policy.notification_retention_days)
            ).isoformat(),
            "activity_timeline": (
                now - timedelta(days=policy.activity_retention_days)
            ).isoformat(),
            "snapshots": (
                now - timedelta(days=policy.snapshot_retention_days)
            ).isoformat(),
            "maintenance_runs": (
                now - timedelta(days=policy.maintenance_run_retention_days)
            ).isoformat(),
        }

    def _write_manifest(
        self,
        artifact: GenerationBackupArtifact,
        *,
        label: str,
    ) -> None:
        manifest = artifact.path.with_suffix(artifact.path.suffix + ".json")
        manifest.write_text(
            json.dumps(
                {
                    **self._backup_payload(artifact),
                    "label": label,
                    "expected_schema_version": self.database.expected_schema_version,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _health_payload(health: GenerationDatabaseHealth) -> dict[str, object]:
        return {
            "database_path": str(health.database_path),
            "database_size_bytes": health.database_size_bytes,
            "schema_version": health.schema_version,
            "expected_schema_version": health.expected_schema_version,
            "applied_versions": list(health.applied_versions),
            "missing_versions": list(health.missing_versions),
            "quick_check": health.quick_check,
            "foreign_key_violations": list(health.foreign_key_violations),
            "table_counts": health.table_counts,
            "issues": list(health.issues),
            "checked_at": health.checked_at,
            "ready": health.ready,
        }

    @staticmethod
    def _backup_payload(artifact: GenerationBackupArtifact) -> dict[str, object]:
        return {
            "path": str(artifact.path),
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "created_at": artifact.created_at,
            "schema_version": artifact.schema_version,
            "quick_check": artifact.quick_check,
        }

    def _now(self) -> datetime:
        value = self.now_factory()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
