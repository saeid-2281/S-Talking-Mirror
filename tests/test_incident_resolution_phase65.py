from __future__ import annotations

import hashlib
import json
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.incident_resolution import IncidentResolutionRecord
from app.models.incident_support import IncidentSupportBundle
from app.models.incident_triage import IncidentTriageCase
from app.services.crash_recovery_service import CrashRecoveryService
from app.services.incident_resolution_service import IncidentResolutionService
from app.services.incident_support_service import IncidentSupportService
from app.services.incident_triage_service import IncidentTriageService
from app.services.post_ga_maintenance_service import PostGaMaintenanceService


NOW = datetime(2026, 8, 6, 8, 30, tzinfo=timezone.utc)
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


def _baseline(runtime: RuntimeConfig, post_ga: PostGaMaintenanceService) -> Path:
    evidence_root = runtime.artifacts_dir / "phase65-baseline-evidence"
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
        "baseline_id": "post-ga-phase65",
        "created_at": NOW.isoformat(),
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


def _triage_case(
    runtime: RuntimeConfig,
) -> tuple[IncidentResolutionService, IncidentTriageCase]:
    Usage = namedtuple("usage", "total used free")
    crash = CrashRecoveryService(runtime, now=lambda: NOW)
    post_ga = PostGaMaintenanceService(
        runtime,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    baseline = _baseline(runtime, post_ga)
    support = IncidentSupportService(
        runtime,
        crash,
        post_ga,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
        disk_usage=lambda _path: Usage(10 * 1024**3, 5 * 1024**3, 4 * 1024**3),
    )
    record = crash.capture_message("controlled phase65 queue failure", source="phase65-test")
    assert record is not None
    crash.acknowledge(record.report_id)
    (runtime.log_dir / "application.log").write_text(
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
        now=lambda: NOW,
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
        now=lambda: NOW,
    )
    return resolution, case


def _evidence(
    service: IncidentResolutionService,
    root: Path,
    *,
    case_id: str,
    kind: str,
    tests_passed: int,
    tests_skipped: int = 0,
) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": kind,
        "case_id": case_id,
        "generated_at": NOW.isoformat(),
        "status": "passed",
        "tests_collected": tests_passed + tests_skipped,
        "tests_passed": tests_passed,
        "tests_skipped": tests_skipped,
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
    payload["evidence_sha256"] = service._payload_digest(payload)
    return _write(root / f"{kind}.json", payload)


def _ready_snapshot(
    root: Path,
) -> tuple[IncidentResolutionService, IncidentTriageCase, object, tuple[Path, Path]]:
    runtime = _runtime(root)
    service, case = _triage_case(runtime)
    dedicated = _evidence(
        service,
        root / "verification",
        case_id=case.case_id,
        kind="dedicated_regression",
        tests_passed=9,
    )
    full = _evidence(
        service,
        root / "verification",
        case_id=case.case_id,
        kind="full_quality_gate",
        tests_passed=886,
        tests_skipped=1,
    )
    snapshot = service.snapshot(
        case_path=case.case_path,
        plan_path=case.plan_path,
        resolution_summary=RESOLUTION_SUMMARY,
        customer_impact=CUSTOMER_IMPACT,
        resolution_type="code_fix",
        evidence_paths=(dedicated, full),
    )
    return service, case, snapshot, (dedicated, full)


def test_phase65_ready_snapshot_requires_verified_case_plan_and_both_test_records(
    tmp_path: Path,
) -> None:
    service, case, snapshot, _evidence_paths = _ready_snapshot(tmp_path)

    assert snapshot.status == "ready"
    assert snapshot.closure_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.case_id == case.case_id
    assert snapshot.priority == "P1"
    assert snapshot.component == "queue"
    assert {item.kind for item in snapshot.evidence} == service.EVIDENCE_KINDS
    assert len(snapshot.actions) == 6
    assert all(action.automatic is False for action in snapshot.actions)


def test_phase65_tampered_phase64_plan_blocks_closure(tmp_path: Path) -> None:
    service, case, _snapshot, evidence_paths = _ready_snapshot(tmp_path)
    payload = json.loads(case.plan_path.read_text(encoding="utf-8"))
    payload["priority"] = "P3"
    _write(case.plan_path, payload)

    snapshot = service.snapshot(
        case_path=case.case_path,
        plan_path=case.plan_path,
        resolution_summary=RESOLUTION_SUMMARY,
        customer_impact=CUSTOMER_IMPACT,
        evidence_paths=evidence_paths,
    )

    assert snapshot.status == "blocked"
    assert not snapshot.closure_allowed
    assert any(
        gate.code == "remediation_plan" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase65_missing_quality_gate_evidence_blocks_closure(tmp_path: Path) -> None:
    service, case, _snapshot, evidence_paths = _ready_snapshot(tmp_path)

    snapshot = service.snapshot(
        case_path=case.case_path,
        plan_path=case.plan_path,
        resolution_summary=RESOLUTION_SUMMARY,
        customer_impact=CUSTOMER_IMPACT,
        evidence_paths=(evidence_paths[0],),
    )

    assert snapshot.status == "blocked"
    assert any(
        gate.code == "verification_evidence" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase65_secret_or_local_path_in_closure_text_is_blocked(tmp_path: Path) -> None:
    service, case, _snapshot, evidence_paths = _ready_snapshot(tmp_path)

    snapshot = service.snapshot(
        case_path=case.case_path,
        plan_path=case.plan_path,
        resolution_summary="The issue was fixed with api_key=sk-secret-token-value-123456.",
        customer_impact="Review D:\\Users\\PrivateName\\Documents before continuing.",
        evidence_paths=evidence_paths,
    )

    assert snapshot.status == "blocked"
    assert {gate.code for gate in snapshot.gates if gate.status == "block"} >= {
        "resolution_summary",
        "customer_impact",
    }


def test_phase65_closure_creation_is_dry_run_until_acknowledged(tmp_path: Path) -> None:
    service, _case, snapshot, _evidence_paths = _ready_snapshot(tmp_path)

    result = service.create_closure(snapshot, acknowledge=False)

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"
    assert not tuple(service.records_dir.glob("*.json"))
    assert not tuple(service.closures_dir.glob("*.json"))
    assert not tuple(service.knowledge_dir.glob("*.json"))


def test_phase65_acknowledged_closure_creates_verified_privacy_safe_chain(
    tmp_path: Path,
) -> None:
    service, case, snapshot, _evidence_paths = _ready_snapshot(tmp_path)

    result = service.create_closure(snapshot, acknowledge=True)

    assert isinstance(result, IncidentResolutionRecord)
    resolution_ok, resolution_detail = service.verify_resolution(result.resolution_path)
    closure_ok, closure_detail = service.verify_closure(result.closure_path)
    knowledge_ok, knowledge_detail = service.verify_knowledge(result.knowledge_path)
    assert resolution_ok, resolution_detail
    assert closure_ok, closure_detail
    assert knowledge_ok, knowledge_detail
    resolution = json.loads(result.resolution_path.read_text(encoding="utf-8"))
    closure = json.loads(result.closure_path.read_text(encoding="utf-8"))
    knowledge = json.loads(result.knowledge_path.read_text(encoding="utf-8"))
    assert resolution["case_id"] == case.case_id
    assert resolution["private_data_included"] is False
    assert closure["customer_notification_sent"] is False
    assert closure["external_ticket_closed"] is False
    assert knowledge["published"] is False
    assert knowledge["human_review_required_before_publish"] is True
    for name in (
        "automatic_deploy",
        "automatic_patch",
        "automatic_rollback",
        "automatic_restart",
        "automatic_ticket_closure",
        "automatic_customer_notification",
        "automatic_publish",
    ):
        assert resolution[name] is False
        assert closure[name] is False


def test_phase65_resolution_closure_and_knowledge_tamper_are_detected(
    tmp_path: Path,
) -> None:
    service, _case, snapshot, _evidence_paths = _ready_snapshot(tmp_path)
    result = service.create_closure(snapshot, acknowledge=True)
    assert isinstance(result, IncidentResolutionRecord)

    resolution = json.loads(result.resolution_path.read_text(encoding="utf-8"))
    resolution["resolution_type"] = "rollback"
    _write(result.resolution_path, resolution)
    ok, detail = service.verify_resolution(result.resolution_path)
    assert not ok
    assert "SHA-256" in detail

    closure = json.loads(result.closure_path.read_text(encoding="utf-8"))
    closure["customer_notification_sent"] = True
    _write(result.closure_path, closure)
    ok, detail = service.verify_closure(result.closure_path)
    assert not ok
    assert "SHA-256" in detail

    knowledge = json.loads(result.knowledge_path.read_text(encoding="utf-8"))
    knowledge["published"] = True
    _write(result.knowledge_path, knowledge)
    ok, detail = service.verify_knowledge(result.knowledge_path)
    assert not ok
    assert "SHA-256" in detail


def test_phase65_existing_verified_closure_blocks_duplicate_case_closure(
    tmp_path: Path,
) -> None:
    service, case, snapshot, evidence_paths = _ready_snapshot(tmp_path)
    result = service.create_closure(snapshot, acknowledge=True)
    assert isinstance(result, IncidentResolutionRecord)

    second = service.snapshot(
        case_path=case.case_path,
        plan_path=case.plan_path,
        resolution_summary=RESOLUTION_SUMMARY,
        customer_impact=CUSTOMER_IMPACT,
        resolution_type="code_fix",
        evidence_paths=evidence_paths,
    )

    assert second.status == "blocked"
    assert second.duplicate_count == 1
    assert any(
        gate.code == "duplicate_closure" and gate.status == "block"
        for gate in second.gates
    )


def test_phase65_ui_container_cli_script_and_manual_operation_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app" / "gui" / "dialogs" / "incident_resolution_dialog.py").read_text(
        encoding="utf-8"
    )
    service = (root / "app" / "services" / "incident_resolution_service.py").read_text(
        encoding="utf-8"
    )
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app" / "bootstrap.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "incident-resolution.ps1").read_text(encoding="utf-8")
    documentation = (root / "docs" / "INCIDENT_RESOLUTION_PHASE65.md").read_text(
        encoding="utf-8"
    )

    assert 'setObjectName("incidentResolutionDialog")' in dialog
    assert "Incident Resolution & Closure" in main
    assert "incident-resolution" in main
    assert "incident_resolution_service" in container
    assert "incident_resolution_service" in bootstrap
    assert "--create-incident-resolution" in frozen
    assert "--verify-incident-knowledge" in frozen
    assert "--acknowledge-incident-resolution" in script
    assert "never deploys a fix, applies a patch" in documentation
    assert '"automatic_ticket_closure": False' in service
    assert '"automatic_customer_notification": False' in service
    assert '"automatic_publish": False' in service
    assert "Raw arbitrary logs, project sources, databases and settings are never copied" in documentation
