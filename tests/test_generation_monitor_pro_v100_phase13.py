from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.database.connection import Database
from app.models.domain import JobStatus, TTSJob
from app.models.generation_automation import (
    GenerationAutomationAction,
    GenerationAutomationPolicy,
)
from app.models.generation_incident import GenerationIncident, GenerationIncidentRunbook
from app.models.product_events import BatchSessionRecord
from app.repositories.job_repository import JobRepository
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_problem_service import GenerationProblemService
from app.services.generation_remediation_automation_service import (
    GenerationRemediationAutomationService,
)


def _project(database: Database, name: str = "Phase 13") -> int:
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
        occurrence_count=1,
        session_ids=(session_id,),
        created_at="2026-07-30T12:00:00+00:00",
        updated_at="2026-07-30T12:02:00+00:00",
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


def _services(
    database: Database,
    *,
    now: datetime | None = None,
) -> tuple[
    ProductEventRepository,
    GenerationIncidentService,
    GenerationRemediationAutomationService,
]:
    repository = ProductEventRepository(database)
    incident_service = GenerationIncidentService(
        repository,
        now_factory=(lambda: now) if now is not None else None,
    )
    problem_service = GenerationProblemService(
        repository,
        now_factory=(lambda: now) if now is not None else None,
    )
    automation_service = GenerationRemediationAutomationService(
        repository,
        incident_service,
        problem_service,
        JobRepository(database),
        now_factory=(lambda: now) if now is not None else None,
    )
    return repository, incident_service, automation_service


def _runbook(
    project_id: int,
    *,
    runbook_id: str = "phase13-runbook",
    action_type: str = "acknowledge_incident",
    trigger: str = "manual",
    dry_run_only: bool = False,
    rollback: str = "Reopen the incident and restore the queue snapshot.",
) -> GenerationIncidentRunbook:
    return GenerationIncidentRunbook(
        runbook_id=runbook_id,
        project_id=project_id,
        name="Phase 13 safe remediation",
        description="Allowlisted internal remediation actions only.",
        severity_filter="critical",
        fingerprint_pattern="provider|timeout",
        steps=("Review the planned action", "Validate the result"),
        automation_enabled=True,
        automation_trigger=trigger,
        automation_actions=(
            GenerationAutomationAction(
                action_type=action_type,
                title=action_type.replace("_", " ").title(),
                rollback_instruction=rollback,
            ),
        ),
        dry_run_only=dry_run_only,
        max_auto_runs=1,
        cooldown_minutes=0,
        rollback_instructions=rollback,
    )


def test_phase13_migration_adds_automation_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 13")
        connection.execute("DROP TABLE generation_automated_remediations")
        connection.execute("DROP TABLE generation_remediation_automation_policies")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        policy_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_remediation_automation_policies'"
        ).fetchone()
        execution_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_automated_remediations'"
        ).fetchone()
        runbook_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(generation_incident_runbooks)"
            )
        }

    assert 13 in versions
    assert policy_table is not None
    assert execution_table is not None
    assert {
        "automation_enabled",
        "automation_trigger",
        "automation_actions_json",
        "dry_run_only",
        "max_auto_runs",
        "cooldown_minutes",
        "rollback_instructions",
    } <= runbook_columns
    assert database.path.with_suffix(database.path.suffix + ".pre-v13.bak").exists()


def test_phase13_policy_round_trip_and_allowlist_validation(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    project_id = _project(database)
    _repository, _incident_service, service = _services(database)

    default = service.get_policy(project_id)
    assert default.enabled is False
    assert default.dry_run_default is True
    assert "retry_transient_jobs" in default.allowed_actions

    saved = service.save_policy(
        replace(
            default,
            enabled=True,
            dry_run_default=False,
            allowed_actions=("acknowledge_incident", "evaluate_sla"),
            max_auto_runs_per_incident=3,
            cooldown_minutes=15,
        )
    )
    restored = service.get_policy(project_id)

    assert saved == restored
    assert restored.allowed_actions == ("acknowledge_incident", "evaluate_sla")
    assert restored.max_auto_runs_per_incident == 3
    with pytest.raises(ValueError, match="Unsupported automation action"):
        service.save_policy(
            GenerationAutomationPolicy(
                project_id=project_id,
                allowed_actions=("shell_command",),
            )
        )


def test_phase13_runbook_round_trip_and_validation(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    project_id = _project(database)
    repository, incident_service, automation_service = _services(database)

    runbook = incident_service.save_runbook(_runbook(project_id))
    restored = repository.get_incident_runbook(runbook.runbook_id)

    assert restored == runbook
    assert restored is not None and restored.automation_enabled is True
    assert restored.automation_actions[0].action_type == "acknowledge_incident"
    with pytest.raises(ValueError, match="require at least one"):
        incident_service.save_runbook(
            replace(runbook, runbook_id="empty-auto", automation_actions=())
        )
    with pytest.raises(ValueError, match="Unsupported automation action"):
        automation_service.validate_runbook(
            replace(
                runbook,
                runbook_id="unsafe",
                automation_actions=(
                    GenerationAutomationAction(
                        action_type="shell_command",
                        title="Run arbitrary shell command",
                    ),
                ),
            )
        )


def test_phase13_dry_run_and_confirmed_live_execution(tmp_path: Path) -> None:
    now = datetime(2026, 7, 30, 19, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    project_id = _project(database)
    repository, incident_service, service = _services(database, now=now)
    incident = _incident("dry-live", project_id)
    _store(repository, incident)
    runbook = incident_service.save_runbook(_runbook(project_id))

    blocked = service.execute(incident.incident_id, runbook.runbook_id, dry_run=True)
    assert blocked.status == "blocked"
    assert "policy is disabled" in (blocked.blocked_reason or "").lower()

    service.save_policy(replace(service.default_policy(project_id), enabled=True))
    dry_run = service.execute(
        incident.incident_id,
        runbook.runbook_id,
        dry_run=True,
    )
    assert dry_run.status == "completed"
    assert dry_run.action_results[0].status == "planned"
    assert repository.get_incident(incident.incident_id).status == "open"

    with pytest.raises(ValueError, match="explicit confirmation"):
        service.execute(
            incident.incident_id,
            runbook.runbook_id,
            dry_run=False,
        )

    live = service.execute(
        incident.incident_id,
        runbook.runbook_id,
        dry_run=False,
        confirmed=True,
        actor="operator",
    )
    assert live.status == "completed"
    assert live.action_results[0].status == "completed"
    assert repository.get_incident(incident.incident_id).status == "acknowledged"
    assert "automation_completed" in {
        update.kind
        for update in incident_service.list_updates(incident.incident_id)
    }
    assert any(
        event.title == "Automated remediation completed"
        for event in repository.list_activity(project_id=project_id)
    )


def test_phase13_policy_block_failure_and_rollback_audit(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    project_id = _project(database)
    repository, incident_service, service = _services(database)
    incident = _incident("blocked-failed", project_id)
    _store(repository, incident)
    acknowledge = incident_service.save_runbook(_runbook(project_id))
    service.save_policy(
        replace(
            service.default_policy(project_id),
            enabled=True,
            allowed_actions=("evaluate_sla",),
        )
    )

    blocked = service.execute(
        incident.incident_id,
        acknowledge.runbook_id,
        dry_run=True,
    )
    assert blocked.status == "blocked"
    assert "Policy blocks" in (blocked.blocked_reason or "")

    failing = incident_service.save_runbook(
        _runbook(
            project_id,
            runbook_id="missing-workaround",
            action_type="record_workaround",
        )
    )
    service.save_policy(
        replace(
            service.default_policy(project_id),
            enabled=True,
            allowed_actions=("record_workaround",),
        )
    )
    failed = service.execute(
        incident.incident_id,
        failing.runbook_id,
        dry_run=False,
    )

    assert failed.status == "failed"
    assert failed.rollback_status == "required"
    assert "known problem" in failed.action_results[0].message.lower()
    rolled_back = service.mark_rollback(
        failed.automation_id,
        "completed",
        note="No queue changes were committed.",
        actor="operator",
    )
    assert rolled_back.rollback_status == "completed"
    assert "No queue changes" in rolled_back.rollback_note
    assert any(
        item.title == "Automated remediation failed"
        for item in repository.list_notifications()
    )


def test_phase13_auto_trigger_respects_dry_run_and_maximum_runs(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    project_id = _project(database)
    repository, incident_service, service = _services(database)
    incident = _incident("auto-limit", project_id)
    _store(repository, incident)
    runbook = incident_service.save_runbook(
        _runbook(project_id, trigger="incident_opened")
    )
    service.save_policy(
        replace(
            service.default_policy(project_id),
            enabled=True,
            dry_run_default=True,
        )
    )

    preview = service.auto_run_for_incident(
        incident.incident_id,
        trigger="incident_opened",
    )
    assert preview is not None and preview.dry_run is True
    assert repository.get_incident(incident.incident_id).status == "open"

    service.save_policy(
        replace(
            service.get_policy(project_id),
            dry_run_default=False,
            allow_unattended_mutating=True,
            max_auto_runs_per_incident=1,
            cooldown_minutes=0,
        )
    )
    live = service.auto_run_for_incident(
        incident.incident_id,
        trigger="incident_opened",
    )
    assert live is not None and live.status == "completed" and live.dry_run is False
    assert live.runbook_id == runbook.runbook_id

    limited = service.auto_run_for_incident(
        incident.incident_id,
        trigger="incident_opened",
    )
    assert limited is not None and limited.status == "blocked"
    assert "Maximum automatic run limit" in (limited.blocked_reason or "")


def test_phase13_retry_transient_jobs_only_and_export_audit(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase13.db")
    database.initialize()
    project_id = _project(database)
    repository, incident_service, service = _services(database)
    incident = _incident("retry-export", project_id)
    _store(repository, incident)
    job_repository = JobRepository(database)
    job_repository.upsert_jobs(
        project_id,
        [
            TTSJob(
                row_number=1,
                text="Transient failure",
                filename="transient.wav",
                status=JobStatus.FAILED,
                error="Connection timeout while contacting provider",
            ),
            TTSJob(
                row_number=2,
                text="Permanent failure",
                filename="permanent.wav",
                status=JobStatus.FAILED,
                error="status=401 unauthorized API key",
            ),
        ],
    )
    runbook = incident_service.save_runbook(
        _runbook(
            project_id,
            runbook_id="retry-transient",
            action_type="retry_transient_jobs",
        )
    )
    service.save_policy(
        replace(
            service.default_policy(project_id),
            enabled=True,
            allowed_actions=("retry_transient_jobs",),
        )
    )

    execution = service.execute(
        incident.incident_id,
        runbook.runbook_id,
        dry_run=False,
        confirmed=True,
    )
    restored = {job.row_number: job for job in job_repository.restore_jobs(project_id)}

    assert execution.status == "completed"
    assert execution.action_results[0].output["scheduled"] == 1
    assert restored[1].status == JobStatus.PENDING
    assert restored[2].status == JobStatus.FAILED

    json_path, csv_path = incident_service.export(
        (repository.get_incident(incident.incident_id),),
        tmp_path / "exports",
        project_name="Phase 13",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert payload["incidents"][0]["automated_remediations"][0]["automation_id"]
    assert "retry_transient_jobs" in rows[0]["automated_remediations_json"]


def test_phase13_runbook_editor_exposes_safe_automation_fields(qt_app) -> None:
    from app.gui.dialogs.incident_runbook_editor_dialog import (
        IncidentRunbookEditorDialog,
    )

    dialog = IncidentRunbookEditorDialog(
        GenerationIncidentRunbook(
            runbook_id="editor",
            project_id=1,
            name="Editor",
            steps=("Manual",),
        )
    )
    dialog.automation_enabled.setChecked(True)
    dialog.dry_run_only.setChecked(False)
    dialog.automation_actions.setPlainText(
        'acknowledge_incident | Acknowledge incident | {} | Reopen incident'
    )
    runbook = dialog.runbook()

    assert runbook.automation_enabled is True
    assert runbook.dry_run_only is False
    assert runbook.automation_actions[0].action_type == "acknowledge_incident"
    assert runbook.automation_actions[0].rollback_instruction == "Reopen incident"
