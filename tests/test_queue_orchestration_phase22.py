from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.generation_orchestration import (
    DeadlineRiskLevel,
    GenerationOrchestrationSavedView,
    GenerationQueueForecast,
    ProviderCircuitSnapshot,
    ProviderCircuitStatus,
    ProviderThrottleSnapshot,
)
from app.release import SCHEMA_VERSION
from app.repositories.generation_orchestration_repository import (
    GenerationOrchestrationRepository,
)
from app.services.api_profile_service import ApiProfileService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.secure_credentials import SecureCredentialStore


def _project(database: Database, name: str = "Phase 22") -> int:
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
        now_factory=lambda: datetime(2026, 8, 1, 8, 30, tzinfo=timezone.utc),
    )


def _risk_state(
    service: GenerationOrchestrationService,
    project_id: int,
) -> None:
    repository = service.repository
    now = "2026-08-01T08:25:00+00:00"
    repository.save_circuit(
        ProviderCircuitSnapshot(
            state_key=repository.state_key(project_id, "elevenlabs", "primary"),
            project_id=project_id,
            provider="elevenlabs",
            profile_id="primary",
            profile_name="Primary",
            status=ProviderCircuitStatus.OPEN,
            consecutive_failures=3,
            retry_after="2026-08-01T08:35:00+00:00",
            updated_at=now,
        )
    )
    repository.save_throttle_state(
        ProviderThrottleSnapshot(
            throttle_key=repository.throttle_key(
                project_id,
                "elevenlabs",
                "backup",
            ),
            project_id=project_id,
            provider="elevenlabs",
            profile_id="backup",
            profile_name="Backup",
            current_concurrency=1,
            recent_rate_limits=2,
            cooldown_until="2026-08-01T08:40:00+00:00",
            last_rate_limit_at=now,
            updated_at=now,
        )
    )
    repository.add_queue_forecast(
        GenerationQueueForecast(
            forecast_id="phase22-risk",
            project_id=project_id,
            provider="elevenlabs",
            job_count=20,
            total_characters=20000,
            current_concurrency=1,
            recommended_concurrency=5,
            characters_per_minute=1000,
            estimated_duration_seconds=1200,
            estimated_finish_at="2026-08-01T08:50:00+00:00",
            deadline_at="2026-08-01T08:40:00+00:00",
            slack_seconds=-600,
            risk_score=1.0,
            risk_level=DeadlineRiskLevel.MISSED,
            recommendation="Increase concurrency to five.",
            source="historical",
            created_at=now,
        )
    )


def test_phase22_migration_adds_workflow_ui_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase22.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 22")
        connection.execute("DROP TABLE generation_orchestration_operator_actions")
        connection.execute("DROP TABLE generation_orchestration_saved_views")
        connection.commit()

    database.initialize()

    assert database.applied_schema_versions() == tuple(range(1, SCHEMA_VERSION + 1))
    backup = database.path.with_suffix(database.path.suffix + ".pre-v22.bak")
    assert backup.exists()
    assert Database(backup).quick_check() == "ok"


def test_phase22_saved_views_are_reusable_and_have_one_default(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase22.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)

    first = service.save_saved_view(
        GenerationOrchestrationSavedView(
            view_id="",
            project_id=project_id,
            name="Attention only",
            selected_tab=1,
            table_density="compact",
            search_text="rate limit",
            status_filter="attention",
            is_default=True,
        )
    )
    second = service.save_saved_view(
        GenerationOrchestrationSavedView(
            view_id="",
            project_id=project_id,
            name="Healthy accounts",
            selected_tab=5,
            status_filter="healthy",
        )
    )
    service.set_default_saved_view(second.view_id)
    updated_first = service.save_saved_view(
        replace(first, view_id="", search_text="circuit")
    )

    views = service.list_saved_views(project_id)
    preferences = service.apply_saved_view(updated_first.view_id)

    assert updated_first.view_id == first.view_id
    assert len(views) == 2
    assert sum(1 for item in views if item.is_default) == 1
    assert next(item for item in views if item.is_default).view_id == second.view_id
    assert preferences.search_text == "circuit"
    assert preferences.status_filter == "attention"


def test_phase22_attention_queue_combines_actionable_risks(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase22.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    _risk_state(service, project_id)

    items = service.attention_items(project_id)

    assert [item.category for item in items] == ["circuit", "deadline", "rate_limit"]
    assert items[0].severity == "critical"
    assert {item.action_type for item in items} == {
        "reset_circuit",
        "clear_throttle",
        "apply_recommended_concurrency",
    }


def test_phase22_safe_operator_actions_are_applied_and_audited(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase22.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    _risk_state(service, project_id)
    safe_ids = [
        item.attention_id
        for item in service.attention_items(project_id)
        if item.action_type in {"reset_circuit", "clear_throttle"}
    ]

    action = service.execute_attention_actions(
        project_id,
        safe_ids,
        safe_only=True,
    )

    circuit = service.repository.get_circuit(
        project_id=project_id,
        provider="elevenlabs",
        profile_id="primary",
    )
    throttle = service.repository.get_throttle_state(
        project_id=project_id,
        provider="elevenlabs",
        profile_id="backup",
    )
    history = service.repository.list_operator_actions(project_id=project_id)
    assert action.target_count == 2
    assert circuit is not None and circuit.status == ProviderCircuitStatus.CLOSED
    assert throttle is not None and throttle.recent_rate_limits == 0
    assert throttle.cooldown_until is None
    assert history[0].action_id == action.action_id


def test_phase22_deadline_action_applies_recommended_concurrency(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase22.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    _risk_state(service, project_id)
    deadline_id = next(
        item.attention_id
        for item in service.attention_items(project_id)
        if item.category == "deadline"
    )

    action = service.execute_attention_actions(project_id, [deadline_id])
    scheduling = service.get_scheduling_policy(project_id)

    assert action.target_count == 1
    assert scheduling.enabled
    assert scheduling.initial_concurrency == 5
    assert scheduling.maximum_concurrency >= 5


def test_phase22_export_contains_saved_views_attention_and_audit(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase22.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    _risk_state(service, project_id)
    service.save_saved_view(
        GenerationOrchestrationSavedView(
            view_id="",
            project_id=project_id,
            name="Risk view",
            selected_tab=1,
            status_filter="attention",
        )
    )
    service.execute_attention_actions(
        project_id,
        [
            item.attention_id
            for item in service.attention_items(project_id)
            if item.action_type == "clear_throttle"
        ],
    )

    json_path, _csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
        project_name="Phase 22",
    )
    text = json_path.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert payload["saved_views"][0]["name"] == "Risk view"
    assert payload["attention_items"]
    assert payload["operator_actions"][0]["target_count"] == 1
    assert "api_key" not in text


def test_phase22_dialog_exposes_saved_views_attention_and_shortcuts(
    qt_app,
    tmp_path: Path,
) -> None:
    from app.gui.dialogs.generation_orchestration_dialog import (
        GenerationOrchestrationDialog,
    )

    database = Database(tmp_path / "phase22.db")
    database.initialize()
    project_id = _project(database)
    service = _service(tmp_path, database)
    _risk_state(service, project_id)
    service.save_saved_view(
        GenerationOrchestrationSavedView(
            view_id="",
            project_id=project_id,
            name="Default attention",
            selected_tab=1,
            table_density="compact",
            status_filter="attention",
            is_default=True,
        )
    )

    dialog = GenerationOrchestrationDialog(
        service,
        project_id=project_id,
        project_name="Phase 22",
        export_dir=tmp_path / "exports",
    )

    assert dialog.tabs.count() == 11
    assert dialog.tabs.indexOf(dialog.attention_page) == 1
    assert dialog.saved_view_combo.count() == 2
    assert dialog.saved_view_combo.currentData() is not None
    assert dialog.attention_table.rowCount() == 3
    assert dialog.operator_action_table.columnCount() == 5
    assert dialog.search_shortcut.key().toString() == "Ctrl+F"
    assert dialog.run_safe_attention.isEnabled()
