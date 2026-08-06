from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.service_level_objectives_service import ServiceLevelObjectivesService


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


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


class _FakeContinuityService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "service-continuity"
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
            return False, "Result is unreadable."
        expected = str(payload.pop("result_sha256", ""))
        if expected != _digest(payload):
            return False, "Result hash changed."
        return payload.get("outcome") == "passed", "Result verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if expected != _digest(payload):
            return False, "Attestation hash changed."
        return payload.get("status") == "verified", "Attestation verified."

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


def _read(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _service(root: Path) -> tuple[ServiceLevelObjectivesService, _FakeContinuityService]:
    runtime = _runtime(root)
    continuity = _FakeContinuityService(runtime)
    service = ServiceLevelObjectivesService(
        runtime,
        continuity,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, continuity


def _continuity_source(
    continuity: _FakeContinuityService,
    *,
    suffix: str = "alpha",
    outcome: str = "passed",
    attestation_status: str = "verified",
) -> tuple[Path, Path, Path, Path]:
    drill_id = f"continuity-{suffix}"
    result_payload: dict[str, object] = {
        "schema_version": 1,
        "drill_id": drill_id,
        "created_at": NOW.isoformat(),
        "outcome": outcome,
    }
    result_payload["result_sha256"] = _digest(result_payload)
    result_path = _write(
        continuity.results_dir / f"{drill_id}-result.json",
        result_payload,
    )

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "drill_id": drill_id,
        "created_at": NOW.isoformat(),
        "status": attestation_status,
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        continuity.attestations_dir / f"{drill_id}-attestation.json",
        attestation_payload,
    )

    pack_path = continuity.audit_packs_dir / f"{drill_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("continuity/result.json", result_path.read_bytes())
        archive.writestr("continuity/attestation.json", attestation_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "drill_id": drill_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        continuity.receipts_dir / f"{drill_id}-receipt.json",
        receipt_payload,
    )
    return result_path, attestation_path, pack_path, receipt_path


def _observation(
    service: ServiceLevelObjectivesService,
    *,
    days: int = 30,
    unavailable_minutes: int = 10,
    total: int = 10000,
    failed: int = 10,
    latency: int = 900,
):
    result = service.create_observation(
        window_start=(NOW - timedelta(days=days)).isoformat(),
        window_end=NOW.isoformat(),
        total_operations=total,
        successful_operations=total - failed,
        failed_operations=failed,
        unavailable_minutes=unavailable_minutes,
        p95_latency_ms=latency,
        owner="Reliability owner",
        notes="Human reviewed stable operational metrics.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def _snapshot(
    root: Path,
    *,
    days: int = 30,
    unavailable_minutes: int = 10,
    failed: int = 10,
    latency: int = 900,
):
    service, continuity = _service(root)
    observation = _observation(
        service,
        days=days,
        unavailable_minutes=unavailable_minutes,
        failed=failed,
        latency=latency,
    )
    continuity_source = _continuity_source(continuity)
    snapshot = service.snapshot(
        observation_paths=(observation.observation_path,),
        continuity_result_paths=(continuity_source[0],),
        continuity_attestation_paths=(continuity_source[1],),
        continuity_pack_paths=(continuity_source[2],),
        continuity_receipt_paths=(continuity_source[3],),
        window_days=30,
    )
    return service, observation, continuity_source, snapshot


def test_phase71_observation_is_human_reviewed_and_verifiable(tmp_path: Path) -> None:
    service, _continuity = _service(tmp_path)
    dry_run = service.create_observation(
        window_start=(NOW - timedelta(days=30)).isoformat(),
        window_end=NOW.isoformat(),
        total_operations=100,
        successful_operations=100,
        failed_operations=0,
        unavailable_minutes=0,
        p95_latency_ms=100,
        owner="Owner",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"

    observation = _observation(service)
    ok, detail = service.verify_observation(observation.observation_path)
    assert ok, detail


def test_phase71_observation_rejects_inconsistent_or_private_input(
    tmp_path: Path,
) -> None:
    service, _continuity = _service(tmp_path)
    inconsistent = service.create_observation(
        window_start=(NOW - timedelta(days=1)).isoformat(),
        window_end=NOW.isoformat(),
        total_operations=10,
        successful_operations=8,
        failed_operations=1,
        unavailable_minutes=0,
        p95_latency_ms=100,
        owner="Owner",
        acknowledge=True,
    )
    assert isinstance(inconsistent, dict)
    assert inconsistent["status"] == "blocked"

    private = service.create_observation(
        window_start=(NOW - timedelta(days=1)).isoformat(),
        window_end=NOW.isoformat(),
        total_operations=10,
        successful_operations=10,
        failed_operations=0,
        unavailable_minutes=0,
        p95_latency_ms=100,
        owner="api_key=secret",
        acknowledge=True,
    )
    assert isinstance(private, dict)
    assert private["status"] == "blocked"


def test_phase71_healthy_slo_and_continuity_allow_release(tmp_path: Path) -> None:
    _service_instance, _observation_source, _continuity, snapshot = _snapshot(
        tmp_path
    )

    assert snapshot.status == "ready"
    assert snapshot.release_gate == "allow"
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.verified_observation_count == 1
    assert snapshot.verified_continuity_count == 1


def test_phase71_exhausted_error_budget_blocks_release(tmp_path: Path) -> None:
    _service_instance, _observation_source, _continuity, snapshot = _snapshot(
        tmp_path,
        unavailable_minutes=100,
    )

    assert snapshot.status == "blocked"
    assert snapshot.release_gate == "hold"
    assert snapshot.error_budget_burn_rate > 1.0
    assert any(gate.code == "error_budget" and gate.status == "block" for gate in snapshot.gates)


def test_phase71_near_budget_or_incomplete_coverage_requires_review(
    tmp_path: Path,
) -> None:
    service, continuity = _service(tmp_path)
    observation = _observation(service, days=29, unavailable_minutes=34)
    source = _continuity_source(continuity)
    snapshot = service.snapshot(
        observation_paths=(observation.observation_path,),
        continuity_result_paths=(source[0],),
        continuity_attestation_paths=(source[1],),
        continuity_pack_paths=(source[2],),
        continuity_receipt_paths=(source[3],),
        window_days=30,
    )

    assert snapshot.status == "ready_with_warnings"
    assert snapshot.release_gate == "manual_review"
    assert snapshot.warning_count >= 1


def test_phase71_tampered_observation_or_failed_continuity_blocks(
    tmp_path: Path,
) -> None:
    service, continuity = _service(tmp_path)
    observation = _observation(service)
    payload = _read(observation.observation_path)
    assert payload is not None
    payload["failed_operations"] = 99
    _write(observation.observation_path, payload)
    failed_source = _continuity_source(
        continuity,
        outcome="failed",
        attestation_status="withheld",
    )
    snapshot = service.snapshot(
        observation_paths=(observation.observation_path,),
        continuity_result_paths=(failed_source[0],),
        continuity_attestation_paths=(failed_source[1],),
        continuity_pack_paths=(failed_source[2],),
        continuity_receipt_paths=(failed_source[3],),
    )

    assert snapshot.status == "blocked"
    assert snapshot.rejected_source_count == 2


def test_phase71_decision_respects_calculated_gate_and_acknowledgement(
    tmp_path: Path,
) -> None:
    service, _observation_source, _continuity, snapshot = _snapshot(tmp_path)
    dry_run = service.create_release_decision(
        snapshot,
        decision="allow",
        owner="Release owner",
        statement="Human reviewed SLO and continuity evidence.",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"

    result = service.create_release_decision(
        snapshot,
        decision="allow",
        owner="Release owner",
        statement="Human reviewed SLO and continuity evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    ok, detail = service.verify_decision(result.decision_path)
    assert ok, detail


def test_phase71_decision_tamper_is_detected(tmp_path: Path) -> None:
    service, _observation_source, _continuity, snapshot = _snapshot(tmp_path)
    result = service.create_release_decision(
        snapshot,
        decision="allow",
        owner="Release owner",
        statement="Human reviewed SLO and continuity evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    payload = _read(result.decision_path)
    assert payload is not None
    payload["decision"] = "hold"
    _write(result.decision_path, payload)

    ok, detail = service.verify_decision(result.decision_path)
    assert not ok
    assert "SHA-256" in detail


def test_phase71_audit_pack_is_verifiable_and_never_acts_automatically(
    tmp_path: Path,
) -> None:
    service, _observation_source, _continuity, snapshot = _snapshot(tmp_path)
    result = service.create_release_decision(
        snapshot,
        decision="allow",
        owner="Release owner",
        statement="Human reviewed SLO and continuity evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    ok, detail = service.verify_audit_pack(
        result.audit_pack_path,
        result.receipt_path,
    )
    assert ok, detail

    decision = _read(result.decision_path)
    assert decision is not None
    assert decision["automatic_deploy"] is False
    assert decision["automatic_rollback"] is False
    assert decision["automatic_restart"] is False
    assert decision["automatic_publish"] is False
    assert decision["automatic_release_decision"] is False

    result.audit_pack_path.write_bytes(result.audit_pack_path.read_bytes() + b"tamper")
    ok, _detail = service.verify_audit_pack(
        result.audit_pack_path,
        result.receipt_path,
    )
    assert not ok
