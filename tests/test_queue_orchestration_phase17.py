from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.connection import Database
from app.exceptions import ProviderError
from app.models.api_profile import ApiProfileStatus, FailoverSettings, ApiProfileFailoverMode
from app.models.domain import AppSettings, TTSJob
from app.models.generation_orchestration import ProviderCircuitStatus
from app.repositories.generation_orchestration_repository import GenerationOrchestrationRepository
from app.repositories.product_event_repository import ProductEventRepository
from app.services.activity_timeline_service import ActivityTimelineService
from app.services.api_profile_service import ApiProfileService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.notification_center_service import NotificationCenterService
from app.services.secure_credentials import SecureCredentialStore


def _project(database: Database, name: str = "Phase 17") -> int:
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
    events = ProductEventRepository(database)
    service = GenerationOrchestrationService(
        GenerationOrchestrationRepository(database),
        profiles,
        NotificationCenterService(events),
        ActivityTimelineService(events),
        now_factory=lambda: now,
    )
    return profiles, events, service


def _profile(profiles: ApiProfileService, name: str, key: str, *, active: bool, priority: int):
    profile = profiles.create_profile(
        name,
        provider="elevenlabs",
        api_key=key,
        active=active,
        priority=priority,
    )
    profile.status = ApiProfileStatus.READY
    profile.remaining_characters = 100_000
    profile.character_limit = 200_000
    return profiles.update_profile(profile)


def test_phase17_migration_adds_orchestration_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase17.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 17")
        connection.execute("DROP TABLE generation_failover_events")
        connection.execute("DROP TABLE generation_provider_circuit_states")
        connection.execute("DROP TABLE generation_orchestration_policies")
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
        "generation_orchestration_policies",
        "generation_provider_circuit_states",
        "generation_failover_events",
    }.issubset(tables)
    backup = database.path.with_suffix(database.path.suffix + ".pre-v17.bak")
    assert backup.exists()
    assert Database(backup).quick_check() == "ok"


def test_phase17_builds_active_then_backup_execution_plan(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase17.db")
    database.initialize()
    project_id = _project(database)
    profiles, _events, service = _services(tmp_path, database, now)
    primary = _profile(profiles, "Primary", "primary-key", active=True, priority=10)
    backup = _profile(profiles, "Backup", "backup-key", active=False, priority=20)
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(
            mode=ApiProfileFailoverMode.AUTO,
            max_switches_per_run=3,
        ),
    )
    service.save_policy(
        replace(
            service.default_policy(project_id),
            max_switches_per_run=2,
            failure_threshold=2,
        )
    )

    plan = service.build_plan(
        project_id=project_id,
        settings=AppSettings(
            provider="elevenlabs",
            api_key="temporary",
            active_api_profile_id=primary.profile_id,
            api_profile_failover="auto",
            api_profile_failover_max_switches=4,
        ),
    )

    assert plan.enabled
    assert plan.max_switches == 2
    assert [candidate.profile_id for candidate in plan.candidates] == [
        primary.profile_id,
        backup.profile_id,
    ]
    assert plan.candidates[0].settings.api_key == "primary-key"
    assert plan.candidates[1].settings.api_key == "backup-key"


def test_phase17_circuit_opens_excludes_profile_then_half_opens(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase17.db")
    database.initialize()
    project_id = _project(database)
    profiles, _events, service = _services(tmp_path, database, now)
    primary = _profile(profiles, "Primary", "primary-key", active=True, priority=10)
    backup = _profile(profiles, "Backup", "backup-key", active=False, priority=20)
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=3),
    )
    service.save_policy(
        replace(
            service.default_policy(project_id),
            failure_threshold=2,
            circuit_cooldown_seconds=60,
        )
    )
    base_payload = {
        "project_id": project_id,
        "job_row_number": 1,
        "filename": "one.mp3",
        "provider": "elevenlabs",
        "from_profile_id": backup.profile_id,
        "from_profile_name": backup.display_name,
        "failure_category": "quota",
        "error_code": "quota_exhausted",
        "outcome": "exhausted",
        "switch_number": 0,
    }
    service.record_worker_event({**base_payload, "consecutive_failures": 1})
    service.record_worker_event({**base_payload, "consecutive_failures": 2, "circuit_opened": True})

    settings = AppSettings(
        provider="elevenlabs",
        active_api_profile_id=primary.profile_id,
        api_profile_failover="auto",
        api_profile_failover_max_switches=3,
    )
    blocked = service.build_plan(project_id=project_id, settings=settings)
    assert [candidate.profile_id for candidate in blocked.candidates] == [primary.profile_id]
    assert {item["profile"] for item in blocked.excluded} == {backup.display_name}
    circuit = service.repository.get_circuit(
        project_id=project_id,
        provider="elevenlabs",
        profile_id=backup.profile_id,
    )
    assert circuit is not None and circuit.status == ProviderCircuitStatus.OPEN

    future_service = GenerationOrchestrationService(
        service.repository,
        profiles,
        now_factory=lambda: now + timedelta(seconds=61),
    )
    half_open = future_service.build_plan(project_id=project_id, settings=settings)
    assert half_open.candidates[1].profile_id == backup.profile_id
    assert half_open.candidates[1].circuit_status == ProviderCircuitStatus.HALF_OPEN


def test_phase17_records_notifications_activity_and_exports(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase17.db")
    database.initialize()
    project_id = _project(database)
    profiles, events, service = _services(tmp_path, database, now)
    profile = _profile(profiles, "Primary", "primary-key", active=True, priority=10)
    service.save_policy(replace(service.default_policy(project_id), failure_threshold=1))

    recorded = service.record_worker_event(
        {
            "project_id": project_id,
            "job_row_number": 7,
            "filename": "seven.mp3",
            "provider": "elevenlabs",
            "from_profile_id": profile.profile_id,
            "from_profile_name": profile.display_name,
            "to_profile_name": "Backup",
            "failure_category": "network",
            "error_code": "timeout",
            "outcome": "switched",
            "switch_number": 1,
            "consecutive_failures": 1,
            "circuit_opened": True,
        }
    )

    assert recorded.circuit_opened
    assert events.list_notifications()[0].title == "Provider account circuit opened"
    assert events.list_activity(project_id=project_id)[0].category == "generation_orchestration"
    json_path, csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
        project_name="Phase 17",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["events"][0]["outcome"] == "switched"
    assert "seven.mp3" in csv_path.read_text(encoding="utf-8-sig")


def test_phase17_worker_retries_same_job_on_backup(qt_app, tmp_path: Path, monkeypatch) -> None:
    from app.gui.worker import GenerationWorker

    now = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase17.db")
    database.initialize()
    project_id = _project(database)
    profiles, _events, service = _services(tmp_path, database, now)
    primary = _profile(profiles, "Primary", "primary-key", active=True, priority=10)
    _profile(profiles, "Backup", "backup-key", active=False, priority=20)
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=2),
    )
    plan = service.build_plan(
        project_id=project_id,
        settings=AppSettings(
            provider="elevenlabs",
            active_api_profile_id=primary.profile_id,
            api_profile_failover="auto",
            api_profile_failover_max_switches=2,
            skip_existing=False,
        ),
    )

    class FakeProvider:
        def __init__(self, settings: AppSettings) -> None:
            self.settings = settings

        def synthesize(self, _text: str, settings: AppSettings) -> bytes:
            if settings.api_key == "primary-key":
                raise ProviderError(
                    "Quota exhausted",
                    provider_code="quota_exhausted",
                    retryable=False,
                )
            return b"audio"

        def close(self) -> None:
            return None

    monkeypatch.setattr("app.gui.worker.create_provider", lambda settings: FakeProvider(settings))
    job = TTSJob(row_number=1, text="Hej", filename="one.mp3")
    worker = GenerationWorker(
        [job],
        plan.candidates[0].settings,
        tmp_path / "output",
        tmp_path / "legacy.db",
        "phase17",
        orchestration_plan=plan,
    )
    failovers: list[dict] = []
    summaries: list[dict] = []
    worker.failover.connect(failovers.append)
    worker.finished.connect(summaries.append)

    worker.run()

    assert summaries[0]["completed"] == 1
    assert summaries[0]["failed"] == 0
    assert summaries[0]["failover_switches"] == 1
    assert (tmp_path / "output" / "one.mp3").exists()
    assert [item["outcome"] for item in failovers] == ["switched", "success"]


def test_phase17_open_primary_routes_directly_to_backup_or_blocks(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase17.db")
    database.initialize()
    project_id = _project(database)
    profiles, _events, service = _services(tmp_path, database, now)
    primary = _profile(profiles, "Primary", "primary-key", active=True, priority=10)
    backup = _profile(profiles, "Backup", "backup-key", active=False, priority=20)
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=2),
    )
    service.save_policy(replace(service.default_policy(project_id), failure_threshold=1))
    settings = AppSettings(
        provider="elevenlabs",
        active_api_profile_id=primary.profile_id,
        api_profile_failover="auto",
        api_profile_failover_max_switches=2,
    )

    def open_profile(profile_id: str, name: str) -> None:
        service.record_worker_event(
            {
                "project_id": project_id,
                "job_row_number": 1,
                "filename": "one.mp3",
                "provider": "elevenlabs",
                "from_profile_id": profile_id,
                "from_profile_name": name,
                "failure_category": "network",
                "error_code": "timeout",
                "outcome": "exhausted",
                "consecutive_failures": 1,
                "circuit_opened": True,
            }
        )

    open_profile(primary.profile_id, primary.display_name)
    routed = service.build_plan(project_id=project_id, settings=settings)
    assert [candidate.profile_id for candidate in routed.candidates] == [backup.profile_id]
    assert routed.blocked_reason is None

    open_profile(backup.profile_id, backup.display_name)
    blocked = service.build_plan(project_id=project_id, settings=settings)
    assert blocked.candidates == ()
    assert blocked.blocked_reason == "All configured provider accounts have open circuits or are unavailable."
