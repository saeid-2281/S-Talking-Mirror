from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.database.connection import Database
from app.models.api_profile import ApiProfileFailoverMode, ApiProfileStatus, FailoverSettings
from app.models.domain import AppSettings, TTSJob
from app.models.generation_orchestration import RoutingMode
from app.repositories.generation_orchestration_repository import GenerationOrchestrationRepository
from app.services.api_profile_service import ApiProfileService
from app.services.generation_orchestration_service import GenerationOrchestrationService
from app.services.secure_credentials import SecureCredentialStore


def _project(database: Database, name: str = "Phase 18") -> int:
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
    remaining: int,
    limit: int = 100_000,
    weight: int | None = None,
):
    profile = profiles.create_profile(
        name,
        provider="elevenlabs",
        api_key=key,
        active=active,
        priority=priority,
    )
    profile.status = ApiProfileStatus.READY
    profile.remaining_characters = remaining
    profile.character_limit = limit
    if weight is not None:
        profile.metadata["routing_weight"] = str(weight)
    return profiles.update_profile(profile)


def _settings(active_profile_id: str) -> AppSettings:
    return AppSettings(
        provider="elevenlabs",
        active_api_profile_id=active_profile_id,
        api_profile_failover="auto",
        api_profile_failover_max_switches=4,
        skip_existing=False,
    )


def test_phase18_migration_adds_adaptive_routing_schema_and_backup(tmp_path: Path) -> None:
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version = 18")
        connection.execute("DROP TABLE generation_routing_decisions")
        connection.execute("DROP TABLE generation_provider_routing_metrics")
        connection.execute("DROP TABLE generation_adaptive_routing_policies")
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
        "generation_adaptive_routing_policies",
        "generation_provider_routing_metrics",
        "generation_routing_decisions",
    }.issubset(tables)
    backup = database.path.with_suffix(database.path.suffix + ".pre-v18.bak")
    assert backup.exists()
    assert Database(backup).quick_check() == "ok"


def test_phase18_policy_normalizes_weights_and_persists(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    project_id = _project(database)
    _profiles, service = _services(tmp_path, database, now)

    saved = service.save_routing_policy(
        replace(
            service.default_routing_policy(project_id),
            enabled=True,
            mode=RoutingMode.ADAPTIVE,
            health_weight=4,
            capacity_weight=3,
            latency_weight=2,
            priority_weight=1,
            minimum_quota_reserve=5000,
            max_profile_share_percent=65,
            sample_window=80,
        )
    )
    loaded = service.get_routing_policy(project_id)

    assert saved == loaded
    assert round(
        loaded.health_weight
        + loaded.capacity_weight
        + loaded.latency_weight
        + loaded.priority_weight,
        8,
    ) == 1.0
    assert loaded.mode == RoutingMode.ADAPTIVE
    assert loaded.minimum_quota_reserve == 5000
    assert loaded.max_profile_share_percent == 65


def test_phase18_adaptive_plan_scores_capacity_and_caps_distribution(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Primary",
        "primary-key",
        active=True,
        priority=10,
        remaining=10_000,
    )
    backup = _profile(
        profiles,
        "Capacity",
        "capacity-key",
        active=False,
        priority=20,
        remaining=90_000,
    )
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=4),
    )
    service.save_routing_policy(
        replace(
            service.default_routing_policy(project_id),
            enabled=True,
            mode=RoutingMode.ADAPTIVE,
            max_profile_share_percent=60,
        )
    )
    jobs = [TTSJob(row_number=index, text="hej" * index, filename=f"{index}.mp3") for index in range(1, 11)]

    plan = service.build_plan(
        project_id=project_id,
        settings=_settings(primary.profile_id),
        jobs=jobs,
    )

    assert plan.routing_enabled
    assert plan.routing_mode == RoutingMode.ADAPTIVE
    assert plan.candidates[0].profile_id == backup.profile_id
    assert plan.candidates[0].routing_score > plan.candidates[1].routing_score
    assert len(plan.routing_sequence) == len(jobs)
    assert sum(int(item["jobs"]) for item in plan.predicted_distribution) == len(jobs)
    assert max(float(item["share_percent"]) for item in plan.predicted_distribution) <= 60.0


def test_phase18_quota_reserve_excludes_low_capacity_profile(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Low quota",
        "low-key",
        active=True,
        priority=10,
        remaining=999,
    )
    backup = _profile(
        profiles,
        "Healthy quota",
        "healthy-key",
        active=False,
        priority=20,
        remaining=80_000,
    )
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=4),
    )
    service.save_routing_policy(
        replace(
            service.default_routing_policy(project_id),
            enabled=True,
            mode=RoutingMode.ADAPTIVE,
            minimum_quota_reserve=1000,
        )
    )

    plan = service.build_plan(project_id=project_id, settings=_settings(primary.profile_id))

    assert [candidate.profile_id for candidate in plan.candidates] == [backup.profile_id]
    assert {item["profile"]: item["reason"] for item in plan.excluded}["Low quota"] == "quota reserve"


def test_phase18_records_decisions_metrics_and_exports_without_credentials(tmp_path: Path) -> None:
    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    project_id = _project(database)
    _profiles, service = _services(tmp_path, database, now)
    base = {
        "project_id": project_id,
        "job_row_number": 3,
        "filename": "three.mp3",
        "provider": "elevenlabs",
        "from_profile_id": "profile-3",
        "from_profile_name": "Profile 3",
        "failure_category": "none",
        "error_code": "none",
        "switch_number": 0,
        "consecutive_failures": 0,
        "circuit_opened": False,
        "metadata": {
            "routing_mode": "adaptive",
            "routing_score": 82.5,
            "routing_weight": 83,
            "characters": 120,
            "duration_seconds": 1.5,
            "reason": "adaptive queue assignment",
        },
    }
    service.record_worker_event({**base, "outcome": "routed"})
    service.record_worker_event({**base, "outcome": "success"})

    decision = service.repository.list_decisions(project_id=project_id)[0]
    metric = service.repository.list_routing_metrics(project_id=project_id)[0]
    assert decision.routing_mode == RoutingMode.ADAPTIVE
    assert decision.estimated_characters == 120
    assert metric.attempts == 1
    assert metric.successes == 1
    assert metric.total_characters == 120
    assert metric.ewma_latency_seconds == 1.5

    json_path, csv_path = service.export_report(
        tmp_path / "exports",
        project_id=project_id,
        project_name="Phase 18",
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["routing_decisions"][0]["profile_name"] == "Profile 3"
    assert payload["routing_metrics"][0]["attempts"] == 1
    assert "api_key" not in serialized
    assert "Profile 3" in csv_path.read_text(encoding="utf-8-sig")


def test_phase18_worker_distributes_jobs_and_updates_health(qt_app, tmp_path: Path, monkeypatch) -> None:
    from app.gui.worker import GenerationWorker

    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Primary",
        "primary-key",
        active=True,
        priority=10,
        remaining=100_000,
        weight=1,
    )
    _profile(
        profiles,
        "Backup",
        "backup-key",
        active=False,
        priority=20,
        remaining=100_000,
        weight=3,
    )
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=4),
    )
    service.save_routing_policy(
        replace(
            service.default_routing_policy(project_id),
            enabled=True,
            mode=RoutingMode.WEIGHTED,
            max_profile_share_percent=75,
        )
    )
    jobs = [
        TTSJob(row_number=index, text=f"Hej {index}", filename=f"{index}.mp3")
        for index in range(1, 5)
    ]
    plan = service.build_plan(
        project_id=project_id,
        settings=_settings(primary.profile_id),
        jobs=jobs,
    )
    used_keys: list[str] = []

    class FakeProvider:
        def __init__(self, settings: AppSettings) -> None:
            self.settings = settings

        def synthesize(self, _text: str, settings: AppSettings) -> bytes:
            used_keys.append(settings.api_key)
            return b"audio"

        def close(self) -> None:
            return None

    monkeypatch.setattr("app.gui.worker.create_provider", lambda settings: FakeProvider(settings))
    worker = GenerationWorker(
        jobs,
        plan.candidates[0].settings,
        tmp_path / "output",
        tmp_path / "legacy.db",
        "phase18",
        orchestration_plan=plan,
    )
    summaries: list[dict] = []
    worker.failover.connect(service.record_worker_event)
    worker.finished.connect(summaries.append)

    worker.run()

    assert summaries[0]["completed"] == 4
    assert used_keys.count("backup-key") == 3
    assert used_keys.count("primary-key") == 1
    assert len(service.repository.list_decisions(project_id=project_id)) == 4
    metrics = service.repository.list_routing_metrics(project_id=project_id)
    assert sum(item.attempts for item in metrics) == 4
    assert sum(item.successes for item in metrics) == 4


def test_phase18_dialog_exposes_routing_policy_health_and_decisions(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.generation_orchestration_dialog import GenerationOrchestrationDialog

    now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
    database = Database(tmp_path / "phase18.db")
    database.initialize()
    project_id = _project(database)
    profiles, service = _services(tmp_path, database, now)
    primary = _profile(
        profiles,
        "Primary",
        "primary-key",
        active=True,
        priority=10,
        remaining=100_000,
    )
    backup = _profile(
        profiles,
        "Backup",
        "backup-key",
        active=False,
        priority=20,
        remaining=100_000,
    )
    profiles.save_failover_settings(
        "elevenlabs",
        FailoverSettings(mode=ApiProfileFailoverMode.AUTO, max_switches_per_run=4),
    )
    service.save_routing_policy(
        replace(
            service.default_routing_policy(project_id),
            enabled=True,
            mode=RoutingMode.ADAPTIVE,
        )
    )
    service.record_worker_event(
        {
            "project_id": project_id,
            "job_row_number": 1,
            "filename": "one.mp3",
            "provider": "elevenlabs",
            "from_profile_id": backup.profile_id,
            "from_profile_name": backup.display_name,
            "failure_category": "none",
            "error_code": "none",
            "outcome": "routed",
            "switch_number": 0,
            "consecutive_failures": 0,
            "circuit_opened": False,
            "metadata": {
                "routing_mode": "adaptive",
                "routing_score": 75,
                "routing_weight": 75,
                "characters": 20,
                "reason": "adaptive queue assignment",
            },
        }
    )
    dialog = GenerationOrchestrationDialog(
        service,
        project_id=project_id,
        project_name="Phase 18",
        settings_provider=lambda: _settings(primary.profile_id),
        export_dir=tmp_path / "exports",
    )

    assert dialog.windowTitle() == "Generation Orchestration & Adaptive Routing"
    assert dialog.routing_mode.count() == 3
    assert dialog.routing_mode.currentData() == RoutingMode.ADAPTIVE.value
    assert dialog.metrics_table.rowCount() == 1
    assert dialog.decision_table.rowCount() == 1
    assert "routing=adaptive" in dialog.plan_label.text()
