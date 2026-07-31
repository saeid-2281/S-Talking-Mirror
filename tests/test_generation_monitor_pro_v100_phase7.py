from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.generation_performance import (
    GenerationPerformanceBudget,
    GenerationPerformanceThresholds,
)
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_history_service import GenerationHistoryService
from app.services.generation_performance_policy_service import (
    GenerationPerformancePolicyService,
)
from app.services.generation_performance_service import GenerationPerformanceService
from app.services.product_activity_service import ProductActivityService


def _project(database: Database, name: str = "Phase 7") -> int:
    with database.transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects(
                name, project_file, csv_path, output_path, provider,
                settings_json, created_at, updated_at
            )
            VALUES(?, NULL, NULL, NULL, 'mock', '{}', 'now', 'now')
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
    alert_state: str = "none",
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
        alert_state=alert_state,
    )


def _services(
    database: Database,
    now: list[datetime] | None = None,
) -> tuple[
    ProductEventRepository,
    GenerationPerformancePolicyService,
    GenerationPerformanceService,
    ProductActivityService,
]:
    repository = ProductEventRepository(database)
    policy = GenerationPerformancePolicyService(
        repository,
        now_factory=(lambda: now[0]) if now is not None else None,
    )
    performance = GenerationPerformanceService(repository, policy_service=policy)
    activity = ProductActivityService(
        repository,
        performance_service=performance,
        performance_policy_service=policy,
    )
    return repository, policy, performance, activity


def _add_baseline(activity: ProductActivityService, project_id: int) -> None:
    for index in range(3):
        activity.record_batch(
            _record(
                f"baseline-{index}",
                project_id=project_id,
                started_at=f"2026-07-30T{index + 8:02d}:00:00+00:00",
            )
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


def test_phase7_migration_adds_budget_and_alert_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase7.db")
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
        budget_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name = 'generation_performance_budgets'"
        ).fetchone()

    assert 7 in versions
    assert budget_table is not None
    assert {
        "alert_fingerprint",
        "alert_state",
        "alert_notification_id",
        "alert_created_at",
        "alert_acknowledged_at",
    }.issubset(columns)


def test_phase7_project_budget_changes_regression_thresholds(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase7.db")
    database.initialize()
    project_id = _project(database)
    repository, policy, performance, activity = _services(database)
    _add_baseline(activity, project_id)

    candidate = _record(
        "moderate-drop",
        project_id=project_id,
        started_at="2026-07-30T12:00:00+00:00",
        active_seconds=75.0,
        files_per_minute=8.0,
        characters_per_minute=800.0,
    )
    assert performance.analyze(candidate, repository.list_batch_sessions()).severity == "warning"

    policy.save_budget(
        GenerationPerformanceBudget(
            project_id=project_id,
            thresholds=GenerationPerformanceThresholds(
                throughput_drop_warning=0.30,
                throughput_drop_critical=0.50,
                elapsed_increase_warning=0.50,
                elapsed_increase_critical=1.0,
            ),
        )
    )
    assert performance.analyze(candidate, repository.list_batch_sessions()).severity == "none"


def test_phase7_deduplicates_silences_resumes_and_acknowledges_alerts(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "phase7.db")
    database.initialize()
    project_id = _project(database)
    now = [datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)]
    repository, policy, _performance, activity = _services(database, now)
    _add_baseline(activity, project_id)

    activity.record_batch(_regression("first", project_id, now[0].isoformat()))
    first = next(item for item in repository.list_batch_sessions() if item.session_id == "first")
    assert first.alert_state == "open"
    assert first.alert_notification_id
    assert len(repository.list_notifications()) == 1

    now[0] = datetime(2026, 7, 30, 12, 10, tzinfo=timezone.utc)
    duplicate_record = replace(
        _regression("duplicate", project_id, now[0].isoformat()),
        active_seconds=160.0,
        elapsed_seconds=165.0,
        files_per_minute=2.2,
        characters_per_minute=220.0,
    )
    activity.record_batch(duplicate_record)
    duplicate = next(
        item for item in repository.list_batch_sessions() if item.session_id == "duplicate"
    )
    assert duplicate.alert_state == "suppressed"
    assert duplicate.alert_notification_id is None
    assert len(repository.list_notifications()) == 1

    policy.silence(project_id, minutes=60)
    now[0] = datetime(2026, 7, 30, 12, 20, tzinfo=timezone.utc)
    activity.record_batch(_regression("silenced", project_id, now[0].isoformat()))
    silenced = next(
        item for item in repository.list_batch_sessions() if item.session_id == "silenced"
    )
    assert silenced.alert_state == "silenced"
    assert len(repository.list_notifications()) == 1

    policy.resume(project_id)
    now[0] = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)
    activity.record_batch(_regression("resumed", project_id, now[0].isoformat()))
    resumed = next(
        item for item in repository.list_batch_sessions() if item.session_id == "resumed"
    )
    assert resumed.alert_state == "open"
    assert len(repository.list_notifications()) == 2
    assert policy.acknowledge(["resumed"]) == 1
    acknowledged = next(
        item for item in repository.list_batch_sessions() if item.session_id == "resumed"
    )
    assert acknowledged.alert_state == "acknowledged"
    assert acknowledged.alert_acknowledged_at


def test_phase7_budget_round_trip_and_history_export(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase7.db")
    database.initialize()
    project_id = _project(database)
    repository, policy, performance, _activity = _services(database)
    saved = policy.save_budget(
        GenerationPerformanceBudget(
            project_id=project_id,
            enabled=False,
            thresholds=GenerationPerformanceThresholds(minimum_baseline_sessions=5),
            alert_cooldown_minutes=180,
        )
    )
    restored = policy.budget_for(project_id)
    assert restored == saved

    record = replace(
        _record(
            "export-alert",
            project_id=project_id,
            started_at="2026-07-30T12:00:00+00:00",
        ),
        health_score=65.0,
        regression_severity="warning",
        regression_reasons=["Throughput dropped 20.0%"],
        alert_fingerprint="fingerprint-a",
        alert_state="acknowledged",
        alert_notification_id="notification-a",
        alert_created_at="2026-07-30T12:01:00+00:00",
        alert_acknowledged_at="2026-07-30T12:02:00+00:00",
    )
    repository.add_batch_session(record)
    service = GenerationHistoryService(repository, performance, policy)
    json_path, csv_path = service.export([record], tmp_path, project_name="Phase 7")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["sessions"][0]["alert_state"] == "acknowledged"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "alert_fingerprint" in csv_text
    assert "notification-a" in csv_text


def test_phase7_history_dialog_filters_and_acknowledges(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_history_dialog import GenerationHistoryDialog

    database = Database(tmp_path / "phase7.db")
    database.initialize()
    project_id = _project(database)
    repository, policy, performance, _activity = _services(database)
    repository.add_batch_session(
        replace(
            _record(
                "dialog-open",
                project_id=project_id,
                started_at="2026-07-30T12:00:00+00:00",
            ),
            health_score=50.0,
            regression_severity="critical",
            alert_fingerprint="dialog-fingerprint",
            alert_state="open",
            alert_created_at="2026-07-30T12:01:00+00:00",
        )
    )
    dialog = GenerationHistoryDialog(
        GenerationHistoryService(repository, performance, policy),
        project_id=project_id,
        project_name="Phase 7",
        export_dir=tmp_path / "exports",
        open_path=lambda _path: None,
        copy_path=lambda _path: None,
    )

    assert dialog.table.columnCount() == 16
    dialog.alert_filter.setCurrentIndex(dialog.alert_filter.findData("open"))
    assert dialog.table.rowCount() == 1
    dialog.table.selectRow(0)
    dialog.acknowledge_selected()
    assert "Acknowledged 1" in dialog.status_label.text()
    assert repository.list_batch_sessions(project_id=project_id)[0].alert_state == "acknowledged"
