from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.exceptions import ProviderError
from app.models.api_profile import ApiProfileFailoverMode, ApiProfileStatus, FailoverSettings
from app.models.domain import AppSettings, TTSJob
from app.models.generation_orchestration import RoutingMode, SchedulingMode
from app.repositories.generation_orchestration_repository import GenerationOrchestrationRepository
from app.services.api_profile_service import ApiProfileService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.secure_credentials import SecureCredentialStore


def _project(database: Database, name: str = "Phase 19") -> int:
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


def _services(tmp_path: Path, database: Database, now: datetime):
    profiles = ApiProfileService(
        tmp_path / "api-profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    service = GenerationOrchestrationService(
        GenerationOrchestrationRepository(database),
        profiles,
        now_factory=lambda: now,
    )
    return profiles, service


def _profile(
    profiles: ApiProfileService,
    name: str,
    key: str,
    *,
    active: bool,
    priority: int,
    weight: int = 1,
):
    profile = profiles.create_profile(
        name,
        provider="elevenlabs",
        api_key=key,
        active=active,
        priority=priority,
    )
    profile.status = ApiProfileStatus.READY
    profile.remaining_characters = 100_000
    profile.character_limit = 100_000
    profile.metadata["routing_weight"] = str(weight)
    return profiles.update_profile(profile)


def _settings(active_profile_id: str) -> AppSettings:
    return AppSettings(
        provider="elevenlabs",
        active_api_profile_id=active_profile_id,
        api_profile_failover="auto",
        api_profile_failover_max_switches=8,
        skip_existing=False,
        delay_seconds=0,
    )


def _configured_plan(tmp_path: Path, database: Database, now: datetime, *, mode: SchedulingMode):
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Primary",
        "primary-key",
        active=True,
        priority=10,
        weight=1,
    )
    _profile(
        profiles,
        "Backup",
        "backup-key",
        active=False,
        priority=20,
        weight=1,
    )
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(
            mode=ApiProfileFailoverMode.AUTO,
            max_switches_per_run=8,
        ),
    )
    service.save_routing_policy(
        replace(
            service.default_routing_policy(project_id),
            enabled=True,
            mode=RoutingMode.WEIGHTED,
            max_profile_share_percent=60,
        )
    )
    service.save_scheduling_policy(
        replace(
            service.default_scheduling_policy(project_id),
            enabled=True,
            mode=mode,
            minimum_concurrency=1,
            initial_concurrency=3,
            maximum_concurrency=3,
            per_profile_concurrency=2,
            success_window=2,
            error_window=3,
            increase_step=1,
            decrease_factor=0.5,
            rate_limit_cooldown_seconds=0,
        )
    )
    jobs = [
        TTSJob(row_number=index, text=f"Hej {index}", filename=f"{index}.mp3")
        for index in range(1, 7)
    ]
    plan = service.build_plan(
        project_id=project_id,
        settings=_settings(primary.profile_id),
        jobs=jobs,
    )
    return project_id, service, jobs, plan


def test_phase19_migration_adds_scheduler_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase19.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 19")
        connection.execute("DROP TABLE generation_scheduler_events")
        connection.execute("DROP TABLE generation_provider_throttle_states")
        connection.execute("DROP TABLE generation_scheduling_policies")
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
    assert versions == tuple(range(1, 20))
    assert {
        "generation_scheduling_policies",
        "generation_provider_throttle_states",
        "generation_scheduler_events",
    }.issubset(tables)
    backup = database.path.with_suffix(database.path.suffix + ".pre-v19.bak")
    assert backup.exists()
    assert Database(backup).quick_check() == "ok"


def test_phase19_policy_normalizes_and_enables_concurrent_plan(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase19.db")
    database.initialize()
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Primary",
        "primary-key",
        active=True,
        priority=10,
    )
    _profile(
        profiles,
        "Backup",
        "backup-key",
        active=False,
        priority=20,
    )
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(
            mode=ApiProfileFailoverMode.AUTO,
            max_switches_per_run=8,
        ),
    )

    saved = service.save_scheduling_policy(
        replace(
            service.default_scheduling_policy(project_id),
            enabled=True,
            mode=SchedulingMode.ADAPTIVE,
            minimum_concurrency=2,
            initial_concurrency=12,
            maximum_concurrency=4,
            per_profile_concurrency=9,
            success_window=0,
            error_window=0,
            increase_step=20,
            decrease_factor=0.01,
            rate_limit_cooldown_seconds=100_000,
        )
    )
    jobs = [
        TTSJob(row_number=index, text="Hej", filename=f"{index}.mp3")
        for index in range(1, 5)
    ]
    plan = service.build_plan(
        project_id=project_id,
        settings=_settings(primary.profile_id),
        jobs=jobs,
    )

    assert saved.initial_concurrency == 4
    assert saved.per_profile_concurrency == 4
    assert saved.success_window == 1
    assert saved.error_window == 1
    assert saved.increase_step == 16
    assert saved.decrease_factor == 0.1
    assert saved.rate_limit_cooldown_seconds == 86400
    assert plan.scheduling_enabled
    assert plan.scheduling_mode == SchedulingMode.ADAPTIVE
    assert plan.minimum_concurrency == 2
    assert plan.initial_concurrency == 4
    assert plan.maximum_concurrency == 4


def test_phase19_scheduler_events_persist_throttle_and_export(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase19.db")
    database.initialize()
    project_id = _project(database)
    _profiles, service = _services(tmp_path, database, now)
    service.save_scheduling_policy(
        replace(
            service.default_scheduling_policy(project_id),
            enabled=True,
            rate_limit_cooldown_seconds=30,
        )
    )

    service.record_scheduler_event(
        {
            "project_id": project_id,
            "provider": "elevenlabs",
            "profile_id": "profile-1",
            "profile_name": "Profile 1",
            "event_type": "scheduler_started",
            "from_concurrency": 4,
            "to_concurrency": 4,
            "metadata": {"api_key": "must-not-leak"},
        }
    )
    assert service.repository.list_throttle_states(project_id=project_id) == []

    service.record_scheduler_event(
        {
            "project_id": project_id,
            "provider": "elevenlabs",
            "profile_id": "profile-1",
            "profile_name": "Profile 1",
            "event_type": "rate_limited",
            "from_concurrency": 4,
            "to_concurrency": 1,
            "pending_jobs": 6,
            "active_jobs": 3,
            "reason": "HTTP 429",
            "metadata": {"api_key": "must-not-leak"},
        }
    )
    service.record_scheduler_event(
        {
            "project_id": project_id,
            "provider": "elevenlabs",
            "profile_id": "profile-1",
            "profile_name": "Profile 1",
            "event_type": "concurrency_increased",
            "from_concurrency": 1,
            "to_concurrency": 2,
            "reason": "success window completed",
        }
    )

    state = service.repository.list_throttle_states(project_id=project_id)[0]
    assert state.current_concurrency == 2
    assert state.recent_rate_limits == 0
    assert state.cooldown_until is None
    assert len(service.repository.list_scheduler_events(project_id=project_id)) == 3

    json_path, csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
        project_name="Phase 19",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["scheduling_policy"]["enabled"] is True
    assert len(payload["scheduler_events"]) == 3
    assert "must-not-leak" not in serialized
    assert "scheduler_event" in csv_path.read_text(encoding="utf-8-sig")


def test_phase19_worker_runs_jobs_concurrently(qt_app, tmp_path: Path, monkeypatch) -> None:
    from app.gui.worker import GenerationWorker

    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase19.db")
    database.initialize()
    _project_id, _service, jobs, plan = _configured_plan(
        tmp_path,
        database,
        now,
        mode=SchedulingMode.STATIC,
    )
    lock = threading.Lock()
    active = 0
    peak = 0

    class FakeProvider:
        def __init__(self, settings: AppSettings) -> None:
            self.settings = settings

        def synthesize(self, _text: str, _settings: AppSettings) -> bytes:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.04)
                return b"audio"
            finally:
                with lock:
                    active -= 1

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.gui.worker.create_provider",
        lambda settings: FakeProvider(settings),
    )
    worker = GenerationWorker(
        jobs,
        plan.candidates[0].settings,
        tmp_path / "output",
        tmp_path / "legacy.db",
        "phase19-static",
        orchestration_plan=plan,
    )
    summaries: list[dict] = []
    worker.finished.connect(summaries.append)

    worker.run()

    assert summaries[0]["completed"] == len(jobs)
    assert summaries[0]["scheduler"]["peak_concurrency"] >= 2
    assert peak >= 2
    assert len(list((tmp_path / "output").glob("*.mp3"))) == len(jobs)


def test_phase19_rate_limit_triggers_backpressure_and_same_job_failover(
    qt_app,
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.gui.worker import GenerationWorker

    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase19.db")
    database.initialize()
    project_id, service, jobs, plan = _configured_plan(
        tmp_path,
        database,
        now,
        mode=SchedulingMode.ADAPTIVE,
    )
    plan = replace(plan, success_window=100)
    failed_once = False

    class FakeProvider:
        def __init__(self, settings: AppSettings) -> None:
            self.settings = settings

        def synthesize(self, _text: str, settings: AppSettings) -> bytes:
            nonlocal failed_once
            time.sleep(0.02)
            if settings.api_key == "primary-key" and not failed_once:
                failed_once = True
                raise ProviderError(
                    "Rate limit reached",
                    retryable=True,
                    http_status=429,
                    provider_code="rate_limit",
                )
            return b"audio"

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.gui.worker.create_provider",
        lambda settings: FakeProvider(settings),
    )
    worker = GenerationWorker(
        jobs,
        plan.candidates[0].settings,
        tmp_path / "output",
        tmp_path / "legacy.db",
        "phase19-adaptive",
        orchestration_plan=plan,
    )
    summaries: list[dict] = []
    scheduler_events: list[dict] = []
    worker.finished.connect(summaries.append)
    worker.failover.connect(service.record_worker_event)
    worker.scheduler.connect(scheduler_events.append)
    worker.scheduler.connect(service.record_scheduler_event)

    worker.run()

    assert summaries[0]["completed"] == len(jobs)
    assert summaries[0]["failover_switches"] == 1
    assert summaries[0]["scheduler"]["backpressure_events"] == 1
    assert any(item["event_type"] == "rate_limited" for item in scheduler_events)
    assert any(item["event_type"] == "backpressure" for item in scheduler_events)
    assert any(
        event.outcome == "switched"
        for event in service.repository.list_events(project_id=project_id)
    )
    state = service.repository.list_throttle_states(project_id=project_id)[0]
    assert state.recent_rate_limits >= 1
    assert state.current_concurrency == 1


def test_phase19_dialog_exposes_scheduler_policy_and_telemetry(
    qt_app,
    tmp_path: Path,
) -> None:
    from app.gui.dialogs.generation_orchestration_dialog import (
        GenerationOrchestrationDialog,
    )

    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase19.db")
    database.initialize()
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Primary",
        "primary-key",
        active=True,
        priority=10,
    )
    service.save_scheduling_policy(
        replace(
            service.default_scheduling_policy(project_id),
            enabled=True,
            mode=SchedulingMode.ADAPTIVE,
            initial_concurrency=3,
            maximum_concurrency=5,
        )
    )
    service.record_scheduler_event(
        {
            "project_id": project_id,
            "provider": "elevenlabs",
            "profile_id": primary.profile_id,
            "profile_name": primary.display_name,
            "event_type": "rate_limited",
            "from_concurrency": 3,
            "to_concurrency": 1,
            "reason": "HTTP 429",
        }
    )
    dialog = GenerationOrchestrationDialog(
        service,
        project_id=project_id,
        project_name="Phase 19",
        settings_provider=lambda: _settings(primary.profile_id),
        export_dir=tmp_path / "exports",
    )

    assert dialog.windowTitle() == "Generation Orchestration & Adaptive Routing"
    assert dialog.scheduling_enabled.isChecked()
    assert dialog.scheduling_mode.currentData() == SchedulingMode.ADAPTIVE.value
    assert dialog.initial_concurrency.value() == 3
    assert dialog.maximum_concurrency.value() == 5
    assert dialog.throttle_table.rowCount() == 1
    assert dialog.scheduler_event_table.rowCount() == 1
    assert "concurrency=" in dialog.plan_label.text()
