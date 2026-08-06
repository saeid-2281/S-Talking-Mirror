from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.recovery_replay_service import RecoveryReplayService


NOW = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)


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


class _FakeDegradationService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "degradation-readiness"
        self.results_dir = root / "results"
        self.attestations_dir = root / "attestations"
        self.audit_packs_dir = root / "audit-packs"
        self.receipts_dir = root / "receipts"
        for path in (
            self.results_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def verify_result(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Result unreadable."
        expected = str(payload.pop("result_sha256", ""))
        return expected == _digest(payload), "Result verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Attestation unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if expected != _digest(payload):
            return False, "Attestation hash changed."
        result_path = self.results_dir / str(payload.get("result_filename") or "")
        if not result_path.is_file() or payload.get("result_sha256") != _sha256(result_path):
            return False, "Linked result changed."
        return True, "Attestation verified."

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


def _service(root: Path) -> tuple[RecoveryReplayService, _FakeDegradationService]:
    runtime = _runtime(root)
    degradation = _FakeDegradationService(runtime)
    service = RecoveryReplayService(
        runtime,
        degradation,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, degradation


def _degradation_source(
    service: _FakeDegradationService,
    *,
    suffix: str = "alpha",
    outcome_status: str = "verified",
    scenario: str = "provider_throttle",
) -> tuple[Path, Path, Path, Path]:
    drill_id = f"degradation-drill-{suffix}"
    result_payload: dict[str, object] = {
        "schema_version": 1,
        "drill_id": drill_id,
        "created_at": NOW.isoformat(),
        "scenario": scenario,
        "outcome_status": outcome_status,
        "human_reviewed": True,
    }
    result_payload["result_sha256"] = _digest(result_payload)
    result_path = _write(
        service.results_dir / f"{drill_id}-result.json", result_payload
    )

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "drill_id": drill_id,
        "created_at": NOW.isoformat(),
        "status": outcome_status,
        "result_filename": result_path.name,
        "result_sha256": _sha256(result_path),
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        service.attestations_dir / f"{drill_id}-attestation.json",
        attestation_payload,
    )

    pack_path = service.audit_packs_dir / f"{drill_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("degradation/result.json", result_path.read_bytes())
        archive.writestr("degradation/attestation.json", attestation_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "drill_id": drill_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        service.receipts_dir / f"{drill_id}-receipt.json", receipt_payload
    )
    return result_path, attestation_path, pack_path, receipt_path


def _plan(service: RecoveryReplayService):
    result = service.create_plan(
        expected_job_count=10,
        recovery_target_minutes=15,
        max_duplicate_requests=0,
        max_duplicate_outputs=0,
        max_orphan_artifacts=0,
        max_manifest_mismatches=0,
        max_cost_variance_percent=1.0,
        owner="Recovery owner",
        notes="Human-reviewed isolated queue replay plan.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def _snapshot(root: Path, *, outcome_status: str = "verified"):
    service, degradation = _service(root)
    plan = _plan(service)
    source = _degradation_source(degradation, outcome_status=outcome_status)
    snapshot = service.snapshot(
        plan_paths=(plan.plan_path,),
        degradation_result_paths=(source[0],),
        degradation_attestation_paths=(source[1],),
        degradation_pack_paths=(source[2],),
        degradation_receipt_paths=(source[3],),
    )
    return service, plan, source, snapshot


def _successful_result(service, plan, snapshot):
    return service.create_replay_result(
        snapshot,
        plan_path=plan.plan_path,
        attempted_jobs=10,
        resumed_jobs=10,
        completed_jobs=10,
        duplicate_api_requests=0,
        duplicate_outputs=0,
        orphan_artifacts=0,
        manifest_mismatches=0,
        cost_variance_percent=0.5,
        recovery_minutes=10,
        receipt_chain_verified=True,
        output_checksums_verified=True,
        dedicated_tests_passed=True,
        owner="Recovery reviewer",
        statement="The isolated recovery replay preserved output and billing integrity.",
        acknowledge=True,
    )


def test_phase74_plan_requires_acknowledgement_and_is_verifiable(tmp_path: Path) -> None:
    service, _degradation = _service(tmp_path)
    dry_run = service.create_plan(
        expected_job_count=10,
        recovery_target_minutes=15,
        max_duplicate_requests=0,
        max_duplicate_outputs=0,
        max_orphan_artifacts=0,
        max_manifest_mismatches=0,
        max_cost_variance_percent=1.0,
        owner="Owner",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"
    plan = _plan(service)
    ok, detail = service.verify_plan(plan.plan_path)
    assert ok, detail


def test_phase74_plan_rejects_invalid_or_private_input(tmp_path: Path) -> None:
    service, _degradation = _service(tmp_path)
    invalid = service.create_plan(
        expected_job_count=0,
        recovery_target_minutes=0,
        max_duplicate_requests=-1,
        max_duplicate_outputs=-1,
        max_orphan_artifacts=-1,
        max_manifest_mismatches=-1,
        max_cost_variance_percent=-1,
        owner="Owner",
        acknowledge=True,
    )
    assert isinstance(invalid, dict)
    assert invalid["status"] == "blocked"
    private = service.create_plan(
        expected_job_count=10,
        recovery_target_minutes=10,
        max_duplicate_requests=0,
        max_duplicate_outputs=0,
        max_orphan_artifacts=0,
        max_manifest_mismatches=0,
        max_cost_variance_percent=1,
        owner="api_key=secret",
        acknowledge=True,
    )
    assert isinstance(private, dict)
    assert private["status"] == "blocked"


def test_phase74_verified_phase73_source_is_ready(tmp_path: Path) -> None:
    _service_instance, _plan_source, _source, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.release_gate == "allow"
    assert snapshot.recommended_decision == "approve_recovery_replay"
    assert snapshot.blocker_count == 0


def test_phase74_withheld_or_incomplete_phase73_evidence_blocks(tmp_path: Path) -> None:
    service, plan, source, withheld = _snapshot(tmp_path, outcome_status="withheld")
    assert withheld.status == "blocked"
    incomplete = service.snapshot(
        plan_paths=(plan.plan_path,),
        degradation_result_paths=(source[0],),
        degradation_attestation_paths=(),
        degradation_pack_paths=(source[2],),
        degradation_receipt_paths=(source[3],),
    )
    assert incomplete.blocker_count >= 1


def test_phase74_successful_replay_creates_verifiable_chain(tmp_path: Path) -> None:
    service, plan, _source, snapshot = _snapshot(tmp_path)
    result = _successful_result(service, plan, snapshot)
    assert not isinstance(result, dict)
    assert result.outcome_status == "verified"
    for path, verifier in (
        (result.result_path, service.verify_result),
        (result.attestation_path, service.verify_attestation),
    ):
        ok, detail = verifier(path)
        assert ok, detail
    ok, detail = service.verify_audit_pack(result.audit_pack_path, result.receipt_path)
    assert ok, detail


def test_phase74_threshold_failure_is_preserved_as_withheld(tmp_path: Path) -> None:
    service, plan, _source, snapshot = _snapshot(tmp_path)
    result = service.create_replay_result(
        snapshot,
        plan_path=plan.plan_path,
        attempted_jobs=10,
        resumed_jobs=10,
        completed_jobs=9,
        duplicate_api_requests=2,
        duplicate_outputs=1,
        orphan_artifacts=1,
        manifest_mismatches=1,
        cost_variance_percent=5.0,
        recovery_minutes=60,
        receipt_chain_verified=False,
        output_checksums_verified=False,
        dedicated_tests_passed=False,
        owner="Reviewer",
        statement="The replay exceeded the reviewed safety limits.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    assert result.outcome_status == "withheld"
    ok, detail = service.verify_result(result.result_path)
    assert ok, detail


def test_phase74_invalid_measurements_are_blocked(tmp_path: Path) -> None:
    service, plan, _source, snapshot = _snapshot(tmp_path)
    result = service.create_replay_result(
        snapshot,
        plan_path=plan.plan_path,
        attempted_jobs=5,
        resumed_jobs=6,
        completed_jobs=5,
        duplicate_api_requests=0,
        duplicate_outputs=0,
        orphan_artifacts=0,
        manifest_mismatches=0,
        cost_variance_percent=0,
        recovery_minutes=5,
        receipt_chain_verified=True,
        output_checksums_verified=True,
        dedicated_tests_passed=True,
        owner="Reviewer",
        statement="Invalid measurement set.",
        acknowledge=True,
    )
    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase74_tampering_is_detected(tmp_path: Path) -> None:
    service, plan, _source, snapshot = _snapshot(tmp_path)
    result = _successful_result(service, plan, snapshot)
    assert not isinstance(result, dict)
    payload = _read(result.result_path)
    assert payload is not None
    payload["duplicate_outputs"] = 99
    _write(result.result_path, payload)
    ok, detail = service.verify_result(result.result_path)
    assert not ok
    assert "SHA-256" in detail
    ok, _detail = service.verify_attestation(result.attestation_path)
    assert not ok


def test_phase74_audit_pack_is_safe_and_application_is_wired(tmp_path: Path) -> None:
    service, plan, _source, snapshot = _snapshot(tmp_path)
    result = _successful_result(service, plan, snapshot)
    assert not isinstance(result, dict)
    with zipfile.ZipFile(result.audit_pack_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    for key, value in service._safety_contract().items():
        assert manifest[key] is value is False

    result.audit_pack_path.write_bytes(result.audit_pack_path.read_bytes() + b"tamper")
    ok, detail = service.verify_audit_pack(result.audit_pack_path, result.receipt_path)
    assert not ok
    assert "SHA-256" in detail or "size" in detail

    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app/gui/dialogs/recovery_replay_dialog.py").read_text(
        encoding="utf-8"
    )
    container = (root / "app/container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app/bootstrap.py").read_text(encoding="utf-8")
    main = (root / "app/gui/main.py").read_text(encoding="utf-8")
    frozen = (root / "app/frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts/recovery-replay.ps1").read_text(encoding="utf-8")
    documentation = (root / "docs/RECOVERY_REPLAY_PHASE74.md").read_text(
        encoding="utf-8"
    )
    assert "class RecoveryReplayDialog" in dialog
    assert "recovery_replay_service" in container
    assert "recovery_replay_service" in bootstrap
    assert "Recovery Replay Integrity & Duplicate Prevention" in main
    assert "_handle_recovery_replay_command" in frozen
    assert "--create-recovery-replay-plan" in script
    assert "never resumes queues" in documentation
