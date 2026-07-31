from __future__ import annotations

import json
from pathlib import Path

from app.database.connection import Database
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_history_service import GenerationHistoryService
from app.services.generation_performance_service import GenerationPerformanceService
from app.services.product_activity_service import ProductActivityService


def _project(database: Database, name: str = "Phase 6") -> int:
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
    health_score: float = 0.0,
    regression_severity: str = "insufficient_data",
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
        health_score=health_score,
        regression_severity=regression_severity,
    )


def test_phase6_migration_adds_performance_analysis_columns(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase6.db")
    database.initialize()

    with database.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(batch_sessions)").fetchall()
        }
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }

    assert 6 in versions
    assert {
        "health_score",
        "baseline_session_id",
        "regression_severity",
        "regression_reasons_json",
        "baseline_metrics_json",
        "performance_deltas_json",
    }.issubset(columns)


def test_phase6_detects_persists_and_notifies_critical_regression(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase6.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    performance = GenerationPerformanceService(repository)
    activity = ProductActivityService(repository, performance_service=performance)

    for index in range(3):
        activity.record_batch(
            _record(
                f"baseline-{index}",
                project_id=project_id,
                started_at=f"2026-07-30T{index + 8:02d}:00:00+00:00",
            )
        )

    analysis = activity.record_batch(
        _record(
            "regression",
            project_id=project_id,
            started_at="2026-07-30T12:00:00+00:00",
            result="failed",
            completed=6,
            failed=4,
            retries=5,
            active_seconds=150.0,
            files_per_minute=2.4,
            characters_per_minute=240.0,
        )
    )

    assert analysis is not None
    assert analysis.severity == "critical"
    assert analysis.baseline.sample_count == 3
    assert analysis.health_score < 50.0
    restored = repository.list_batch_sessions(project_id=project_id)
    candidate = next(record for record in restored if record.session_id == "regression")
    assert candidate.regression_severity == "critical"
    assert candidate.baseline_session_id == "baseline-2"
    assert candidate.regression_reasons
    assert candidate.baseline_metrics["sample_count"] == 3
    assert repository.list_notifications()[0].title == "Critical generation regression"
    assert repository.list_activity(project_id=project_id)[0].category == "generation-performance"


def test_phase6_requires_enough_comparable_baseline_sessions(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase6.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    performance = GenerationPerformanceService(repository)
    record = _record(
        "first",
        project_id=project_id,
        started_at="2026-07-30T08:00:00+00:00",
    )
    repository.add_batch_session(record)

    analysis = performance.analyze_and_persist(record)

    assert analysis.severity == "insufficient_data"
    assert analysis.baseline.sample_count == 0
    restored = repository.list_batch_sessions(project_id=project_id)[0]
    assert restored.health_score == 100.0
    assert restored.regression_severity == "insufficient_data"


def test_phase6_reanalysis_and_trend_summary(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase6.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationHistoryService(repository)
    records = [
        _record(
            f"session-{index}",
            project_id=project_id,
            started_at=f"2026-07-30T{index + 8:02d}:00:00+00:00",
            health_score=score,
            regression_severity=severity,
        )
        for index, (score, severity) in enumerate(
            [(95.0, "none"), (90.0, "none"), (75.0, "warning"), (50.0, "critical")]
        )
    ]
    for record in records:
        repository.add_batch_session(record)

    trend = service.trend(records, window_size=4)
    analyses = service.reanalyze(records)

    assert trend.direction == "degrading"
    assert trend.health_delta < 0
    assert trend.warning_count == 1
    assert trend.critical_count == 1
    assert len(analyses) == 4
    refreshed = repository.list_batch_sessions(project_id=project_id)
    assert all(record.health_score > 0 for record in refreshed)


def test_phase6_history_export_includes_performance_fields(tmp_path: Path) -> None:
    record = _record(
        "export-performance",
        project_id=1,
        started_at="2026-07-30T08:00:00+00:00",
        health_score=72.5,
        regression_severity="warning",
    )
    record = BatchSessionRecord(
        **{
            **record.__dict__,
            "baseline_session_id": "baseline-a",
            "regression_reasons": ["Throughput dropped 20.0%"],
            "baseline_metrics": {"sample_count": 3},
            "performance_deltas": {"characters_per_minute_ratio": -0.2},
        }
    )

    json_path, csv_path = GenerationHistoryService.export(
        [record],
        tmp_path,
        project_name="Phase 6",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["warning_regressions"] == 1
    assert payload["sessions"][0]["health_score"] == 72.5
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "regression_reasons_json" in csv_text
    assert "baseline-a" in csv_text


def test_phase6_history_dialog_filters_and_recalculates(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_history_dialog import GenerationHistoryDialog

    database = Database(tmp_path / "phase6.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    for index in range(4):
        repository.add_batch_session(
            _record(
                f"dialog-{index}",
                project_id=project_id,
                started_at=f"2026-07-30T{index + 8:02d}:00:00+00:00",
            )
        )
    dialog = GenerationHistoryDialog(
        GenerationHistoryService(repository),
        project_id=project_id,
        project_name="Phase 6",
        export_dir=tmp_path / "exports",
        open_path=lambda _path: None,
        copy_path=lambda _path: None,
    )

    assert dialog.table.columnCount() == 16
    dialog.reanalyze_all()
    assert "Recalculated 4 sessions" in dialog.status_label.text()
    dialog.regression_filter.setCurrentIndex(dialog.regression_filter.findData("none"))
    assert dialog.table.rowCount() >= 1
    dialog.close()
