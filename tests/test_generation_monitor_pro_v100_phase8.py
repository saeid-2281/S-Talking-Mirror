from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.generation_incident import GenerationIncident
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_performance_policy_service import (
    GenerationPerformancePolicyService,
)
from app.services.generation_performance_service import GenerationPerformanceService
from app.services.product_activity_service import ProductActivityService


def _project(database: Database, name: str = "Phase 8") -> int:
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


def _record(
    session_id: str,
    *,
    project_id: int | None,
    started_at: str,
    result: str = "completed",
    completed: int = 10,
    failed: int = 0,
    retries: int = 0,
    active_seconds: float = 60.0,
    files_per_minute: float = 10.0,
    characters_per_minute: float = 1000.0,
) -> BatchSessionRecord:
    total = 10
    return BatchSessionRecord(
        session_id=session_id,
        project_id=project_id,
        scope="row_range",
        provider="mock",
        model="model-a",
        voice="voice-a",
        total_jobs=total,
        completed_jobs=completed,
        failed_jobs=failed,
        skipped_jobs=max(0, total - completed - failed),
        character_count=1000,
        report_path=f"/reports/{session_id}/report.html",
        output_path=f"/output/{session_id}",
        result=result,
        started_at=started_at,
        finished_at=started_at,
        elapsed_seconds=active_seconds + 5.0,
        active_seconds=active_seconds,
        paused_seconds=5.0,
        retry_events=retries,
        files_per_minute=files_per_minute,
        characters_per_minute=characters_per_minute,
        failure_summary={"failed": failed},
        monitor_metrics={"stalled": False},
    )


def _regression(session_id: str, project_id: int, started_at: str) -> BatchSessionRecord:
    return _record(
        session_id,
        project_id=project_id,
        started_at=started_at,
        result="failed",
        completed=6,
        failed=4,
        retries=5,
        active_seconds=150.0,
        files_per_minute=2.4,
        characters_per_minute=240.0,
    )


def _services(
    database: Database,
    now: list[datetime] | None = None,
) -> tuple[
    ProductEventRepository,
    GenerationIncidentService,
    ProductActivityService,
]:
    repository = ProductEventRepository(database)
    now_factory = (lambda: now[0]) if now is not None else None
    policy = GenerationPerformancePolicyService(repository, now_factory=now_factory)
    performance = GenerationPerformanceService(repository, policy_service=policy)
    incidents = GenerationIncidentService(repository, now_factory=now_factory)
    activity = ProductActivityService(
        repository,
        performance_service=performance,
        performance_policy_service=policy,
        incident_service=incidents,
    )
    return repository, incidents, activity


def _add_baseline(activity: ProductActivityService, project_id: int) -> None:
    for index in range(3):
        activity.record_batch(
            _record(
                f"baseline-{index}",
                project_id=project_id,
                started_at=f"2026-07-30T{index + 8:02d}:00:00+00:00",
            )
        )


def test_phase8_migration_adds_incident_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase8.db")
    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(batch_sessions)").fetchall()
        }
        incident_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incidents'"
        ).fetchone()

    assert 8 in versions
    assert incident_table is not None
    assert {"incident_id", "incident_status"}.issubset(columns)


def test_phase8_critical_alert_opens_and_links_incident(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase8.db")
    database.initialize()
    project_id = _project(database)
    repository, incidents, activity = _services(database)
    _add_baseline(activity, project_id)

    activity.record_batch(
        _regression("critical-first", project_id, "2026-07-30T12:00:00+00:00")
    )

    stored = incidents.list_incidents(project_id=project_id)
    assert len(stored) == 1
    incident = stored[0]
    assert incident.status == "open"
    assert incident.occurrence_count == 1
    assert incident.session_ids == ("critical-first",)
    session = next(
        item
        for item in repository.list_batch_sessions(project_id=project_id)
        if item.session_id == "critical-first"
    )
    assert session.incident_id == incident.incident_id
    assert session.incident_status == "open"
    notification = repository.list_notifications()[0]
    assert notification.action_payload == "generation-incident-center"


def test_phase8_duplicate_regression_updates_active_incident(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase8.db")
    database.initialize()
    project_id = _project(database)
    now = [datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)]
    repository, incidents, activity = _services(database, now)
    _add_baseline(activity, project_id)

    activity.record_batch(_regression("first", project_id, now[0].isoformat()))
    now[0] = datetime(2026, 7, 30, 12, 10, tzinfo=timezone.utc)
    activity.record_batch(
        replace(
            _regression("duplicate", project_id, now[0].isoformat()),
            files_per_minute=2.2,
            characters_per_minute=220.0,
        )
    )

    stored = incidents.list_incidents(project_id=project_id)
    assert len(stored) == 1
    incident = stored[0]
    assert incident.occurrence_count == 2
    assert incident.session_ids == ("first", "duplicate")
    assert incident.latest_session_id == "duplicate"
    sessions = {
        item.session_id: item
        for item in repository.list_batch_sessions(project_id=project_id)
    }
    assert sessions["first"].incident_id == incident.incident_id
    assert sessions["duplicate"].incident_id == incident.incident_id
    assert len(repository.list_notifications()) == 1


def test_phase8_new_occurrence_reopens_acknowledged_incident(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase8.db")
    database.initialize()
    project_id = _project(database)
    now = [datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)]
    repository, incidents, activity = _services(database, now)
    _add_baseline(activity, project_id)

    activity.record_batch(_regression("first", project_id, now[0].isoformat()))
    incident = incidents.list_incidents(project_id=project_id)[0]
    assert incidents.acknowledge([incident.incident_id]) == 1

    now[0] = datetime(2026, 7, 30, 12, 10, tzinfo=timezone.utc)
    activity.record_batch(_regression("reopened", project_id, now[0].isoformat()))

    restored = incidents.list_incidents(project_id=project_id)[0]
    assert restored.incident_id == incident.incident_id
    assert restored.status == "open"
    assert restored.acknowledged_at is None
    assert restored.occurrence_count == 2
    sessions = {
        item.session_id: item
        for item in repository.list_batch_sessions(project_id=project_id)
    }
    assert sessions["first"].incident_status == "open"
    assert sessions["reopened"].incident_status == "open"


def test_phase8_incident_lifecycle_updates_related_sessions(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase8.db")
    database.initialize()
    project_id = _project(database)
    repository, incidents, activity = _services(database)
    _add_baseline(activity, project_id)
    activity.record_batch(_regression("lifecycle", project_id, "2026-07-30T12:00:00+00:00"))
    incident = incidents.list_incidents(project_id=project_id)[0]

    assert incidents.acknowledge([incident.incident_id]) == 1
    assert incidents.list_incidents(project_id=project_id)[0].status == "acknowledged"
    assert incidents.resolve([incident.incident_id], "Provider recovered") == 1
    resolved = incidents.list_incidents(project_id=project_id)[0]
    assert resolved.status == "resolved"
    assert resolved.resolution_note == "Provider recovered"
    assert incidents.reopen([incident.incident_id]) == 1
    reopened = incidents.list_incidents(project_id=project_id)[0]
    assert reopened.status == "open"
    session = next(
        item
        for item in repository.list_batch_sessions(project_id=project_id)
        if item.session_id == "lifecycle"
    )
    assert session.incident_status == "open"
    lifecycle_events = [
        event
        for event in repository.list_activity(project_id=project_id)
        if event.category == "generation-incident"
    ]
    assert {event.metadata.get("status") for event in lifecycle_events} >= {
        "acknowledged",
        "resolved",
        "open",
    }


def test_phase8_incident_export_contains_sessions_and_resolution(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase8.db")
    database.initialize()
    project_id = _project(database)
    repository, incidents, _activity = _services(database)
    repository.add_batch_session(
        _record(
            "export-session",
            project_id=project_id,
            started_at="2026-07-30T12:00:00+00:00",
        )
    )
    incident = GenerationIncident(
        incident_id="incident-export",
        project_id=project_id,
        alert_fingerprint="fingerprint-export",
        severity="critical",
        status="resolved",
        title="Export incident",
        summary="Regression summary",
        first_session_id="export-session",
        latest_session_id="export-session",
        occurrence_count=1,
        session_ids=("export-session",),
        created_at="2026-07-30T12:00:00+00:00",
        updated_at="2026-07-30T12:05:00+00:00",
        resolved_at="2026-07-30T12:05:00+00:00",
        resolution_note="Validated recovery",
    )
    repository.add_incident(incident)

    json_path, csv_path = incidents.export([incident], tmp_path, project_name="Phase 8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["resolved_count"] == 1
    assert payload["incidents"][0]["session_ids"] == ["export-session"]
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "session_ids_json" in csv_text
    assert "Validated recovery" in csv_text


def test_phase8_incident_dialog_filters_and_acknowledges(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_incident_dialog import GenerationIncidentDialog

    database = Database(tmp_path / "phase8.db")
    database.initialize()
    project_id = _project(database)
    repository, incidents, _activity = _services(database)
    repository.add_batch_session(
        _record(
            "dialog-session",
            project_id=project_id,
            started_at="2026-07-30T12:00:00+00:00",
        )
    )
    repository.add_incident(
        GenerationIncident(
            incident_id="dialog-incident",
            project_id=project_id,
            alert_fingerprint="dialog-fingerprint",
            severity="critical",
            status="open",
            title="Dialog incident",
            summary="Critical regression",
            first_session_id="dialog-session",
            latest_session_id="dialog-session",
            occurrence_count=1,
            session_ids=("dialog-session",),
            created_at="2026-07-30T12:00:00+00:00",
            updated_at="2026-07-30T12:00:00+00:00",
        )
    )
    repository.link_batch_incident("dialog-session", "dialog-incident", "open")
    dialog = GenerationIncidentDialog(
        incidents,
        project_id=project_id,
        project_name="Phase 8",
        export_dir=tmp_path / "exports",
    )

    assert dialog.table.columnCount() == 8
    dialog.status_filter.setCurrentIndex(dialog.status_filter.findData("open"))
    assert dialog.table.rowCount() == 1
    dialog.table.selectRow(0)
    dialog.acknowledge_selected()
    assert "Acknowledged 1" in dialog.status_label.text()
    assert incidents.list_incidents(project_id=project_id)[0].status == "acknowledged"
