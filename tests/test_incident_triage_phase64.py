from __future__ import annotations

import hashlib
import json
import zipfile
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.incident_support import IncidentSupportBundle
from app.models.incident_triage import IncidentTriageCase
from app.services.crash_recovery_service import CrashRecoveryService
from app.services.incident_support_service import IncidentSupportService
from app.services.incident_triage_service import IncidentTriageService
from app.services.post_ga_maintenance_service import PostGaMaintenanceService


NOW = datetime(2026, 8, 5, 19, 30, tzinfo=timezone.utc)
SUMMARY = "Queue resume leaves generation jobs pending while the interface remains responsive."


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
    evidence_root = runtime.artifacts_dir / "phase64-baseline-evidence"
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
        "baseline_id": "post-ga-phase64",
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


def _services(
    runtime: RuntimeConfig,
) -> tuple[CrashRecoveryService, IncidentSupportService, IncidentTriageService, Path]:
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
    triage = IncidentTriageService(
        runtime,
        support,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return crash, support, triage, baseline


def _bundle(
    runtime: RuntimeConfig,
    *,
    summary: str = SUMMARY,
    severity: str = "high",
    crash_count: int = 1,
    include_log: bool = True,
) -> tuple[IncidentTriageService, IncidentSupportBundle]:
    crash, support, triage, baseline = _services(runtime)
    for index in range(crash_count):
        record = crash.capture_message(f"controlled phase64 failure {index}", source="phase64-test")
        assert record is not None
        crash.acknowledge(record.report_id)
    if include_log:
        (runtime.log_dir / "application.log").write_text(
            "Queue resumed; generation remained pending.\n",
            encoding="utf-8",
        )
    snapshot = support.snapshot(
        summary=summary,
        severity=severity,
        baseline_path=baseline,
        include_logs=include_log,
    )
    result = support.create_bundle(
        snapshot,
        baseline_path=baseline,
        include_logs=include_log,
        acknowledge=True,
    )
    assert isinstance(result, IncidentSupportBundle)
    return triage, result


def test_phase64_ready_snapshot_verifies_bundle_receipt_priority_component_and_actions(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)

    snapshot = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )

    assert snapshot.status == "ready"
    assert snapshot.triage_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.priority == "P1"
    assert snapshot.component == "queue"
    assert snapshot.effective_severity == "high"
    assert snapshot.report_count == 1
    assert snapshot.log_count == 1
    assert len(snapshot.actions) == 6
    assert all(action.automatic is False for action in snapshot.actions)
    assert {gate.code for gate in snapshot.gates} >= {
        "support_bundle",
        "support_receipt",
        "incident_consistency",
        "severity_policy",
        "privacy_contract",
        "manual_remediation",
    }


def test_phase64_tampered_bundle_blocks_intake(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)
    extracted = tmp_path / "tampered"
    with zipfile.ZipFile(bundle.path) as archive:
        archive.extractall(extracted)
    summary_path = extracted / "incident" / "summary.json"
    summary_path.write_text(summary_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    tampered = service.incident_support_service.bundles_dir / "tampered-phase64.zip"
    with zipfile.ZipFile(tampered, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(extracted.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(extracted).as_posix())

    snapshot = service.snapshot(bundle_path=tampered)

    assert snapshot.status == "blocked"
    assert not snapshot.triage_allowed
    assert any(
        gate.code == "support_bundle" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase64_missing_receipt_is_warning_but_bundle_only_triage_is_allowed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)
    bundle.receipt_path.unlink()
    latest = service.incident_support_service.root / "latest-incident-support-receipt.json"
    latest.unlink(missing_ok=True)

    snapshot = service.snapshot(bundle_path=bundle.path)

    assert snapshot.status == "ready_with_warnings"
    assert snapshot.triage_allowed
    assert snapshot.blocker_count == 0
    assert any(
        gate.code == "support_receipt" and gate.status == "warn"
        for gate in snapshot.gates
    )


def test_phase64_evidence_policy_escalates_low_incident_to_high_priority(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(
        runtime,
        summary="Performance freeze repeats while five controlled crash reports are captured.",
        severity="low",
        crash_count=5,
        include_log=False,
    )

    snapshot = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )

    assert snapshot.reported_severity == "low"
    assert snapshot.effective_severity == "high"
    assert snapshot.priority == "P1"
    assert snapshot.component == "performance"
    assert any(
        gate.code == "severity_policy" and gate.status == "warn"
        for gate in snapshot.gates
    )


def test_phase64_case_creation_is_dry_run_until_acknowledged(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)
    snapshot = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )

    result = service.create_case(snapshot, acknowledge=False)

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"
    assert not tuple(service.cases_dir.glob("*.json"))
    assert not tuple(service.plans_dir.glob("*.json"))


def test_phase64_verified_case_and_plan_preserve_manual_privacy_contract(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)
    snapshot = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )

    result = service.create_case(snapshot, acknowledge=True)

    assert isinstance(result, IncidentTriageCase)
    case_ok, case_detail = service.verify_case(result.case_path)
    plan_ok, plan_detail = service.verify_plan(result.plan_path)
    assert case_ok, case_detail
    assert plan_ok, plan_detail
    case_payload = json.loads(result.case_path.read_text(encoding="utf-8"))
    plan_payload = json.loads(result.plan_path.read_text(encoding="utf-8"))
    for name in (
        "automatic_ticket_creation",
        "automatic_patch",
        "automatic_rollback",
        "automatic_restart",
        "automatic_publish",
    ):
        assert case_payload[name] is False
        assert plan_payload[name] is False
    assert case_payload["private_data_included"] is False
    assert plan_payload["private_data_included"] is False
    assert all(action["automatic"] is False for action in plan_payload["actions"])
    assert "summary" not in plan_payload


def test_phase64_case_and_plan_tamper_are_detected(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)
    snapshot = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )
    result = service.create_case(snapshot, acknowledge=True)
    assert isinstance(result, IncidentTriageCase)

    case_payload = json.loads(result.case_path.read_text(encoding="utf-8"))
    case_payload["priority"] = "P3"
    _write(result.case_path, case_payload)
    case_ok, case_detail = service.verify_case(result.case_path)
    assert not case_ok
    assert "SHA-256" in case_detail

    plan_payload = json.loads(result.plan_path.read_text(encoding="utf-8"))
    plan_payload["automatic_patch"] = True
    _write(result.plan_path, plan_payload)
    plan_ok, plan_detail = service.verify_plan(result.plan_path)
    assert not plan_ok
    assert "SHA-256" in plan_detail


def test_phase64_duplicate_fingerprint_warns_after_verified_case_creation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service, bundle = _bundle(runtime)
    first = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )
    result = service.create_case(first, acknowledge=True)
    assert isinstance(result, IncidentTriageCase)

    second = service.snapshot(
        bundle_path=bundle.path,
        receipt_path=bundle.receipt_path,
    )

    assert second.fingerprint == first.fingerprint
    assert second.duplicate_count == 1
    assert second.status == "ready_with_warnings"
    assert any(
        gate.code == "duplicate_detection" and gate.status == "warn"
        for gate in second.gates
    )


def test_phase64_ui_container_cli_script_and_no_automatic_operation_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app" / "gui" / "dialogs" / "incident_triage_dialog.py").read_text(
        encoding="utf-8"
    )
    service = (root / "app" / "services" / "incident_triage_service.py").read_text(
        encoding="utf-8"
    )
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app" / "bootstrap.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "incident-triage.ps1").read_text(encoding="utf-8")
    documentation = (root / "docs" / "INCIDENT_TRIAGE_PHASE64.md").read_text(
        encoding="utf-8"
    )

    assert 'setObjectName("incidentTriageDialog")' in dialog
    assert "Incident Triage & Remediation" in main
    assert "incident-triage" in main
    assert "incident_triage_service" in container
    assert "incident_triage_service" in bootstrap
    assert "--create-incident-triage-case" in frozen
    assert "--verify-incident-remediation-plan" in frozen
    assert "--acknowledge-incident-triage" in script
    assert "never uploads a bundle, creates an external ticket" in documentation
    assert '"automatic_ticket_creation": False' in service
    assert '"automatic_patch": False' in service
    assert '"automatic_rollback": False' in service
    assert "private source files are not copied" in service
