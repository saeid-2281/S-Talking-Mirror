from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.release import SCHEMA_VERSION
from app.models.generation_orchestration import (
    DeadlineRiskLevel,
    GenerationOrchestrationViewPreferences,
    GenerationQueueForecast,
    OrchestrationPreset,
    ProviderCircuitSnapshot,
    ProviderCircuitStatus,
    ProviderRoutingMetric,
    ProviderThrottleSnapshot,
    RoutingMode,
    SchedulingMode,
)
from app.repositories.generation_orchestration_repository import (
    GenerationOrchestrationRepository,
)
from app.services.api_profile_service import ApiProfileService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.secure_credentials import SecureCredentialStore


def _project(database: Database, name: str = "Phase 21") -> int:
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


def _service(tmp_path: Path, database: Database) -> GenerationOrchestrationService:
    return GenerationOrchestrationService(
        GenerationOrchestrationRepository(database),
        ApiProfileService(
            tmp_path / "api-profiles.json",
            SecureCredentialStore(tmp_path / "credentials"),
        ),
        now_factory=lambda: datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc),
    )


def test_phase21_migration_adds_view_preferences_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase21.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 21")
        connection.execute("DROP TABLE generation_orchestration_view_preferences")
        connection.commit()

    database.initialize()

    assert database.applied_schema_versions() == tuple(range(1, SCHEMA_VERSION + 1))
    backup = database.path.with_suffix(database.path.suffix + ".pre-v21.bak")
    assert backup.exists()
    assert Database(backup).quick_check() == "ok"


def test_phase21_view_preferences_are_normalized_and_persisted(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase21.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)

    saved = service.save_view_preferences(
        GenerationOrchestrationViewPreferences(
            project_id=project_id,
            selected_tab=99,
            auto_refresh=True,
            refresh_interval_seconds=1,
            table_density="unknown",
            search_text="x" * 300,
            status_filter="invalid",
        )
    )

    assert saved.preference_key == f"project:{project_id}"
    assert saved.selected_tab == 12
    assert saved.refresh_interval_seconds == 3
    assert saved.table_density == "comfortable"
    assert len(saved.search_text) == 200
    assert saved.status_filter == "all"
    assert service.get_view_preferences(project_id) == saved


def test_phase21_operational_presets_update_all_policy_groups(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase21.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)

    throughput = service.apply_preset(project_id, OrchestrationPreset.THROUGHPUT)

    assert throughput["preset"] == "throughput"
    assert service.get_policy(project_id).auto_failover
    assert service.get_routing_policy(project_id).mode == RoutingMode.ADAPTIVE
    assert service.get_scheduling_policy(project_id).mode == SchedulingMode.ADAPTIVE
    assert service.get_scheduling_policy(project_id).initial_concurrency == 4
    assert service.get_scheduling_policy(project_id).maximum_concurrency == 8

    service.apply_preset(project_id, OrchestrationPreset.SAFE)
    assert not service.get_routing_policy(project_id).enabled
    assert not service.get_scheduling_policy(project_id).enabled
    assert service.get_scheduling_policy(project_id).maximum_concurrency == 1
    assert not service.get_deadline_policy(project_id).allow_concurrency_boost


def test_phase21_dashboard_summary_prioritizes_operator_risk(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase21.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    repository = service.repository
    now = "2026-07-31T14:00:00+00:00"

    repository.save_routing_metric(
        ProviderRoutingMetric(
            metric_key=repository.metric_key(project_id, "elevenlabs", "primary"),
            project_id=project_id,
            provider="elevenlabs",
            profile_id="primary",
            profile_name="Primary",
            attempts=10,
            successes=7,
            failures=3,
            health_score=68.0,
            updated_at=now,
        )
    )
    repository.save_circuit(
        ProviderCircuitSnapshot(
            state_key=repository.state_key(project_id, "elevenlabs", "primary"),
            project_id=project_id,
            provider="elevenlabs",
            profile_id="primary",
            profile_name="Primary",
            status=ProviderCircuitStatus.OPEN,
            consecutive_failures=3,
            updated_at=now,
        )
    )
    repository.save_throttle_state(
        ProviderThrottleSnapshot(
            throttle_key=repository.throttle_key(project_id, "elevenlabs", "primary"),
            project_id=project_id,
            provider="elevenlabs",
            profile_id="primary",
            profile_name="Primary",
            current_concurrency=1,
            recent_rate_limits=2,
            updated_at=now,
        )
    )
    repository.add_queue_forecast(
        GenerationQueueForecast(
            forecast_id="phase21-risk",
            project_id=project_id,
            provider="elevenlabs",
            job_count=10,
            total_characters=10000,
            current_concurrency=1,
            recommended_concurrency=4,
            characters_per_minute=1000,
            estimated_duration_seconds=600,
            estimated_finish_at=now,
            deadline_at=now,
            slack_seconds=-120,
            risk_score=1.0,
            risk_level=DeadlineRiskLevel.MISSED,
            recommendation="Increase capacity.",
            source="fallback",
            created_at=now,
        )
    )

    summary = service.dashboard_summary(project_id)

    assert summary.degraded_profiles == 1
    assert summary.open_circuits == 1
    assert summary.rate_limited_profiles == 1
    assert summary.latest_deadline_risk == DeadlineRiskLevel.MISSED
    assert summary.recommended_concurrency == 4
    assert summary.severity == "error"
    assert "open circuit" in summary.recommendation


def test_phase21_export_contains_ui_preferences_and_dashboard_summary(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase21.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    service.save_view_preferences(
        replace(
            service.default_view_preferences(project_id),
            auto_refresh=True,
            refresh_interval_seconds=15,
            table_density="compact",
        )
    )

    json_path, _csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
        project_name="Phase 21",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["view_preferences"]["auto_refresh"] is True
    assert payload["view_preferences"]["table_density"] == "compact"
    assert "recommendation" in payload["dashboard_summary"]
    assert "api_key" not in json_path.read_text(encoding="utf-8")


def test_phase21_dialog_exposes_operations_center_controls(qt_app, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QTabWidget

    from app.gui.dialogs.generation_orchestration_dialog import (
        GenerationOrchestrationDialog,
    )

    database = Database(tmp_path / "phase21.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    service.save_view_preferences(
        replace(
            service.default_view_preferences(project_id),
            auto_refresh=False,
            table_density="compact",
            status_filter="attention",
        )
    )
    dialog = GenerationOrchestrationDialog(
        service,
        project_id=project_id,
        project_name="Phase 21",
        export_dir=tmp_path / "exports",
    )

    assert dialog.tabs.tabPosition() == QTabWidget.West
    assert dialog.tabs.count() >= 10
    assert dialog.overview_table.columnCount() == 6
    assert dialog.forecast_table.columnCount() == 12
    assert dialog.preset.count() == 4
    assert dialog.density.currentData() == "compact"
    assert dialog.status_filter.currentData() == "attention"
    assert dialog.health_card.value_label.text() == "0"
