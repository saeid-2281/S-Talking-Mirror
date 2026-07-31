from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentSlaPolicy,
)
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_incident_service import GenerationIncidentService


def _project(database: Database, name: str = "Phase 9") -> int:
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


def _session(session_id: str, project_id: int) -> BatchSessionRecord:
    return BatchSessionRecord(
        session_id=session_id,
        project_id=project_id,
        scope="row_range",
        provider="mock",
        model="model-a",
        voice="voice-a",
        total_jobs=10,
        completed_jobs=6,
        failed_jobs=4,
        skipped_jobs=0,
        character_count=1000,
        report_path=None,
        output_path=None,
        result="failed",
        started_at="2026-07-30T12:00:00+00:00",
        finished_at="2026-07-30T12:02:00+00:00",
        elapsed_seconds=120.0,
        active_seconds=120.0,
        retry_events=4,
        files_per_minute=3.0,
        characters_per_minute=300.0,
    )


def _incident(
    incident_id: str,
    project_id: int,
    *,
    status: str = "open",
    assigned_to: str | None = None,
) -> GenerationIncident:
    return GenerationIncident(
        incident_id=incident_id,
        project_id=project_id,
        alert_fingerprint=f"fingerprint-{incident_id}",
        severity="critical",
        status=status,
        title="Phase 9 incident",
        summary="Critical provider regression",
        first_session_id=f"session-{incident_id}",
        latest_session_id=f"session-{incident_id}",
        occurrence_count=1,
        session_ids=(f"session-{incident_id}",),
        created_at="2026-07-30T12:00:00+00:00",
        updated_at="2026-07-30T12:00:00+00:00",
        assigned_to=assigned_to,
        priority="p1",
        response_due_at="2026-07-30T12:15:00+00:00",
        resolution_due_at="2026-07-30T16:00:00+00:00",
        sla_state="on_track",
    )


def _store_incident(
    repository: ProductEventRepository,
    incident: GenerationIncident,
) -> None:
    repository.add_batch_session(_session(incident.first_session_id, int(incident.project_id)))
    repository.add_incident(incident)
    repository.link_batch_incident(
        incident.first_session_id,
        incident.incident_id,
        incident.status,
    )


def test_phase9_migration_adds_sla_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase9.db")
    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(generation_incidents)").fetchall()
        }
        policy_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incident_sla_policies'"
        ).fetchone()
        updates_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incident_updates'"
        ).fetchone()

    assert 9 in versions
    assert policy_table is not None
    assert updates_table is not None
    assert {
        "assigned_to",
        "priority",
        "response_due_at",
        "resolution_due_at",
        "sla_state",
        "escalation_level",
        "escalated_at",
        "last_sla_notification_level",
    }.issubset(columns)


def test_phase9_policy_round_trip_and_project_override(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase9.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)

    global_policy = service.save_sla_policy(
        GenerationIncidentSlaPolicy(
            critical_response_minutes=20,
            critical_resolution_minutes=300,
        )
    )
    assert service.get_sla_policy(project_id).critical_response_minutes == 20

    project_policy = service.save_sla_policy(
        GenerationIncidentSlaPolicy(
            project_id=project_id,
            critical_response_minutes=5,
            critical_resolution_minutes=45,
        )
    )
    restored = service.get_sla_policy(project_id)
    assert restored.project_id == project_id
    assert restored.critical_response_minutes == 5
    assert restored.critical_resolution_minutes == 45
    assert global_policy.project_id is None
    assert project_policy.updated_at


def test_phase9_assignment_and_note_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase9.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("ownership", project_id)
    _store_incident(repository, incident)

    assert service.assign([incident.incident_id], "Saeid", actor="operator") == 1
    assert service.add_note(
        incident.incident_id,
        "Provider status page is under investigation.",
        actor="operator",
    ) is not None

    stored = repository.get_incident(incident.incident_id)
    assert stored is not None
    assert stored.assigned_to == "Saeid"
    updates = service.list_updates(incident.incident_id)
    assert {item.kind for item in updates} == {"assignment", "note"}
    assert {item.actor for item in updates} == {"operator"}


def test_phase9_response_and_resolution_escalation_are_deduplicated(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "phase9.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    clock = [datetime(2026, 7, 30, 12, 16, tzinfo=timezone.utc)]
    service = GenerationIncidentService(repository, now_factory=lambda: clock[0])
    incident = _incident("escalation", project_id, assigned_to="Saeid")
    _store_incident(repository, incident)

    changed = service.evaluate_sla(project_id=project_id)
    assert changed[0].sla_state == "response_overdue"
    assert changed[0].escalation_level == 1
    assert len(repository.list_notifications()) == 1

    service.evaluate_sla(project_id=project_id)
    assert len(repository.list_notifications()) == 1

    assert service.acknowledge([incident.incident_id]) == 1
    clock[0] = datetime(2026, 7, 30, 16, 1, tzinfo=timezone.utc)
    service.evaluate_sla(project_id=project_id)
    stored = repository.get_incident(incident.incident_id)
    assert stored is not None
    assert stored.sla_state == "resolution_overdue"
    assert stored.escalation_level == 2
    assert stored.last_sla_notification_level == 2
    assert len(repository.list_notifications()) == 2
    assert [item.kind for item in service.list_updates(incident.incident_id)].count(
        "escalation"
    ) == 2


def test_phase9_resolution_and_reopen_update_sla_state(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase9.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    clock = [datetime(2026, 7, 30, 16, 5, tzinfo=timezone.utc)]
    service = GenerationIncidentService(repository, now_factory=lambda: clock[0])
    incident = _incident("lifecycle", project_id)
    _store_incident(repository, incident)

    assert service.resolve([incident.incident_id], "Recovered") == 1
    resolved = repository.get_incident(incident.incident_id)
    assert resolved is not None
    assert resolved.sla_state == "breached"

    clock[0] = datetime(2026, 7, 30, 17, 0, tzinfo=timezone.utc)
    assert service.reopen([incident.incident_id]) == 1
    reopened = repository.get_incident(incident.incident_id)
    assert reopened is not None
    assert reopened.status == "open"
    assert reopened.sla_state == "on_track"
    assert reopened.escalation_level == 0
    assert reopened.response_due_at == "2026-07-30T17:15:00+00:00"
    assert reopened.resolution_due_at == "2026-07-30T21:00:00+00:00"


def test_phase9_export_contains_sla_ownership_and_updates(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase9.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("export", project_id, assigned_to="Saeid")
    _store_incident(repository, incident)
    service.add_note(incident.incident_id, "Exported note", actor="operator")

    stored = repository.get_incident(incident.incident_id)
    assert stored is not None
    json_path, csv_path = service.export([stored], tmp_path / "exports")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    exported = payload["incidents"][0]
    assert exported["assigned_to"] == "Saeid"
    assert exported["sla_state"] == "on_track"
    assert exported["updates"][0]["message"] == "Exported note"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "response_due_at" in csv_text
    assert "updates_json" in csv_text


def test_phase9_incident_dialog_filters_sla_and_assigns(
    qt_app,
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.gui.dialogs.generation_incident_dialog import GenerationIncidentDialog

    database = Database(tmp_path / "phase9.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    clock = [datetime(2026, 7, 30, 12, 16, tzinfo=timezone.utc)]
    service = GenerationIncidentService(repository, now_factory=lambda: clock[0])
    incident = _incident("dialog", project_id)
    _store_incident(repository, incident)
    dialog = GenerationIncidentDialog(
        service,
        project_id=project_id,
        project_name="Phase 9",
        export_dir=tmp_path / "exports",
    )

    assert dialog.table.columnCount() == 8
    dialog.sla_filter.setCurrentIndex(dialog.sla_filter.findData("response_overdue"))
    assert dialog.table.rowCount() == 1
    dialog.table.selectRow(0)
    monkeypatch.setattr(
        "app.gui.dialogs.generation_incident_dialog.QInputDialog.getText",
        lambda *_args, **_kwargs: ("Saeid", True),
    )
    dialog.assign_selected()
    assert "Updated assignment for 1" in dialog.status_label.text()
    stored = repository.get_incident(incident.incident_id)
    assert stored is not None
    assert stored.assigned_to == "Saeid"
