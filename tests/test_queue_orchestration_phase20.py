from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.release import SCHEMA_VERSION
from app.models.domain import AppSettings, TTSJob
from app.models.generation_orchestration import (
    DeadlineRiskLevel,
    GenerationQueueForecast,
    ProviderRoutingMetric,
)
from app.repositories.generation_orchestration_repository import (
    GenerationOrchestrationRepository,
)
from app.repositories.product_event_repository import ProductEventRepository
from app.services.activity_timeline_service import ActivityTimelineService
from app.services.notification_center_service import NotificationCenterService
from app.services.api_profile_service import ApiProfileService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.secure_credentials import SecureCredentialStore


def _project(database: Database, name: str = "Phase 20") -> int:
    with database.transaction() as connection:
        cursor = connection.execute(
            """
            INSERT INTO projects(
                name, project_file, csv_path, output_path, provider,
                settings_json, created_at, updated_at
            ) VALUES(?, NULL, NULL, NULL, 'elevenlabs', '{}', 'now', 'now')
            """,
            (name,),
        )
        return int(cursor.lastrowid)


def _service(tmp_path: Path, database: Database, now: datetime):
    profiles = ApiProfileService(
        tmp_path / "api-profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    return GenerationOrchestrationService(
        GenerationOrchestrationRepository(database),
        profiles,
        now_factory=lambda: now,
    )


def _jobs(*, count: int = 4, characters: int = 1000) -> list[TTSJob]:
    return [
        TTSJob(
            row_number=index,
            text="x" * characters,
            filename=f"job-{index}.mp3",
        )
        for index in range(1, count + 1)
    ]


def test_phase20_migration_adds_deadline_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 20")
        connection.execute("DROP TABLE generation_queue_forecasts")
        connection.execute("DROP TABLE generation_deadline_scheduling_policies")
        connection.commit()

    database.initialize()

    with database.connect() as connection:
        versions = tuple(
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert versions == tuple(range(1, SCHEMA_VERSION + 1))
    assert {
        "generation_deadline_scheduling_policies",
        "generation_queue_forecasts",
    }.issubset(tables)
    backup = database.path.with_suffix(database.path.suffix + ".pre-v20.bak")
    assert backup.exists()
    assert Database(backup).quick_check() == "ok"


def test_phase20_deadline_policy_normalizes_values(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)

    saved = service.save_deadline_policy(
        replace(
            service.default_deadline_policy(project_id),
            enabled=True,
            target_completion_minutes=0,
            warning_slack_minutes=-10,
            maximum_deadline_concurrency=100,
            fallback_characters_per_minute=0,
            safety_margin_percent=100,
        )
    )

    assert saved.target_completion_minutes == 1
    assert saved.warning_slack_minutes == 0
    assert saved.maximum_deadline_concurrency == 32
    assert saved.fallback_characters_per_minute == 1
    assert saved.safety_margin_percent == 90
    assert service.get_deadline_policy(project_id) == saved


def test_phase20_forecast_persists_deadline_risk_and_recommendation(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)
    service.save_deadline_policy(
        replace(
            service.default_deadline_policy(project_id),
            enabled=True,
            target_completion_minutes=3,
            warning_slack_minutes=1,
            maximum_deadline_concurrency=8,
            fallback_characters_per_minute=1000,
            safety_margin_percent=0,
            persist_forecasts=True,
        )
    )

    forecast = service.forecast_queue(
        project_id=project_id,
        provider="elevenlabs",
        jobs=_jobs(count=4, characters=3000),
        current_concurrency=1,
    )

    assert forecast.source == "fallback"
    assert forecast.risk_level == DeadlineRiskLevel.MISSED
    assert forecast.recommended_concurrency == 4
    assert forecast.slack_seconds < 0
    assert "Increase concurrency" in forecast.recommendation
    stored = service.repository.list_queue_forecasts(project_id=project_id)
    assert [item.forecast_id for item in stored] == [forecast.forecast_id]


def test_phase20_forecast_prefers_historical_throughput(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)
    service.save_deadline_policy(
        replace(
            service.default_deadline_policy(project_id),
            enabled=True,
            target_completion_minutes=10,
            warning_slack_minutes=1,
            fallback_characters_per_minute=100,
            safety_margin_percent=0,
            persist_forecasts=False,
        )
    )
    service.repository.save_routing_metric(
        ProviderRoutingMetric(
            metric_key=service.repository.metric_key(
                project_id, "elevenlabs", "primary"
            ),
            project_id=project_id,
            provider="elevenlabs",
            profile_id="primary",
            profile_name="Primary",
            attempts=10,
            successes=10,
            total_latency_seconds=600.0,
            total_characters=12_000,
            updated_at=now.isoformat(),
        )
    )

    forecast = service.forecast_queue(
        project_id=project_id,
        provider="elevenlabs",
        jobs=_jobs(count=2, characters=1000),
        current_concurrency=1,
        persist=False,
    )

    assert forecast.source == "historical"
    assert forecast.characters_per_minute == 1200.0
    assert forecast.risk_level == DeadlineRiskLevel.ON_TRACK
    assert service.repository.list_queue_forecasts(project_id=project_id) == []


def test_phase20_at_risk_plan_boosts_concurrency_before_start(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)
    service.save_deadline_policy(
        replace(
            service.default_deadline_policy(project_id),
            enabled=True,
            target_completion_minutes=2,
            warning_slack_minutes=1,
            allow_concurrency_boost=True,
            maximum_deadline_concurrency=8,
            fallback_characters_per_minute=1000,
            safety_margin_percent=0,
        )
    )

    plan = service.build_plan(
        project_id=project_id,
        settings=AppSettings(
            provider="elevenlabs",
            api_key="temporary-key",
            skip_existing=False,
            delay_seconds=0,
        ),
        jobs=_jobs(count=4, characters=1000),
    )

    assert plan.deadline_enabled
    assert plan.deadline_risk_level == DeadlineRiskLevel.MISSED
    assert plan.deadline_recommended_concurrency == 2
    assert plan.scheduling_enabled
    assert plan.initial_concurrency == 2
    assert plan.maximum_concurrency >= 2
    assert plan.queue_forecast_id


def test_phase20_deadline_boost_can_be_disabled(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)
    service.save_deadline_policy(
        replace(
            service.default_deadline_policy(project_id),
            enabled=True,
            target_completion_minutes=2,
            allow_concurrency_boost=False,
            maximum_deadline_concurrency=8,
            fallback_characters_per_minute=1000,
            safety_margin_percent=0,
        )
    )

    plan = service.build_plan(
        project_id=project_id,
        settings=AppSettings(provider="elevenlabs", api_key="temporary-key"),
        jobs=_jobs(count=4, characters=1000),
    )

    assert plan.deadline_recommended_concurrency == 2
    assert not plan.scheduling_enabled
    assert plan.initial_concurrency == 1


def test_phase20_export_includes_forecasts_without_credentials(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)
    service.repository.add_queue_forecast(
        GenerationQueueForecast(
            forecast_id="forecast-export",
            project_id=project_id,
            provider="elevenlabs",
            job_count=2,
            total_characters=2000,
            current_concurrency=1,
            recommended_concurrency=2,
            characters_per_minute=1000.0,
            estimated_duration_seconds=120.0,
            estimated_finish_at=now.isoformat(),
            deadline_at=now.isoformat(),
            slack_seconds=-60.0,
            risk_score=1.0,
            risk_level=DeadlineRiskLevel.MISSED,
            recommendation="Increase concurrency.",
            source="fallback",
            created_at=now.isoformat(),
            metadata={"api_key": "must-not-leak", "required_concurrency": 2},
        )
    )

    json_path, csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
        project_name="Phase 20",
    )
    json_text = json_path.read_text(encoding="utf-8")
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    payload = json.loads(json_text)

    assert payload["deadline_policy"]["project_id"] == project_id
    assert payload["queue_forecasts"][0]["forecast_id"] == "forecast-export"
    assert "queue_forecast" in csv_text
    assert "must-not-leak" not in json_text
    assert "must-not-leak" not in csv_text



def test_phase20_at_risk_forecast_publishes_activity_and_notification(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    profiles = ApiProfileService(
        tmp_path / "api-profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    product_events = ProductEventRepository(database)
    activity = ActivityTimelineService(product_events)
    notifications = NotificationCenterService(product_events)
    service = GenerationOrchestrationService(
        GenerationOrchestrationRepository(database),
        profiles,
        notifications,
        activity,
        now_factory=lambda: now,
    )
    service.save_deadline_policy(
        replace(
            service.default_deadline_policy(project_id),
            enabled=True,
            target_completion_minutes=1,
            warning_slack_minutes=1,
            fallback_characters_per_minute=1000,
            safety_margin_percent=0,
        )
    )

    forecast = service.forecast_queue(
        project_id=project_id,
        provider="elevenlabs",
        jobs=_jobs(count=2, characters=2000),
        current_concurrency=1,
    )

    assert forecast.risk_level == DeadlineRiskLevel.MISSED
    assert any(
        event.category == "generation_deadline"
        for event in activity.list(project_id=project_id)
    )
    assert any(
        item.action_payload == "generation-orchestration"
        for item in notifications.list()
    )

def test_phase20_dialog_exposes_deadline_policy(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_orchestration_dialog import (
        GenerationOrchestrationDialog,
    )

    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase20.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database, now)
    dialog = GenerationOrchestrationDialog(
        service,
        project_id=project_id,
        project_name="Phase 20",
        export_dir=tmp_path / "exports",
    )

    assert dialog.forecast_table.columnCount() == 12
    dialog.deadline_enabled.setChecked(True)
    dialog.target_completion_minutes.setValue(45)
    dialog.maximum_deadline_concurrency.setValue(6)
    dialog.save_deadline_policy()

    saved = service.get_deadline_policy(project_id)
    assert saved.enabled
    assert saved.target_completion_minutes == 45
    assert saved.maximum_deadline_concurrency == 6
