from __future__ import annotations

import json
from pathlib import Path

from app.database.connection import Database
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_history_service import GenerationHistoryService


def _project(database: Database, name: str = "Phase 5") -> int:
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
    provider: str = "mock",
    total: int = 10,
    completed: int = 10,
    failed: int = 0,
    retries: int = 0,
    elapsed: float = 60.0,
    files_per_minute: float = 10.0,
) -> BatchSessionRecord:
    return BatchSessionRecord(
        session_id=session_id,
        project_id=project_id,
        scope="row_range",
        provider=provider,
        model="model-a",
        voice="voice-a",
        total_jobs=total,
        completed_jobs=completed,
        failed_jobs=failed,
        skipped_jobs=max(0, total - completed - failed),
        character_count=total * 100,
        report_path=f"/reports/{session_id}/report.html",
        output_path=f"/output/{session_id}",
        result=result,
        started_at=started_at,
        finished_at=started_at,
        elapsed_seconds=elapsed,
        active_seconds=max(0.0, elapsed - 5.0),
        paused_seconds=5.0,
        retry_events=retries,
        files_per_minute=files_per_minute,
        characters_per_minute=files_per_minute * 100.0,
        failure_summary={"failed": failed, "categories": {"network": failed} if failed else {}},
        monitor_metrics={"stalled": False, "retry_events": retries},
    )


def test_phase5_migration_adds_generation_history_telemetry(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase5.db")
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

    assert 5 in versions
    assert {
        "elapsed_seconds",
        "active_seconds",
        "paused_seconds",
        "retry_events",
        "files_per_minute",
        "characters_per_minute",
        "failure_summary_json",
        "monitor_metrics_json",
    }.issubset(columns)


def test_phase5_repository_round_trip_and_filters(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase5.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    repository.add_batch_session(
        _record(
            "session-a",
            project_id=project_id,
            started_at="2026-07-30T08:00:00+00:00",
            result="failed",
            provider="elevenlabs",
            completed=8,
            failed=2,
            retries=3,
        )
    )
    repository.add_batch_session(
        _record(
            "session-b",
            project_id=None,
            started_at="2026-07-30T09:00:00+00:00",
        )
    )

    restored = repository.list_batch_sessions(
        project_id=project_id,
        provider="elevenlabs",
        result="failed",
    )

    assert [record.session_id for record in restored] == ["session-a"]
    assert restored[0].retry_events == 3
    assert restored[0].failure_summary["categories"] == {"network": 2}
    assert restored[0].monitor_metrics["stalled"] is False


def test_phase5_summary_and_comparison() -> None:
    baseline = _record(
        "baseline",
        project_id=1,
        started_at="2026-07-30T08:00:00+00:00",
        total=10,
        completed=8,
        failed=2,
        retries=3,
        elapsed=120.0,
        files_per_minute=4.0,
    )
    candidate = _record(
        "candidate",
        project_id=1,
        started_at="2026-07-30T09:00:00+00:00",
        total=10,
        completed=10,
        failed=0,
        retries=1,
        elapsed=60.0,
        files_per_minute=10.0,
    )

    summary = GenerationHistoryService.summary([baseline, candidate])
    comparison = GenerationHistoryService.compare(baseline, candidate)

    assert summary.session_count == 2
    assert summary.total_jobs == 20
    assert summary.completion_rate == 90.0
    assert summary.retry_events == 4
    assert summary.providers == {"mock": 2}
    assert comparison.completion_rate_delta == 20.0
    assert comparison.elapsed_seconds_delta == -60.0
    assert comparison.files_per_minute_delta == 6.0
    assert comparison.retry_events_delta == -2
    assert comparison.failed_jobs_delta == -2


def test_phase5_history_export_writes_json_and_csv(tmp_path: Path) -> None:
    records = [
        _record(
            "export-a",
            project_id=1,
            started_at="2026-07-30T08:00:00+00:00",
            retries=2,
        )
    ]

    json_path, csv_path = GenerationHistoryService.export(
        records,
        tmp_path,
        project_name="Phase 5",
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["session_count"] == 1
    assert payload["sessions"][0]["session_id"] == "export-a"
    assert "failure_summary_json" in csv_path.read_text(encoding="utf-8-sig")


def test_phase5_history_dialog_filters_compares_and_exports(qt_app, tmp_path: Path) -> None:
    from PySide6.QtCore import QItemSelectionModel

    from app.gui.dialogs.generation_history_dialog import GenerationHistoryDialog

    database = Database(tmp_path / "phase5.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    repository.add_batch_session(
        _record(
            "older",
            project_id=project_id,
            started_at="2026-07-30T08:00:00+00:00",
            completed=8,
            failed=2,
            elapsed=120.0,
            files_per_minute=4.0,
        )
    )
    repository.add_batch_session(
        _record(
            "newer",
            project_id=project_id,
            started_at="2026-07-30T09:00:00+00:00",
            elapsed=60.0,
            files_per_minute=10.0,
        )
    )
    repository.add_batch_session(
        _record(
            "other-project",
            project_id=None,
            started_at="2026-07-30T10:00:00+00:00",
        )
    )
    opened: list[Path] = []
    copied: list[Path] = []
    dialog = GenerationHistoryDialog(
        GenerationHistoryService(repository),
        project_id=project_id,
        project_name="Phase 5",
        export_dir=tmp_path / "exports",
        open_path=opened.append,
        copy_path=copied.append,
    )

    assert dialog.table.rowCount() == 2
    selection = dialog.table.selectionModel()
    model = dialog.table.model()
    selection.select(
        model.index(0, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )
    selection.select(
        model.index(1, 0),
        QItemSelectionModel.Select | QItemSelectionModel.Rows,
    )
    dialog.compare_selected()

    assert "Completion-rate delta" in dialog.details.toPlainText()
    exported = dialog.export_filtered()
    assert exported is not None
    assert all(path.exists() for path in exported)
    dialog.close()
