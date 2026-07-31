from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config.runtime import RuntimeConfig
from app.database.connection import Database
from app.models.domain import AppSettings, TTSJob
from app.models.generation_cost_capacity import (
    GenerationCostBudgetPolicy,
    GenerationPricingRate,
)
from app.models.product_events import BatchSessionRecord
from app.repositories.job_repository import JobRepository
from app.repositories.product_event_repository import ProductEventRepository
from app.services.generation_cost_capacity_service import GenerationCostCapacityService
from app.services.preflight_service import PreflightService
from app.services.product_activity_service import ProductActivityService


def _project(database: Database, name: str = "Phase 15") -> int:
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
    model: str = "model-a",
    total: int = 100,
    completed: int = 100,
    failed: int = 0,
    retries: int = 0,
    characters: int = 10_000,
    files_per_minute: float = 20.0,
    characters_per_minute: float = 2_000.0,
    monitor_metrics: dict[str, object] | None = None,
) -> BatchSessionRecord:
    return BatchSessionRecord(
        session_id=session_id,
        project_id=project_id,
        scope="all",
        provider=provider,
        model=model,
        voice="voice-a",
        total_jobs=total,
        completed_jobs=completed,
        failed_jobs=failed,
        skipped_jobs=max(0, total - completed - failed),
        character_count=characters,
        report_path=None,
        output_path=None,
        result="completed" if failed == 0 else "failed",
        started_at=started_at.isoformat(),
        finished_at=(started_at + timedelta(minutes=5)).isoformat(),
        elapsed_seconds=300.0,
        active_seconds=300.0,
        retry_events=retries,
        files_per_minute=files_per_minute,
        characters_per_minute=characters_per_minute,
        monitor_metrics=monitor_metrics or {},
    )


def _runtime(root: Path) -> RuntimeConfig:
    return RuntimeConfig.from_root(root)


def test_phase15_migration_adds_cost_capacity_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 15")
        connection.execute("DROP TABLE generation_cost_capacity_snapshots")
        connection.execute("DROP TABLE generation_session_costs")
        connection.execute("DROP TABLE generation_pricing_rates")
        connection.execute("DROP TABLE generation_cost_budget_policies")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = {
            int(row[0])
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert 15 in versions
    assert "generation_cost_budget_policies" in tables
    assert "generation_pricing_rates" in tables
    assert "generation_session_costs" in tables
    assert "generation_cost_capacity_snapshots" in tables
    assert database.path.with_suffix(database.path.suffix + ".pre-v15.bak").exists()


def test_phase15_policy_and_pricing_precedence(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationCostCapacityService(repository)

    service.save_policy(
        replace(
            service.default_policy(None),
            currency="eur",
            default_price_per_million_characters=10.0,
            monthly_budget=100.0,
        )
    )
    inherited = service.get_policy(project_id)
    assert inherited.project_id == project_id
    assert inherited.currency == "EUR"
    assert inherited.default_price_per_million_characters == 10.0

    rates = (
        GenerationPricingRate("global-all", None, "mock", "*", 20.0, "EUR"),
        GenerationPricingRate("global-model", None, "mock", "model-a", 25.0, "EUR"),
        GenerationPricingRate("project-all", project_id, "mock", "*", 30.0, "EUR"),
        GenerationPricingRate(
            "project-model",
            project_id,
            "mock",
            "model-a",
            35.0,
            "EUR",
        ),
    )
    for rate in rates:
        service.save_rate(rate)

    exact = service.rate_for(
        project_id=project_id,
        provider="mock",
        model="model-a",
    )
    wildcard = service.rate_for(
        project_id=project_id,
        provider="mock",
        model="model-b",
    )
    global_exact = service.rate_for(
        project_id=None,
        provider="mock",
        model="model-a",
    )
    fallback = service.rate_for(
        project_id=project_id,
        provider="other",
        model="model-x",
    )

    assert exact[:2] == (35.0, "EUR")
    assert wildcard[:2] == (30.0, "EUR")
    assert global_exact[:2] == (25.0, "EUR")
    assert fallback[:2] == (10.0, "EUR")


def test_phase15_records_session_cost_retry_waste_and_actual_cost(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationCostCapacityService(repository, now_factory=lambda: now)
    service.save_rate(
        GenerationPricingRate(
            "mock-rate",
            project_id,
            "mock",
            "model-a",
            100.0,
            "USD",
        )
    )
    record = _session(
        "cost-session",
        project_id,
        now - timedelta(hours=1),
        retries=10,
    )
    repository.add_batch_session(record)

    cost = service.record_session(record)

    assert cost.character_count == 10_000
    assert cost.retry_characters == 1_000
    assert cost.billable_characters == 11_000
    assert cost.estimated_cost == pytest.approx(1.1)
    assert repository.get_session_cost(record.session_id) == cost

    actual_record = replace(
        record,
        session_id="actual-session",
        monitor_metrics={"actual_cost": 0.75, "cost_currency": "USD"},
    )
    repository.add_batch_session(actual_record)
    actual = service.record_session(actual_record)
    assert actual.actual_cost == 0.75
    assert actual.effective_cost == 0.75
    assert actual.cost_source == "provider-actual"


def test_phase15_queue_forecast_uses_historical_capacity_and_current_jobs(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    jobs = JobRepository(database)
    service = GenerationCostCapacityService(
        repository,
        jobs,
        now_factory=lambda: now,
    )
    service.save_rate(
        GenerationPricingRate(
            "queue-rate",
            project_id,
            "mock",
            "model-a",
            50.0,
            "USD",
        )
    )
    for index in range(3):
        repository.add_batch_session(
            _session(
                f"history-{index}",
                project_id,
                now - timedelta(days=index + 1),
                files_per_minute=20.0,
                characters_per_minute=2_000.0,
            )
        )
    jobs.upsert_jobs(
        project_id,
        [
            TTSJob(row_number=1, filename="one.mp3", text="a" * 1_000),
            TTSJob(row_number=2, filename="two.mp3", text="b" * 2_000),
        ],
    )

    forecast = service.capacity_forecast(
        project_id=project_id,
        provider="mock",
        model="model-a",
        now=now,
    )

    assert forecast.queued_jobs == 2
    assert forecast.queued_characters == 3_000
    assert forecast.characters_per_minute == 2_000.0
    assert forecast.estimated_duration_seconds == pytest.approx(90.0)
    assert forecast.estimated_cost == pytest.approx(0.15)
    assert forecast.confidence == "medium"
    assert forecast.estimated_completion_at == (
        now + timedelta(seconds=90)
    ).isoformat()


def test_phase15_budget_alert_and_snapshot_are_deduplicated(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationCostCapacityService(repository, now_factory=lambda: now)
    service.save_policy(
        GenerationCostBudgetPolicy(
            project_id=project_id,
            currency="USD",
            daily_budget=1.0,
            weekly_budget=10.0,
            monthly_budget=20.0,
            warning_percent=80.0,
            alert_cooldown_minutes=240,
        )
    )
    service.save_rate(
        GenerationPricingRate(
            "budget-rate",
            project_id,
            "mock",
            "model-a",
            200.0,
            "USD",
        )
    )
    record = _session(
        "budget-session",
        project_id,
        now - timedelta(minutes=30),
        characters=10_000,
    )
    repository.add_batch_session(record)
    service.record_session(record)

    first = service.evaluate_and_persist(
        project_id=project_id,
        provider="mock",
        model="model-a",
        now=now,
    )
    second = service.evaluate_and_persist(
        project_id=project_id,
        provider="mock",
        model="model-a",
        now=now + timedelta(minutes=5),
    )

    assert first.state == "critical"
    assert first.daily_spend == pytest.approx(2.0)
    assert first.daily_budget_usage_percent == pytest.approx(200.0)
    assert first.alert_notification_id is not None
    assert second.alert_notification_id is None
    notifications = [
        item
        for item in repository.list_notifications()
        if item.title == "Generation cost budget exceeded"
    ]
    assert len(notifications) == 1
    assert len(repository.list_cost_capacity_snapshots(project_id=project_id)) == 2



def test_phase15_product_activity_records_cost_and_snapshot(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    cost_service = GenerationCostCapacityService(repository, now_factory=lambda: now)
    cost_service.save_rate(
        GenerationPricingRate(
            "activity-rate",
            project_id,
            "mock",
            "model-a",
            100.0,
            "USD",
        )
    )
    activity = ProductActivityService(
        repository,
        cost_capacity_service=cost_service,
    )
    record = _session(
        "activity-session",
        project_id,
        now - timedelta(minutes=10),
    )

    analysis = activity.record_batch(record)

    assert analysis is None
    assert repository.get_session_cost(record.session_id) is not None
    snapshots = repository.list_cost_capacity_snapshots(project_id=project_id)
    assert len(snapshots) == 1
    assert snapshots[0].session_count == 1

def test_phase15_preflight_includes_estimated_cost(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    cost_service = GenerationCostCapacityService(repository)
    cost_service.save_rate(
        GenerationPricingRate(
            "preflight-rate",
            project_id,
            "mock",
            "model-a",
            100.0,
            "USD",
        )
    )
    runtime = _runtime(tmp_path / "runtime")
    runtime.ensure_directories()
    preflight = PreflightService(runtime, cost_capacity_service=cost_service)
    output = tmp_path / "output"
    output.mkdir()

    state = preflight.run(
        jobs=[TTSJob(row_number=1, filename="one.wav", text="x" * 10_000)],
        settings=AppSettings(
            provider="mock",
            model_id="model-a",
            voice_id="mock",
            api_key="",
            file_extension=".wav",
        ),
        output_dir=output,
        project_id=project_id,
    )

    assert state.estimated_cost == pytest.approx(1.0)
    assert "Estimated cost: 1.0000" in preflight.markdown(state)
    assert "Estimated cost: 1.0000" in preflight.html(state)


def test_phase15_provider_efficiency_snapshot_round_trip_and_export(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationCostCapacityService(repository, now_factory=lambda: now)
    for provider, price in (("mock", 100.0), ("azure", 50.0)):
        service.save_rate(
            GenerationPricingRate(
                f"{provider}-rate",
                project_id,
                provider,
                "model-a",
                price,
                "USD",
            )
        )
        record = _session(
            f"{provider}-session",
            project_id,
            now - timedelta(hours=1),
            provider=provider,
        )
        repository.add_batch_session(record)
        service.record_session(record)

    saved = service.evaluate_and_persist(
        project_id=project_id,
        provider="mock",
        model="model-a",
        now=now,
    )
    restored = repository.list_cost_capacity_snapshots(project_id=project_id)
    dashboard = service.dashboard(
        project_id=project_id,
        provider="mock",
        model="model-a",
        now=now,
    )
    json_path, csv_path = service.export(
        dashboard,
        tmp_path / "exports",
        project_name="Phase 15",
    )

    assert restored[0] == saved
    providers = {item.provider: item for item in dashboard.snapshot.provider_metrics}
    assert providers["azure"].total_cost == pytest.approx(0.5)
    assert providers["mock"].total_cost == pytest.approx(1.0)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["snapshot"]["session_count"] == 2
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert "effective_cost" in rows[0]


def test_phase15_cost_capacity_dialog_renders_dashboard(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_cost_capacity_dialog import (
        GenerationCostCapacityDialog,
    )

    now = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase15.db")
    database.initialize()
    project_id = _project(database)
    repository = ProductEventRepository(database)
    service = GenerationCostCapacityService(repository, now_factory=lambda: now)
    service.save_rate(
        GenerationPricingRate(
            "dialog-rate",
            project_id,
            "mock",
            "model-a",
            100.0,
            "USD",
        )
    )
    record = _session(
        "dialog-session",
        project_id,
        now - timedelta(hours=1),
    )
    repository.add_batch_session(record)
    service.record_session(record)

    dialog = GenerationCostCapacityDialog(
        service,
        project_id=project_id,
        project_name="Phase 15",
        provider="mock",
        model="model-a",
        export_dir=tmp_path / "exports",
    )

    assert dialog.budget_table.columnCount() == 4
    assert dialog.budget_table.rowCount() == 5
    assert dialog.provider_table.columnCount() == 11
    assert dialog.provider_table.rowCount() == 1
    assert dialog.rate_table.rowCount() == 1
    assert dialog.session_table.rowCount() == 1
    assert "Healthy" in dialog.state_label.text()
