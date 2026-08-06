from __future__ import annotations

import hashlib
import json
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.incident_prevention import IncidentPreventionRecord
from app.models.incident_resolution import IncidentResolutionRecord
from app.models.incident_support import IncidentSupportBundle
from app.models.incident_triage import IncidentTriageCase
from app.services.crash_recovery_service import CrashRecoveryService
from app.services.incident_prevention_service import IncidentPreventionService
from app.services.incident_resolution_service import IncidentResolutionService
from app.services.incident_support_service import IncidentSupportService
from app.services.incident_triage_service import IncidentTriageService
from app.services.post_ga_maintenance_service import PostGaMaintenanceService


NOW = datetime(2026, 8, 6, 9, 30, tzinfo=timezone.utc)
INCIDENT_SUMMARY = (
    "Queue resume leaves generation jobs pending while the interface remains responsive."
)
RESOLUTION_SUMMARY = (
    "The queue resume transition now restores pending jobs and preserves scheduler state."
)
CUSTOMER_IMPACT = (
    "Affected queued jobs can continue normally after resume without manual recreation."
)


def _runtime(root: Path) -> RuntimeConfig:
    runtime = RuntimeConfig(
        app_root=root,
        data_dir=root / "data",
        database_path=root / "data" / "s_talking.db",
        legacy_database_path=root / "data" / "s-talking.db",
        settings_path=root / "settings" / "settings.json",
        log_dir=root / "logs",
        cache_dir=root / "cache",
        default_output_dir=root / "output",
        reports_dir=root / "reports",
        artifacts_dir=root / "artifacts",
        resource_dir=root,
    )
    runtime.ensure_directories()
    return runtime


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _baseline(
    runtime: RuntimeConfig,
    post_ga: PostGaMaintenanceService,
    now: datetime,
) -> Path:
    evidence_root = runtime.artifacts_dir / "phase66-baseline-evidence"
    artifacts = []
    for index in range(3):
        path = _write(evidence_root / f"evidence-{index}.json", {"index": index})
        artifacts.append(
            {
                "role": f"evidence_{index}",
                "path": path.resolve().relative_to(runtime.app_root.resolve()).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "baseline_id": "post-ga-phase66",
        "created_at": now.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "status": "ready",
        "warning_count": 0,
        "evidence_age_days": 0,
        "rollout_percentage": 100,
        "free_space_bytes": 4 * 1024**3,
        "manual_maintenance_required": True,
        "automatic_cleanup": False,
        "automatic_publish": False,
        "automatic_update": False,
        "automatic_restart": False,
        "gates": [],
        "artifacts": artifacts,
        "private_data_included": False,
    }
    payload["baseline_sha256"] = post_ga._payload_digest(payload)
    path = post_ga.default_baseline_path()
    _write(path, payload)
    return path


def _create_closure(
    runtime: RuntimeConfig,
    *,
    now: datetime,
    suffix: str,
) -> tuple[IncidentResolutionService, IncidentResolutionRecord]:
    Usage = namedtuple("usage", "total used free")
    crash = CrashRecoveryService(runtime, now=lambda: now)
    post_ga = PostGaMaintenanceService(
        runtime,
        version="1.0.0",
        channel="stable",
        now=lambda: now,
    )
    baseline = _baseline(runtime, post_ga, now)
    support = IncidentSupportService(
        runtime,
        crash,
        post_ga,
        version="1.0.0",
        channel="stable",
        now=lambda: now,
        disk_usage=lambda _path: Usage(10 * 1024**3, 5 * 1024**3, 4 * 1024**3),
    )
    report = crash.capture_message(
        f"controlled phase66 queue failure {suffix}",
        source="phase66-test",
    )
    assert report is not None
    crash.acknowledge(report.report_id)
    (runtime.log_dir / f"application-{suffix}.log").write_text(
        "Queue resumed and remained pending before the verified fix.\n",
        encoding="utf-8",
    )
    support_snapshot = support.snapshot(
        summary=INCIDENT_SUMMARY,
        severity="high",
        baseline_path=baseline,
        include_logs=True,
    )
    bundle = support.create_bundle(
        support_snapshot,
        baseline_path=baseline,
        include_logs=True,
        acknowledge=True,
    )
    assert isinstance(bundle, IncidentSupportBundle)

    triage = IncidentTriageService(
        runtime,
        support,
        version="1.0.0",
        channel="stable",
        now=lambda: now,
    )
    triage_snapshot = triage.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )
    case = triage.create_case(triage_snapshot, acknowledge=True)
    assert isinstance(case, IncidentTriageCase)

    resolution = IncidentResolutionService(
        runtime,
        triage,
        version="1.0.0",
        channel="stable",
        now=lambda: now,
    )
    evidence_root = runtime.artifacts_dir / "phase66-verification" / suffix
    evidence_paths = []
    for kind, passed, skipped in (
        ("dedicated_regression", 9, 0),
        ("full_quality_gate", 895, 1),
    ):
        payload: dict[str, object] = {
            "schema_version": 1,
            "kind": kind,
            "case_id": case.case_id,
            "generated_at": now.isoformat(),
            "status": "passed",
            "tests_collected": passed + skipped,
            "tests_passed": passed,
            "tests_skipped": skipped,
            "tests_failed": 0,
            "compileall_passed": kind == "full_quality_gate",
            "ruff_passed": kind == "full_quality_gate",
            "manual_attestation": True,
            "automatic_deploy": False,
            "automatic_patch": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        payload["evidence_sha256"] = resolution._payload_digest(payload)
        evidence_paths.append(_write(evidence_root / f"{kind}.json", payload))
    snapshot = resolution.snapshot(
        case_path=case.case_path,
        plan_path=case.plan_path,
        resolution_summary=RESOLUTION_SUMMARY,
        customer_impact=CUSTOMER_IMPACT,
        resolution_type="code_fix",
        evidence_paths=tuple(evidence_paths),
    )
    record = resolution.create_closure(snapshot, acknowledge=True)
    assert isinstance(record, IncidentResolutionRecord)
    return resolution, record


def _service_with_closures(
    root: Path,
    *,
    count: int = 1,
    first_age_days: int = 5,
) -> tuple[IncidentPreventionService, tuple[IncidentResolutionRecord, ...]]:
    runtime = _runtime(root)
    records = []
    resolution = None
    for index in range(count):
        closed_at = NOW - timedelta(days=max(0, first_age_days - index))
        resolution, record = _create_closure(
            runtime,
            now=closed_at,
            suffix=str(index),
        )
        records.append(record)
    assert resolution is not None
    service = IncidentPreventionService(
        runtime,
        resolution,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, tuple(records)


def test_phase66_single_verified_closure_creates_ready_nonrecurring_snapshot(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path)

    snapshot = service.snapshot(closure_paths=(records[0].closure_path,))

    assert snapshot.status == "ready_with_warnings"
    assert snapshot.baseline_allowed
    assert snapshot.verified_count == 1
    assert snapshot.rejected_count == 0
    assert snapshot.recurring_pattern_count == 0
    assert snapshot.high_risk_pattern_count == 1
    assert len(snapshot.patterns) == 1
    assert len(snapshot.actions) == 7
    assert all(action.automatic is False for action in snapshot.actions)


def test_phase66_repeated_fingerprint_is_grouped_and_flagged_for_prevention(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path, count=2)

    snapshot = service.snapshot(
        closure_paths=tuple(record.closure_path for record in records),
    )

    assert snapshot.baseline_allowed
    assert snapshot.verified_count == 2
    assert len(snapshot.patterns) == 1
    pattern = snapshot.patterns[0]
    assert pattern.occurrence_count == 2
    assert pattern.recurring
    assert pattern.high_risk
    assert pattern.risk_score == 95
    assert snapshot.recurring_pattern_count == 1
    assert any(action.pattern_fingerprint == pattern.fingerprint for action in snapshot.actions)


def test_phase66_tampered_closure_is_rejected_and_blocks_empty_analysis(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path)
    closure = records[0].closure_path
    payload = json.loads(closure.read_text(encoding="utf-8"))
    payload["priority"] = "P3"
    _write(closure, payload)

    snapshot = service.snapshot(closure_paths=(closure,))

    assert snapshot.status == "blocked"
    assert not snapshot.baseline_allowed
    assert snapshot.verified_count == 0
    assert snapshot.rejected_count == 1
    assert any(
        gate.code == "closure_integrity" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase66_lookback_excludes_old_closure_and_requires_in_scope_evidence(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path, first_age_days=120)

    snapshot = service.snapshot(
        closure_paths=(records[0].closure_path,),
        lookback_days=90,
    )

    assert snapshot.status == "blocked"
    assert snapshot.ignored_count == 1
    assert snapshot.verified_count == 0
    assert any(gate.code == "lookback_scope" and gate.status == "warn" for gate in snapshot.gates)


def test_phase66_invalid_analysis_parameters_are_blocked(tmp_path: Path) -> None:
    service, records = _service_with_closures(tmp_path)

    snapshot = service.snapshot(
        closure_paths=(records[0].closure_path,),
        lookback_days=1,
        recurrence_threshold=1,
        high_risk_threshold=20,
    )

    assert snapshot.status == "blocked"
    assert any(
        gate.code == "analysis_policy" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase66_baseline_creation_remains_dry_run_until_acknowledged(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path)
    snapshot = service.snapshot(closure_paths=(records[0].closure_path,))

    result = service.create_baseline(snapshot, acknowledge=False)

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"
    assert not tuple(service.baselines_dir.glob("*.json"))
    assert not tuple(service.registers_dir.glob("*.json"))


def test_phase66_acknowledged_baseline_and_action_register_are_verified_and_private(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path, count=2)
    snapshot = service.snapshot(
        closure_paths=tuple(record.closure_path for record in records),
    )

    result = service.create_baseline(snapshot, acknowledge=True)

    assert isinstance(result, IncidentPreventionRecord)
    baseline_ok, baseline_detail = service.verify_baseline(result.baseline_path)
    register_ok, register_detail = service.verify_register(result.register_path)
    assert baseline_ok, baseline_detail
    assert register_ok, register_detail
    baseline = json.loads(result.baseline_path.read_text(encoding="utf-8"))
    register = json.loads(result.register_path.read_text(encoding="utf-8"))
    serialized = json.dumps((baseline, register), ensure_ascii=False)
    assert INCIDENT_SUMMARY not in serialized
    assert RESOLUTION_SUMMARY not in serialized
    assert CUSTOMER_IMPACT not in serialized
    assert baseline["private_data_included"] is False
    assert register["private_data_included"] is False
    assert all(action["automatic"] is False for action in register["actions"])
    assert all(action["status"] == "open" for action in register["actions"])


def test_phase66_baseline_and_register_tamper_are_detected(tmp_path: Path) -> None:
    service, records = _service_with_closures(tmp_path)
    snapshot = service.snapshot(closure_paths=(records[0].closure_path,))
    result = service.create_baseline(snapshot, acknowledge=True)
    assert isinstance(result, IncidentPreventionRecord)

    baseline = json.loads(result.baseline_path.read_text(encoding="utf-8"))
    baseline["metrics"]["open_action_count"] = 0
    _write(result.baseline_path, baseline)
    assert service.verify_baseline(result.baseline_path)[0] is False

    register = json.loads(result.register_path.read_text(encoding="utf-8"))
    register["actions"][0]["automatic"] = True
    _write(result.register_path, register)
    assert service.verify_register(result.register_path)[0] is False


def test_phase66_source_change_after_review_blocks_baseline_creation(
    tmp_path: Path,
) -> None:
    service, records = _service_with_closures(tmp_path)
    closure = records[0].closure_path
    snapshot = service.snapshot(closure_paths=(closure,))
    payload = json.loads(closure.read_text(encoding="utf-8"))
    payload["customer_notification_sent"] = True
    _write(closure, payload)

    result = service.create_baseline(snapshot, acknowledge=True)

    assert isinstance(result, dict)
    assert result["status"] == "blocked"
    assert not tuple(service.baselines_dir.glob("*.json"))
