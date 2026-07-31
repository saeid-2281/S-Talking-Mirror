from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentActionItem,
    GenerationIncidentRemediation,
    GenerationIncidentReview,
    GenerationRemediationStep,
)
from app.models.generation_reliability import GenerationSloPolicy
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_reliability_service import GenerationReliabilityService


def _project(database: Database, name: str = "Phase 14") -> int:
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
    provider: str = "mock",
    total: int = 100,
    completed: int = 100,
    failed: int = 0,
    retries: int = 0,
    throughput: float = 20.0,
) -> BatchSessionRecord:
    return BatchSessionRecord(
        session_id=session_id,
        project_id=project_id,
        scope="all",
        provider=provider,
        model="model-a",
        voice="voice-a",
        total_jobs=total,
        completed_jobs=completed,
        failed_jobs=failed,
        skipped_jobs=max(0, total - completed - failed),
        character_count=total * 100,
        report_path=None,
        output_path=None,
        result="completed" if failed == 0 else "failed",
        started_at=started_at.isoformat(),
        finished_at=(started_at + timedelta(minutes=5)).isoformat(),
        elapsed_seconds=300.0,
        active_seconds=300.0,
        retry_events=retries,
        files_per_minute=throughput,
        characters_per_minute=2000.0,
        health_score=100.0 if failed == 0 else 50.0,
        regression_severity="none" if failed == 0 else "critical",
    )


def _incident(
    incident_id: str,
    project_id: int,
    session_id: str,
    created_at: datetime,
) -> GenerationIncident:
    return GenerationIncident(
        incident_id=incident_id,
        project_id=project_id,
        alert_fingerprint=f"fingerprint-{incident_id}",
        severity="critical",
        status="resolved",
        title="Reliability incident",
        summary="A repeated provider failure.",
        first_session_id=session_id,
        latest_session_id=session_id,
        occurrence_count=2,
        session_ids=(session_id,),
        created_at=created_at.isoformat(),
        updated_at=(created_at + timedelta(hours=4)).isoformat(),
        acknowledged_at=(created_at + timedelta(minutes=30)).isoformat(),
        resolved_at=(created_at + timedelta(hours=4)).isoformat(),
        resolution_note="Recovered with the approved runbook.",
    )


def test_phase14_migration_adds_slo_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 14")
        connection.execute("DROP TABLE generation_reliability_snapshots")
        connection.execute("DROP TABLE generation_reliability_slo_policies")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        policy_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='generation_reliability_slo_policies'"
        ).fetchone()
        snapshot_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='generation_reliability_snapshots'"
        ).fetchone()

    assert 14 in versions
    assert policy_table is not None
    assert snapshot_table is not None
    assert database.path.with_suffix(database.path.suffix + ".pre-v14.bak").exists()


def test_phase14_policy_round_trip_and_project_override(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationReliabilityService(repository)

    service.save_policy(
        replace(
            service.default_policy(None),
            target_job_success_rate=98.5,
            window_days=14,
        )
    )
    inherited = service.get_policy(project_id)
    assert inherited.project_id == project_id
    assert inherited.target_job_success_rate == 98.5
    assert inherited.window_days == 14

    project_policy = service.save_policy(
        replace(
            inherited,
            target_job_success_rate=99.5,
            max_retry_rate=2.0,
            critical_burn_rate=3.0,
        )
    )
    restored = service.get_policy(project_id)
    assert restored == project_policy
    assert restored.target_job_success_rate == 99.5
    assert restored.max_retry_rate == 2.0


def test_phase14_healthy_dashboard_and_provider_breakdown(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationReliabilityService(repository, now_factory=lambda: now)
    service.save_policy(
        replace(
            service.default_policy(project_id),
            target_job_success_rate=98.0,
            minimum_sessions=3,
        )
    )
    for index, provider in enumerate(("mock", "mock", "azure")):
        repository.add_batch_session(
            _session(
                f"healthy-{index}",
                project_id,
                now - timedelta(days=index + 1),
                provider=provider,
            )
        )

    dashboard = service.dashboard(project_id=project_id, now=now)

    assert dashboard.snapshot.state == "healthy"
    assert dashboard.snapshot.job_success_rate == 100.0
    assert dashboard.snapshot.error_budget_remaining_percent == 100.0
    assert dashboard.snapshot.burn_rate == 0.0
    assert {item.provider for item in dashboard.snapshot.provider_metrics} == {
        "mock",
        "azure",
    }
    assert dashboard.target_status["job_success_rate"] == "met"


def test_phase14_error_budget_burn_alert_is_deduplicated(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationReliabilityService(repository, now_factory=lambda: now)
    service.save_policy(
        GenerationSloPolicy(
            project_id=project_id,
            window_days=30,
            minimum_sessions=3,
            target_job_success_rate=99.0,
            warning_burn_rate=1.0,
            critical_burn_rate=2.0,
            alert_cooldown_minutes=240,
        )
    )
    for index in range(3):
        repository.add_batch_session(
            _session(
                f"burn-{index}",
                project_id,
                now - timedelta(days=index + 1),
                completed=90,
                failed=10,
                retries=8,
            )
        )

    first = service.evaluate_and_persist(project_id=project_id, now=now)
    second = service.evaluate_and_persist(
        project_id=project_id,
        now=now + timedelta(minutes=5),
    )

    assert first.state == "critical"
    assert first.burn_rate >= 2.0
    assert first.error_budget_remaining_percent == 0.0
    assert first.alert_notification_id is not None
    assert second.alert_notification_id is None
    notifications = [
        item
        for item in repository.list_notifications()
        if item.title == "Critical reliability SLO burn"
    ]
    assert len(notifications) == 1


def test_phase14_operational_metrics_cover_incidents_runbooks_and_actions(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationReliabilityService(repository, now_factory=lambda: now)
    service.save_policy(
        replace(service.default_policy(project_id), minimum_sessions=1)
    )
    session = _session("ops-session", project_id, now - timedelta(days=2))
    repository.add_batch_session(session)
    incident = _incident(
        "ops-incident",
        project_id,
        session.session_id,
        now - timedelta(days=2),
    )
    repository.add_incident(incident)
    repository.link_batch_incident(session.session_id, incident.incident_id, "resolved")
    repository.save_incident_remediation(
        GenerationIncidentRemediation(
            remediation_id="manual-remediation",
            incident_id=incident.incident_id,
            runbook_id=None,
            runbook_name="Recovery",
            status="completed",
            steps=(GenerationRemediationStep(position=0, title="Recover", status="completed"),),
            started_at=(now - timedelta(days=2, hours=-1)).isoformat(),
            updated_at=(now - timedelta(days=2, hours=-2)).isoformat(),
            completed_at=(now - timedelta(days=2, hours=-2)).isoformat(),
        )
    )
    review = GenerationIncidentReview(
        review_id="ops-review",
        incident_id=incident.incident_id,
        created_at=(now - timedelta(days=1)).isoformat(),
        updated_at=(now - timedelta(days=1)).isoformat(),
    )
    repository.save_incident_review(review)
    repository.save_incident_action_item(
        GenerationIncidentActionItem(
            action_id="ops-action",
            review_id=review.review_id,
            incident_id=incident.incident_id,
            title="Prevent recurrence",
            status="completed",
            created_at=(now - timedelta(days=1)).isoformat(),
            updated_at=(now - timedelta(hours=12)).isoformat(),
            completed_at=(now - timedelta(hours=12)).isoformat(),
        )
    )

    snapshot = service.dashboard(project_id=project_id, now=now).snapshot

    assert snapshot.incident_count == 1
    assert snapshot.recurring_incident_count == 1
    assert snapshot.mtta_minutes == 30.0
    assert snapshot.mttr_minutes == 240.0
    assert snapshot.runbook_execution_count == 1
    assert snapshot.runbook_success_rate == 100.0
    assert snapshot.corrective_action_count == 1
    assert snapshot.corrective_action_completion_rate == 100.0


def test_phase14_snapshot_round_trip_and_export(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationReliabilityService(repository, now_factory=lambda: now)
    service.save_policy(
        replace(service.default_policy(project_id), minimum_sessions=1)
    )
    repository.add_batch_session(
        _session("export-session", project_id, now - timedelta(days=1))
    )

    saved = service.evaluate_and_persist(project_id=project_id, now=now)
    restored = repository.list_reliability_snapshots(project_id=project_id)
    dashboard = service.dashboard(project_id=project_id, now=now)
    json_path, csv_path = service.export(
        dashboard,
        tmp_path / "exports",
        project_name="Phase 14",
    )

    assert restored[0] == saved
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["snapshot"]["session_count"] == 1
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["snapshot_id"] == dashboard.snapshot.snapshot_id
    assert "provider_metrics_json" in rows[0]


def test_phase14_reliability_dialog_renders_metrics(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_reliability_dialog import (
        GenerationReliabilityDialog,
    )

    now = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase14.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationReliabilityService(repository, now_factory=lambda: now)
    service.save_policy(
        replace(service.default_policy(project_id), minimum_sessions=1)
    )
    repository.add_batch_session(
        _session("dialog-session", project_id, now - timedelta(days=1))
    )

    dialog = GenerationReliabilityDialog(
        service,
        project_id=project_id,
        project_name="Phase 14",
        export_dir=tmp_path / "exports",
    )

    assert dialog.metrics_table.columnCount() == 4
    assert dialog.metrics_table.rowCount() >= 7
    assert dialog.provider_table.rowCount() == 1
    assert "Healthy" in dialog.state_label.text()
