from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.generation_maintenance import (
    GenerationMaintenancePolicy,
    GenerationMaintenanceRun,
)
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord
from app.release import SCHEMA_VERSION
from app.repositories.generation_maintenance_repository import (
    GenerationMaintenanceRepository,
)
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_maintenance_service import GenerationMaintenanceService


def _project(database: Database, name: str = "Phase 16") -> int:
    with database.transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects(
                name, project_file, csv_path, output_path, provider,
                settings_json, created_at, updated_at
            ) VALUES(?, NULL, NULL, NULL, 'mock', '{}', 'now', 'now')
            """,
            (name,),
        )
        return int(cursor.lastrowid)


def _session(
    session_id: str,
    project_id: int,
    started_at: datetime,
    *,
    incident_id: str | None = None,
) -> BatchSessionRecord:
    return BatchSessionRecord(
        session_id=session_id,
        project_id=project_id,
        scope="all",
        provider="mock",
        model="model-a",
        voice="voice-a",
        total_jobs=10,
        completed_jobs=10,
        failed_jobs=0,
        skipped_jobs=0,
        character_count=1000,
        report_path=None,
        output_path=None,
        result="completed",
        started_at=started_at.isoformat(),
        finished_at=(started_at + timedelta(minutes=1)).isoformat(),
        elapsed_seconds=60.0,
        active_seconds=60.0,
        incident_id=incident_id,
        incident_status="open" if incident_id else "none",
    )


def _service(
    database: Database,
    backup_dir: Path,
    *,
    now: datetime,
) -> GenerationMaintenanceService:
    return GenerationMaintenanceService(
        database,
        GenerationMaintenanceRepository(database),
        backup_dir,
        now_factory=lambda: now,
    )


def test_phase16_migration_adds_hardening_schema_and_verified_backup(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "phase16.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 16")
        connection.execute("DROP TABLE generation_maintenance_runs")
        connection.execute("DROP TABLE generation_maintenance_policies")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = tuple(
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    migration_backup = database.path.with_suffix(
        database.path.suffix + ".pre-v16.bak"
    )
    assert versions == tuple(range(1, SCHEMA_VERSION + 1))
    assert 16 in versions
    assert "generation_maintenance_policies" in tables
    assert "generation_maintenance_runs" in tables
    assert migration_backup.exists()
    assert Database(migration_backup).quick_check() == "ok"


def test_phase16_health_policy_and_release_gate(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase16.db")
    database.initialize()
    project_id = _project(database)
    service = _service(database, tmp_path / "backups", now=now)

    global_policy = service.save_policy(
        GenerationMaintenancePolicy(
            session_retention_days=400,
            backup_retention_count=7,
        )
    )
    inherited = service.get_policy(project_id)
    health = service.run_health_check(project_id=project_id, full=True)
    startup_health = service.run_startup_check()

    assert global_policy.project_id is None
    assert inherited.project_id == project_id
    assert inherited.session_retention_days == 400
    assert inherited.backup_retention_count == 7
    assert health.ready
    assert health.schema_version == SCHEMA_VERSION
    assert health.applied_versions == tuple(range(1, SCHEMA_VERSION + 1))
    assert health.quick_check == "ok"
    assert health.foreign_key_violations == ()
    assert startup_health is not None and startup_health.ready
    assert service.repository.list_runs(project_id=project_id)[0].status == "passed"


def test_phase16_verified_backup_restore_and_manifest(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase16.db")
    database.initialize()
    first_project = _project(database, "Before backup")
    service = _service(database, tmp_path / "backups", now=now)

    artifact = service.create_backup(project_id=first_project, label="release-candidate")
    manifest_path = artifact.path.with_suffix(artifact.path.suffix + ".json")
    second_project = _project(database, "After backup")
    pre_restore = service.restore_backup(artifact.path, project_id=first_project)

    with database.connect() as connection:
        names = [
            str(row[0])
            for row in connection.execute("SELECT name FROM projects ORDER BY id")
        ]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert second_project > first_project
    assert artifact.quick_check == "ok"
    assert artifact.schema_version == SCHEMA_VERSION
    assert len(artifact.sha256) == 64
    assert manifest["sha256"] == artifact.sha256
    assert manifest["expected_schema_version"] == SCHEMA_VERSION
    assert pre_restore.path.exists()
    assert names == ["Before backup"]
    assert service.health(full=True).ready


def test_phase16_retention_preserves_incident_linked_sessions(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    old = now - timedelta(days=120)
    database = Database(tmp_path / "phase16.db")
    database.initialize()
    project_id = _project(database)
    events = ProductEventRepository(database)
    maintenance_repository = GenerationMaintenanceRepository(database)
    service = GenerationMaintenanceService(
        database,
        maintenance_repository,
        tmp_path / "backups",
        now_factory=lambda: now,
    )
    events.add_batch_session(_session("orphan-old", project_id, old))
    events.add_batch_session(
        _session(
            "incident-old",
            project_id,
            old,
            incident_id="incident-1",
        )
    )
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO generation_incidents(
                incident_id, project_id, alert_fingerprint, severity, status,
                title, summary, first_session_id, latest_session_id,
                occurrence_count, session_ids_json, created_at, updated_at
            ) VALUES(?, ?, ?, 'critical', 'open', ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                "incident-1",
                project_id,
                "fingerprint-1",
                "Retained incident",
                "Must survive retention",
                "incident-old",
                "incident-old",
                '["incident-old"]',
                old.isoformat(),
                old.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO generation_reliability_snapshots(
                snapshot_id, project_id, period_start, period_end, created_at
            ) VALUES('reliability-old', ?, ?, ?, ?)
            """,
            (project_id, old.isoformat(), old.isoformat(), old.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO generation_cost_capacity_snapshots(
                snapshot_id, project_id, period_start, period_end, created_at
            ) VALUES('cost-old', ?, ?, ?, ?)
            """,
            (project_id, old.isoformat(), old.isoformat(), old.isoformat()),
        )
    events.add_notification(
        NotificationRecord(
            "read-old",
            "info",
            "Old read",
            "Eligible",
            old.isoformat(),
            read=True,
        )
    )
    events.add_notification(
        NotificationRecord(
            "unread-old",
            "warning",
            "Old unread",
            "Must survive",
            old.isoformat(),
            read=False,
        )
    )
    events.add_activity(
        ActivityEvent(
            "activity-old",
            "generation",
            "Old activity",
            "Eligible",
            old.isoformat(),
            project_id=project_id,
        )
    )
    maintenance_repository.add_run(
        GenerationMaintenanceRun(
            "maintenance-old",
            project_id,
            "quick_check",
            "passed",
            old.isoformat(),
            old.isoformat(),
        )
    )
    policy = service.save_policy(
        GenerationMaintenancePolicy(
            project_id=project_id,
            session_retention_days=30,
            notification_retention_days=30,
            activity_retention_days=30,
            snapshot_retention_days=30,
            maintenance_run_retention_days=30,
        )
    )

    project_preview = service.retention_preview(project_id=project_id, policy=policy)
    global_preview = service.retention_preview(policy=replace(policy, project_id=None))
    project_deleted = service.apply_retention(project_id=project_id, policy=policy)
    global_deleted = service.apply_retention(policy=replace(policy, project_id=None))

    with database.connect() as connection:
        sessions = {
            str(row[0])
            for row in connection.execute("SELECT session_id FROM batch_sessions")
        }
        notifications = {
            str(row[0])
            for row in connection.execute(
                "SELECT notification_id FROM notifications"
            )
        }
        incident_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM generation_incidents"
            ).fetchone()[0]
        )
    assert project_preview.candidate_counts["batch_sessions"] == 1
    assert project_preview.candidate_counts["notifications"] == 0
    assert global_preview.candidate_counts["notifications"] == 1
    assert project_deleted.candidate_counts["batch_sessions"] == 1
    assert global_deleted.candidate_counts["notifications"] == 1
    assert sessions == {"incident-old"}
    assert notifications == {"unread-old"}
    assert incident_count == 1
    assert service.health().ready


def test_phase16_export_and_dialog(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_maintenance_dialog import (
        GenerationMaintenanceDialog,
    )

    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase16.db")
    database.initialize()
    project_id = _project(database)
    service = _service(database, tmp_path / "backups", now=now)
    service.run_health_check(project_id=project_id)

    json_path, csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
    )
    dialog = GenerationMaintenanceDialog(
        service,
        project_id=project_id,
        project_name="Phase 16",
        export_dir=tmp_path / "exports",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert json_path.exists()
    assert csv_path.exists()
    assert payload["health"]["ready"] is True
    assert payload["health"]["schema_version"] == SCHEMA_VERSION
    assert dialog.windowTitle() == "Generation Hardening & Maintenance"
    assert dialog.backup_table.columnCount() == 5
    assert dialog.run_table.rowCount() >= 1
    assert (
        f"schema {SCHEMA_VERSION}/{SCHEMA_VERSION}"
        in dialog.health_label.text()
    )
