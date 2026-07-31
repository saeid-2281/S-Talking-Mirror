from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.database.connection import Database
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentRunbook,
)
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_incident_service import GenerationIncidentService


def _project(database: Database, name: str = "Phase 10") -> int:
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
        completed_jobs=4,
        failed_jobs=6,
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
        files_per_minute=2.0,
        characters_per_minute=250.0,
    )


def _incident(
    incident_id: str,
    project_id: int,
    *,
    fingerprint: str = "provider-timeout-network",
) -> GenerationIncident:
    return GenerationIncident(
        incident_id=incident_id,
        project_id=project_id,
        alert_fingerprint=fingerprint,
        severity="critical",
        status="open",
        title="Critical provider timeout",
        summary="Provider network timeout and server failure",
        first_session_id=f"session-{incident_id}",
        latest_session_id=f"session-{incident_id}",
        occurrence_count=1,
        session_ids=(f"session-{incident_id}",),
        created_at="2026-07-30T12:00:00+00:00",
        updated_at="2026-07-30T12:00:00+00:00",
    )


def _store_incident(
    repository: ProductEventRepository,
    incident: GenerationIncident,
) -> None:
    project_id = int(incident.project_id or 0)
    repository.add_batch_session(_session(incident.first_session_id, project_id))
    repository.add_incident(incident)
    repository.link_batch_incident(
        incident.first_session_id,
        incident.incident_id,
        incident.status,
    )


def test_phase10_migration_adds_runbook_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 10")
        connection.execute("DROP TABLE generation_incident_remediations")
        connection.execute("DROP TABLE generation_incident_runbooks")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        runbooks = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incident_runbooks'"
        ).fetchone()
        remediations = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incident_remediations'"
        ).fetchone()

    assert 10 in versions
    assert runbooks is not None
    assert remediations is not None
    assert database.path.with_suffix(database.path.suffix + ".pre-v10.bak").exists()


def test_phase10_defaults_and_recommendations(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("recommend", project_id)
    _store_incident(repository, incident)

    defaults = service.ensure_default_runbooks()
    recommendations = service.recommend_runbooks(incident.incident_id)

    assert len(defaults) >= 3
    assert recommendations[0].runbook_id == "default-provider-recovery"
    assert recommendations[0].enabled is True
    assert all(item.steps for item in recommendations)


def test_phase10_runbook_validation_and_project_priority(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("project-runbook", project_id)
    _store_incident(repository, incident)
    service.ensure_default_runbooks()

    saved = service.save_runbook(
        GenerationIncidentRunbook(
            runbook_id="project-provider",
            project_id=project_id,
            name="Project provider recovery",
            severity_filter="critical",
            fingerprint_pattern="provider|timeout",
            steps=("Check project profile", "Run controlled probe"),
        )
    )
    recommendations = service.recommend_runbooks(incident.incident_id)

    assert saved.updated_at
    assert recommendations[0].runbook_id == "project-provider"

    other_project = _project(database, "Other project")
    foreign = service.save_runbook(
        replace(saved, runbook_id="foreign", project_id=other_project)
    )
    with pytest.raises(ValueError, match="different project"):
        service.start_remediation(incident.incident_id, foreign.runbook_id)

    with pytest.raises(ValueError, match="Invalid fingerprint pattern"):
        service.save_runbook(replace(saved, runbook_id="bad", fingerprint_pattern="["))
    with pytest.raises(ValueError, match="at least one"):
        service.save_runbook(replace(saved, runbook_id="empty", steps=()))


def test_phase10_start_is_deduplicated_and_records_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("start", project_id)
    _store_incident(repository, incident)
    service.ensure_default_runbooks()

    first = service.start_remediation(
        incident.incident_id,
        "default-provider-recovery",
        actor="operator",
    )
    second = service.start_remediation(
        incident.incident_id,
        "default-critical-triage",
        actor="operator",
    )

    assert first.remediation_id == second.remediation_id
    assert first.status == "active"
    assert first.total_steps == 5
    assert repository.find_active_incident_remediation(incident.incident_id) == first
    assert "runbook_started" in {
        update.kind for update in service.list_updates(incident.incident_id)
    }
    assert any(
        event.title == "Generation remediation started"
        for event in repository.list_activity(project_id=project_id)
    )


def test_phase10_step_completion_updates_progress_and_finishes(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("complete", project_id)
    _store_incident(repository, incident)
    service.ensure_default_runbooks()
    remediation = service.start_remediation(
        incident.incident_id,
        "default-critical-triage",
        actor="Saeid",
    )

    for position in range(remediation.total_steps):
        remediation = service.update_remediation_step(
            remediation.remediation_id,
            position,
            "completed",
            actor="Saeid",
        )

    assert remediation.status == "completed"
    assert remediation.progress_percent == 100
    assert remediation.completed_at is not None
    assert service.active_remediation(incident.incident_id) is None
    kinds = [item.kind for item in service.list_updates(incident.incident_id)]
    assert kinds.count("runbook_step") == remediation.total_steps
    assert "runbook_completed" in kinds


def test_phase10_failed_runbook_can_resume_and_cancel(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("resume", project_id)
    _store_incident(repository, incident)
    service.ensure_default_runbooks()
    remediation = service.start_remediation(
        incident.incident_id,
        "default-critical-triage",
    )

    failed = service.update_remediation_step(
        remediation.remediation_id,
        0,
        "failed",
        note="Probe failed",
    )
    resumed = service.resume_remediation(failed.remediation_id, actor="operator")
    cancelled = service.cancel_remediation(
        resumed.remediation_id,
        note="Waiting for provider maintenance",
        actor="operator",
    )

    assert failed.status == "failed"
    assert resumed.status == "active"
    assert resumed.steps[0].status == "pending"
    assert cancelled.status == "cancelled"
    assert cancelled.completed_at is not None


def test_phase10_export_contains_remediation_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("export", project_id)
    _store_incident(repository, incident)
    service.ensure_default_runbooks()
    remediation = service.start_remediation(
        incident.incident_id,
        "default-critical-triage",
    )
    service.update_remediation_step(remediation.remediation_id, 0, "completed")

    json_path, csv_path = service.export([incident], tmp_path / "exports")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    exported = payload["incidents"][0]["remediations"][0]

    assert exported["runbook_name"] == "General critical incident triage"
    assert exported["steps"][0]["status"] == "completed"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "remediations_json" in csv_text
    assert "General critical incident triage" in csv_text


def test_phase10_runbook_dialog_starts_and_updates_step(
    qt_app,
    tmp_path: Path,
) -> None:
    from app.gui.dialogs.generation_incident_runbook_dialog import (
        GenerationIncidentRunbookDialog,
    )

    database = Database(tmp_path / "phase10.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("dialog", project_id)
    _store_incident(repository, incident)

    dialog = GenerationIncidentRunbookDialog(
        service,
        incident,
        project_name="Phase 10",
    )
    assert dialog.runbook_combo.count() >= 3
    dialog.start_selected_runbook()
    assert dialog.steps_table.rowCount() == 5
    dialog.steps_table.selectRow(0)
    dialog.set_step_status("completed")

    remediation = service.list_remediations(incident.incident_id)[0]
    assert remediation.steps[0].status == "completed"
    assert "Step 1 changed to completed" in dialog.status_label.text()
