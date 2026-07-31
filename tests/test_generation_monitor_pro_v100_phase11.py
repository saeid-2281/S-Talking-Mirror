from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.connection import Database
from app.models.generation_incident import GenerationIncident
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_incident_service import GenerationIncidentService


def _project(database: Database, name: str = "Phase 11") -> int:
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


def _incident(incident_id: str, project_id: int) -> GenerationIncident:
    session_id = f"session-{incident_id}"
    return GenerationIncident(
        incident_id=incident_id,
        project_id=project_id,
        alert_fingerprint="provider-timeout-network",
        severity="critical",
        status="open",
        title="Critical provider timeout",
        summary="Provider network timeout and server failure",
        first_session_id=session_id,
        latest_session_id=session_id,
        occurrence_count=2,
        session_ids=(session_id,),
        created_at="2026-07-30T12:00:00+00:00",
        updated_at="2026-07-30T12:00:00+00:00",
        assigned_to="Saeid",
    )


def _store(repository: ProductEventRepository, incident: GenerationIncident) -> None:
    repository.add_batch_session(_session(incident.first_session_id, int(incident.project_id or 0)))
    repository.add_incident(incident)
    repository.link_batch_incident(
        incident.first_session_id,
        incident.incident_id,
        incident.status,
    )


def test_phase11_migration_adds_review_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase11.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 11")
        connection.execute("DROP TABLE generation_incident_action_items")
        connection.execute("DROP TABLE generation_incident_reviews")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        reviews = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incident_reviews'"
        ).fetchone()
        actions = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_incident_action_items'"
        ).fetchone()
    assert 11 in versions
    assert reviews is not None
    assert actions is not None
    assert database.path.with_suffix(database.path.suffix + ".pre-v11.bak").exists()


def test_phase11_review_lifecycle_and_validation(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase11.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("review", project_id)
    _store(repository, incident)

    draft = service.get_or_create_review(incident.incident_id, actor="Saeid")
    assert draft.status == "draft"
    assert draft.root_cause_category == "network"
    assert "2 generation session" in draft.impact_summary

    with pytest.raises(ValueError, match="Resolve or dismiss"):
        service.save_review(
            replace(
                draft,
                root_cause="Provider endpoint timed out.",
                resolution_summary="Recovered the provider connection.",
                lessons_learned="Add a provider probe.",
            ),
            complete=True,
        )
    with pytest.raises(ValueError, match="Resolve or dismiss"):
        service.save_review(
            replace(
                draft,
                status="completed",
                root_cause="Provider endpoint timed out.",
                resolution_summary="Recovered the provider connection.",
                lessons_learned="Add a provider probe.",
            )
        )

    service.resolve((incident.incident_id,), "Provider connection recovered.")
    completed = service.save_review(
        replace(
            draft,
            root_cause="Provider endpoint timed out.",
            contributing_factors=("No preflight probe", "Insufficient timeout telemetry"),
            detection_gap="The timeout trend was detected after queue failure.",
            resolution_summary="Recovered the provider connection.",
            lessons_learned="Add a provider probe before generation.",
        ),
        complete=True,
        actor="Saeid",
    )

    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert repository.get_incident_review(incident.incident_id) == completed
    kinds = {item.kind for item in service.list_updates(incident.incident_id)}
    assert "review_created" in kinds
    assert "review_completed" in kinds


def test_phase11_corrective_actions_and_overdue_notification(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 15, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase11.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository, now_factory=lambda: now)
    incident = _incident("actions", project_id)
    _store(repository, incident)

    action = service.add_action_item(
        incident.incident_id,
        "Add provider connectivity probe",
        owner="Platform team",
        due_at="2026-07-30T14:00:00+00:00",
        priority="p1",
        note="Run before queue start.",
        actor="Saeid",
    )
    overdue = service.evaluate_action_items(project_id=project_id, now=now)
    service.evaluate_action_items(project_id=project_id, now=now)

    assert [item.action_id for item in overdue] == [action.action_id]
    stored = repository.get_incident_action_item(action.action_id)
    assert stored is not None and stored.overdue_notified_at == now.isoformat()
    notifications = repository.list_notifications()
    assert sum(item.title == "Corrective action overdue" for item in notifications) == 1

    completed = service.update_action_item(
        action.action_id,
        status="completed",
        actor="Platform team",
    )
    assert completed.completed_at == now.isoformat()
    assert completed.overdue_notified_at is None


def test_phase11_export_contains_review_and_actions(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase11.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("export", project_id)
    _store(repository, incident)
    review = service.get_or_create_review(incident.incident_id)
    service.save_review(
        replace(review, root_cause="Timeout", lessons_learned="Probe first"),
    )
    service.add_action_item(
        incident.incident_id,
        "Add provider probe",
        owner="Platform",
        priority="p1",
    )

    json_path, csv_path = service.export([incident], tmp_path / "exports")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    exported = payload["incidents"][0]

    assert exported["post_incident_review"]["root_cause"] == "Timeout"
    assert exported["corrective_actions"][0]["title"] == "Add provider probe"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "post_incident_review_json" in csv_text
    assert "corrective_actions_json" in csv_text
    assert "Add provider probe" in csv_text


def test_phase11_review_dialog_saves_draft(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_incident_review_dialog import (
        GenerationIncidentReviewDialog,
    )

    database = Database(tmp_path / "phase11.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationIncidentService(repository)
    incident = _incident("dialog", project_id)
    _store(repository, incident)

    dialog = GenerationIncidentReviewDialog(service, incident)
    dialog.root_cause.setPlainText("Provider timeout")
    dialog.resolution_summary.setPlainText("Connection restored")
    dialog.lessons_learned.setPlainText("Probe before start")
    dialog.save_draft()

    review = service.get_review(incident.incident_id)
    assert review is not None
    assert review.root_cause == "Provider timeout"
    assert "Review draft saved" in dialog.status_label.text()
