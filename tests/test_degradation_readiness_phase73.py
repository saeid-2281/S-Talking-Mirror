from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.degradation_readiness_service import DegradationReadinessService


NOW = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)


def _runtime(root: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(root)
    runtime.ensure_directories()
    return runtime


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _read(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class _FakeCapacityService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "capacity-readiness"
        self.snapshots_dir = root / "snapshots"
        self.decisions_dir = root / "decisions"
        self.audit_packs_dir = root / "audit-packs"
        self.receipts_dir = root / "receipts"
        for path in (
            self.snapshots_dir,
            self.decisions_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Snapshot unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        return expected == _digest(payload), "Snapshot verified."

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Decision unreadable."
        expected = str(payload.pop("decision_sha256", ""))
        return expected == _digest(payload), "Decision verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        receipt = _read(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Pack or receipt missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if expected != _digest(receipt):
            return False, "Receipt hash changed."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Pack filename changed."
        if receipt.get("pack_sha256") != _sha256(pack_path):
            return False, "Pack hash changed."
        return True, "Pack verified."


def _service(root: Path) -> tuple[DegradationReadinessService, _FakeCapacityService]:
    runtime = _runtime(root)
    capacity = _FakeCapacityService(runtime)
    service = DegradationReadinessService(
        runtime,
        capacity,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, capacity


def _capacity_source(
    capacity: _FakeCapacityService,
    *,
    suffix: str = "alpha",
    release_gate: str = "allow",
    decision: str = "allow_release",
    queue_depth: int = 10,
    worker: float = 50.0,
    memory: float = 55.0,
    throttle: float = 0.0,
) -> tuple[Path, Path, Path, Path]:
    snapshot_id = f"capacity-snapshot-{suffix}"
    decision_id = f"capacity-decision-{suffix}"
    snapshot_payload: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generated_at": NOW.isoformat(),
        "status": "ready" if release_gate == "allow" else "ready_with_warnings",
        "release_gate": release_gate,
        "max_queue_depth": queue_depth,
        "max_worker_utilization_percent": worker,
        "max_memory_utilization_percent": memory,
        "max_provider_throttle_percent": throttle,
    }
    snapshot_payload["snapshot_sha256"] = _digest(snapshot_payload)
    snapshot_path = _write(
        capacity.snapshots_dir / f"{snapshot_id}.json", snapshot_payload
    )

    decision_payload: dict[str, object] = {
        "schema_version": 1,
        "decision_id": decision_id,
        "created_at": NOW.isoformat(),
        "decision": decision,
        "calculated_release_gate": release_gate,
        "snapshot_filename": snapshot_path.name,
        "snapshot_sha256": _sha256(snapshot_path),
    }
    decision_payload["decision_sha256"] = _digest(decision_payload)
    decision_path = _write(
        capacity.decisions_dir / f"{decision_id}.json", decision_payload
    )

    pack_path = capacity.audit_packs_dir / f"{decision_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("capacity/snapshot.json", snapshot_path.read_bytes())
        archive.writestr("capacity/decision.json", decision_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "decision_id": decision_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        capacity.receipts_dir / f"{decision_id}-receipt.json", receipt_payload
    )
    return snapshot_path, decision_path, pack_path, receipt_path


def _plan(
    service: DegradationReadinessService,
    *,
    scenario: str = "provider_throttle",
    target: float = 20.0,
    queue_limit: int = 100,
    recovery_target: int = 15,
    failed_limit: int = 0,
):
    result = service.create_plan(
        scenario=scenario,
        target_load_reduction_percent=target,
        max_queue_depth=queue_limit,
        recovery_target_minutes=recovery_target,
        max_failed_requests=failed_limit,
        owner="Reliability owner",
        notes="Human-reviewed isolated drill plan.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def _snapshot(root: Path, **source_kwargs):
    service, capacity = _service(root)
    plan = _plan(service)
    source = _capacity_source(capacity, **source_kwargs)
    snapshot = service.snapshot(
        plan_paths=(plan.plan_path,),
        capacity_snapshot_paths=(source[0],),
        capacity_decision_paths=(source[1],),
        capacity_pack_paths=(source[2],),
        capacity_receipt_paths=(source[3],),
    )
    return service, plan, source, snapshot


def test_phase73_plan_is_reviewed_and_verifiable(tmp_path: Path) -> None:
    service, _capacity = _service(tmp_path)
    dry_run = service.create_plan(
        scenario="provider_throttle",
        target_load_reduction_percent=20,
        max_queue_depth=100,
        recovery_target_minutes=15,
        max_failed_requests=0,
        owner="Owner",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"

    plan = _plan(service)
    ok, detail = service.verify_plan(plan.plan_path)
    assert ok, detail


def test_phase73_plan_rejects_invalid_or_private_input(tmp_path: Path) -> None:
    service, _capacity = _service(tmp_path)
    invalid = service.create_plan(
        scenario="unknown",
        target_load_reduction_percent=1,
        max_queue_depth=-1,
        recovery_target_minutes=0,
        max_failed_requests=-1,
        owner="Owner",
        acknowledge=True,
    )
    assert isinstance(invalid, dict)
    assert invalid["status"] == "blocked"

    private = service.create_plan(
        scenario="provider_throttle",
        target_load_reduction_percent=20,
        max_queue_depth=10,
        recovery_target_minutes=10,
        max_failed_requests=0,
        owner="api_key=secret",
        acknowledge=True,
    )
    assert isinstance(private, dict)
    assert private["status"] == "blocked"


def test_phase73_healthy_capacity_and_plan_are_ready(tmp_path: Path) -> None:
    _service_instance, _plan_source, _capacity, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.release_gate == "allow"
    assert snapshot.recommended_decision == "approve_readiness"
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0


def test_phase73_prepare_degraded_mode_requires_full_scenario_coverage(
    tmp_path: Path,
) -> None:
    service, capacity = _service(tmp_path)
    plans = [_plan(service, scenario=scenario) for scenario in service.SCENARIOS]
    source = _capacity_source(
        capacity,
        release_gate="manual_review",
        decision="prepare_degraded_mode",
        queue_depth=150,
        worker=85,
        memory=85,
        throttle=10,
    )
    snapshot = service.snapshot(
        plan_paths=tuple(plan.plan_path for plan in plans),
        capacity_snapshot_paths=(source[0],),
        capacity_decision_paths=(source[1],),
        capacity_pack_paths=(source[2],),
        capacity_receipt_paths=(source[3],),
    )
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.release_gate == "manual_review"
    assert set(snapshot.required_scenarios) == set(service.SCENARIOS)
    assert snapshot.blocker_count == 0


def test_phase73_held_capacity_or_missing_scenario_blocks(tmp_path: Path) -> None:
    service, capacity = _service(tmp_path)
    plan = _plan(service, scenario="provider_throttle")
    source = _capacity_source(
        capacity,
        release_gate="hold",
        decision="hold_release",
        queue_depth=500,
    )
    snapshot = service.snapshot(
        plan_paths=(plan.plan_path,),
        capacity_snapshot_paths=(source[0],),
        capacity_decision_paths=(source[1],),
        capacity_pack_paths=(source[2],),
        capacity_receipt_paths=(source[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.release_gate == "hold"
    assert snapshot.blocker_count >= 1


def test_phase73_successful_drill_creates_verifiable_chain(tmp_path: Path) -> None:
    service, plan, _capacity, snapshot = _snapshot(tmp_path)
    result = service.create_drill_result(
        snapshot,
        plan_path=plan.plan_path,
        achieved_load_reduction_percent=25,
        observed_max_queue_depth=50,
        recovery_minutes=10,
        failed_requests=0,
        data_loss_count=0,
        health_checks_passed=True,
        dedicated_tests_passed=True,
        owner="Reliability reviewer",
        statement="The isolated drill met every reviewed recovery target.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    assert result.outcome_status == "verified"
    for path, verifier in (
        (result.result_path, service.verify_result),
        (result.attestation_path, service.verify_attestation),
    ):
        ok, detail = verifier(path)
        assert ok, detail
    ok, detail = service.verify_audit_pack(
        result.audit_pack_path, result.receipt_path
    )
    assert ok, detail


def test_phase73_failed_drill_is_preserved_as_withheld(tmp_path: Path) -> None:
    service, plan, _capacity, snapshot = _snapshot(tmp_path)
    result = service.create_drill_result(
        snapshot,
        plan_path=plan.plan_path,
        achieved_load_reduction_percent=5,
        observed_max_queue_depth=1000,
        recovery_minutes=60,
        failed_requests=5,
        data_loss_count=1,
        health_checks_passed=False,
        dedicated_tests_passed=False,
        owner="Reliability reviewer",
        statement="The isolated drill failed reviewed recovery targets.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    assert result.outcome_status == "withheld"
    ok, detail = service.verify_result(result.result_path)
    assert ok, detail


def test_phase73_tampered_result_or_attestation_is_detected(tmp_path: Path) -> None:
    service, plan, _capacity, snapshot = _snapshot(tmp_path)
    result = service.create_drill_result(
        snapshot,
        plan_path=plan.plan_path,
        achieved_load_reduction_percent=25,
        observed_max_queue_depth=50,
        recovery_minutes=10,
        failed_requests=0,
        data_loss_count=0,
        health_checks_passed=True,
        dedicated_tests_passed=True,
        owner="Reviewer",
        statement="Reviewed isolated drill evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    payload = _read(result.result_path)
    assert payload is not None
    payload["outcome_status"] = "withheld"
    _write(result.result_path, payload)
    ok, detail = service.verify_result(result.result_path)
    assert not ok
    assert "SHA-256" in detail
    ok, _detail = service.verify_attestation(result.attestation_path)
    assert not ok


def test_phase73_audit_pack_never_authorizes_automatic_actions(tmp_path: Path) -> None:
    service, plan, _capacity, snapshot = _snapshot(tmp_path)
    result = service.create_drill_result(
        snapshot,
        plan_path=plan.plan_path,
        achieved_load_reduction_percent=25,
        observed_max_queue_depth=50,
        recovery_minutes=10,
        failed_requests=0,
        data_loss_count=0,
        health_checks_passed=True,
        dedicated_tests_passed=True,
        owner="Reviewer",
        statement="Reviewed isolated drill evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    with zipfile.ZipFile(result.audit_pack_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    for key, value in service._safety_contract().items():
        assert manifest[key] is value is False

    result.audit_pack_path.write_bytes(result.audit_pack_path.read_bytes() + b"tamper")
    ok, detail = service.verify_audit_pack(
        result.audit_pack_path, result.receipt_path
    )
    assert not ok
    assert "SHA-256" in detail or "size" in detail

    root = Path(__file__).resolve().parents[1]
    dialog = (
        root / "app" / "gui" / "dialogs" / "degradation_readiness_dialog.py"
    ).read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app" / "bootstrap.py").read_text(encoding="utf-8")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "degradation-readiness.ps1").read_text(
        encoding="utf-8"
    )
    documentation = (
        root / "docs" / "DEGRADATION_READINESS_PHASE73.md"
    ).read_text(encoding="utf-8")
    assert "class DegradationReadinessDialog" in dialog
    assert "degradation_readiness_service" in container
    assert "degradation_readiness_service" in bootstrap
    assert "Controlled Degradation Drill & Recovery" in main
    assert "_handle_degradation_readiness_command" in frozen
    assert "--create-degradation-plan" in script
    assert "never performs load shedding" in documentation
