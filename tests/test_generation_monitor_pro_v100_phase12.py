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
from app.services.generation_problem_service import GenerationProblemService
from app.services.generation_performance_policy_service import (
    GenerationPerformancePolicyService,
)
from app.services.generation_performance_service import GenerationPerformanceService
from app.services.product_activity_service import ProductActivityService


def _project(database: Database, name: str = "Phase 12") -> int:
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
    occurrence_count: int = 1,
) -> GenerationIncident:
    session_id = f"session-{incident_id}"
    return GenerationIncident(
        incident_id=incident_id,
        project_id=project_id,
        alert_fingerprint=fingerprint,
        severity="critical",
        status="open",
        title="Critical provider timeout",
        summary="Provider network timeout and server failure",
        first_session_id=session_id,
        latest_session_id=session_id,
        occurrence_count=occurrence_count,
        session_ids=(session_id,),
        created_at="2026-07-30T12:00:00+00:00",
        updated_at="2026-07-30T12:02:00+00:00",
        assigned_to="Platform",
    )


def _store(repository: ProductEventRepository, incident: GenerationIncident) -> None:
    repository.add_batch_session(
        _session(incident.first_session_id, int(incident.project_id or 0))
    )
    repository.add_incident(incident)
    repository.link_batch_incident(
        incident.first_session_id,
        incident.incident_id,
        incident.status,
    )


def test_phase12_migration_adds_problem_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase12.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 12")
        connection.execute("DROP TABLE generation_problem_incidents")
        connection.execute("DROP TABLE generation_known_problems")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        problems = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_known_problems'"
        ).fetchone()
        links = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_problem_incidents'"
        ).fetchone()
        incident_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(generation_incidents)")
        }
        action_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(generation_incident_action_items)"
            )
        }
    assert 12 in versions
    assert problems is not None
    assert links is not None
    assert {"problem_id", "problem_status"} <= incident_columns
    assert "problem_id" in action_columns
    assert database.path.with_suffix(database.path.suffix + ".pre-v12.bak").exists()


def test_phase12_create_problem_links_incidents_and_actions(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase12.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    incident_service = GenerationIncidentService(repository)
    problem_service = GenerationProblemService(repository)
    first = _incident("first", project_id, occurrence_count=2)
    second = _incident("second", project_id, occurrence_count=3)
    _store(repository, first)
    _store(repository, second)
    action = incident_service.add_action_item(
        first.incident_id,
        "Add provider connectivity probe",
        owner="Platform",
        priority="p1",
    )

    problem = problem_service.create_from_incidents(
        (first.incident_id, second.incident_id),
        actor="Saeid",
    )

    assert problem.status == "investigating"
    assert problem.root_cause_category == "network"
    assert problem.occurrence_count == 5
    assert set(problem.incident_ids) == {first.incident_id, second.incident_id}
    stored_first = repository.get_incident(first.incident_id)
    stored_action = repository.get_incident_action_item(action.action_id)
    assert stored_first is not None and stored_first.problem_id == problem.problem_id
    assert stored_first.problem_status == "investigating"
    assert stored_action is not None and stored_action.problem_id == problem.problem_id
    assert any(
        event.title == "Known problem created"
        for event in repository.list_activity(project_id=project_id)
    )


def test_phase12_known_error_and_fix_lifecycle_validation(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase12.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationProblemService(repository)
    incident = _incident("lifecycle", project_id)
    _store(repository, incident)
    problem = service.create_from_incidents((incident.incident_id,))

    with pytest.raises(ValueError, match="documented workaround"):
        service.set_status(problem.problem_id, "known_error")

    known_error = service.update_problem(
        replace(
            problem,
            status="known_error",
            workaround="Retry after provider connectivity is restored.",
        )
    )
    assert known_error.status == "known_error"

    with pytest.raises(ValueError, match="permanent fix"):
        service.set_status(problem.problem_id, "monitoring")

    monitoring = service.update_problem(
        replace(
            known_error,
            status="monitoring",
            permanent_fix="Run a provider probe before generation.",
            monitoring_until="2026-08-06T12:00:00+00:00",
        )
    )
    closed = service.set_status(monitoring.problem_id, "closed")
    assert monitoring.monitoring_until == "2026-08-06T12:00:00+00:00"
    assert closed.status == "closed"
    assert closed.closed_at is not None
    linked = repository.get_incident(incident.incident_id)
    assert linked is not None and linked.problem_status == "closed"


def test_phase12_recurring_incident_auto_matches_and_notifies(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 18, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase12.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationProblemService(repository, now_factory=lambda: now)
    original = _incident("original", project_id)
    recurring = _incident("recurring", project_id, occurrence_count=2)
    _store(repository, original)
    _store(repository, recurring)
    problem = service.create_from_incidents((original.incident_id,))
    problem = service.update_problem(
        replace(
            problem,
            status="known_error",
            workaround="Wait 30 seconds and retry transient provider failures.",
        )
    )

    match = service.match_incident(recurring.incident_id, auto_link=True)

    assert match is not None and match.problem_id == problem.problem_id
    assert match.score >= 100
    linked = repository.get_incident(recurring.incident_id)
    refreshed = service.get(problem.problem_id)
    assert linked is not None and linked.problem_id == problem.problem_id
    assert refreshed is not None and recurring.incident_id in refreshed.incident_ids
    notifications = repository.list_notifications()
    assert sum(item.title == "Known problem recurred" for item in notifications) == 1
    assert "Wait 30 seconds" in notifications[0].message


def test_phase12_export_contains_workaround_fix_and_actions(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase12.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    incident_service = GenerationIncidentService(repository)
    service = GenerationProblemService(repository)
    incident = _incident("export", project_id)
    _store(repository, incident)
    problem = service.create_from_incidents((incident.incident_id,))
    action = incident_service.add_action_item(
        incident.incident_id,
        "Add connectivity preflight",
        owner="Platform",
    )
    service.link_action(action.action_id, problem.problem_id)
    problem = service.update_problem(
        replace(
            problem,
            status="fix_planned",
            workaround="Retry transient failures.",
            permanent_fix="Add connectivity preflight.",
        )
    )

    json_path, csv_path = service.export((problem,), tmp_path / "exports")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    exported = payload["known_problems"][0]

    assert exported["workaround"] == "Retry transient failures."
    assert exported["permanent_fix"] == "Add connectivity preflight."
    assert exported["corrective_actions_json"][0]["title"] == "Add connectivity preflight"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "corrective_actions_json" in csv_text
    assert "Retry transient failures" in csv_text


def test_phase12_product_activity_auto_links_recurrence(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase12.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    policy = GenerationPerformancePolicyService(repository)
    performance = GenerationPerformanceService(repository, policy_service=policy)
    incidents = GenerationIncidentService(repository)
    problems = GenerationProblemService(repository)
    activity = ProductActivityService(
        repository,
        performance_service=performance,
        performance_policy_service=policy,
        incident_service=incidents,
        problem_service=problems,
    )

    def record(
        session_id: str,
        hour: int,
        *,
        completed: int = 10,
        failed: int = 0,
        retries: int = 0,
        active_seconds: float = 60.0,
        files_per_minute: float = 10.0,
    ) -> BatchSessionRecord:
        return BatchSessionRecord(
            session_id=session_id,
            project_id=project_id,
            scope="row_range",
            provider="mock",
            model="model-a",
            voice="voice-a",
            total_jobs=10,
            completed_jobs=completed,
            failed_jobs=failed,
            skipped_jobs=max(0, 10 - completed - failed),
            character_count=1000,
            report_path=None,
            output_path=None,
            result="failed" if failed else "completed",
            started_at=f"2026-07-30T{hour:02d}:00:00+00:00",
            finished_at=f"2026-07-30T{hour:02d}:02:00+00:00",
            elapsed_seconds=active_seconds,
            active_seconds=active_seconds,
            retry_events=retries,
            files_per_minute=files_per_minute,
            characters_per_minute=files_per_minute * 100,
        )

    for index in range(3):
        activity.record_batch(record(f"baseline-{index}", 8 + index))
    activity.record_batch(
        record(
            "regression-first",
            12,
            completed=5,
            failed=5,
            retries=5,
            active_seconds=180.0,
            files_per_minute=1.7,
        )
    )
    incident = incidents.list_incidents(project_id=project_id)[0]
    problem = problems.create_from_incidents((incident.incident_id,))
    problems.update_problem(
        replace(
            problem,
            status="known_error",
            workaround="Retry after provider recovery.",
        )
    )

    activity.record_batch(
        record(
            "regression-second",
            13,
            completed=5,
            failed=5,
            retries=5,
            active_seconds=180.0,
            files_per_minute=1.7,
        )
    )

    refreshed = problems.get(problem.problem_id)
    assert refreshed is not None and refreshed.occurrence_count == 2
    assert sum(
        item.title == "Known problem recurred"
        for item in repository.list_notifications()
    ) == 1


def test_phase12_problem_dialog_filters_and_opens_editor(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_problem_dialog import GenerationProblemDialog

    database = Database(tmp_path / "phase12.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationProblemService(repository)
    incident = _incident("dialog", project_id)
    _store(repository, incident)
    problem = service.create_from_incidents((incident.incident_id,))

    dialog = GenerationProblemDialog(
        service,
        project_id=project_id,
        project_name="Phase 12",
        export_dir=tmp_path / "exports",
    )

    assert dialog.table.columnCount() == 8
    assert dialog.table.rowCount() == 1
    dialog.status_filter.setCurrentIndex(
        dialog.status_filter.findData("investigating")
    )
    assert dialog.table.rowCount() == 1
    dialog.table.selectRow(0)
    assert dialog.selected_problem() == problem
    assert problem.problem_id in dialog.details.toPlainText()
