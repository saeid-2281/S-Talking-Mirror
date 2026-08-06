from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.capacity_readiness_service import CapacityReadinessService


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


def _read(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class _FakeSloService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "service-level-objectives"
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


def _service(root: Path) -> tuple[CapacityReadinessService, _FakeSloService]:
    runtime = _runtime(root)
    slo = _FakeSloService(runtime)
    service = CapacityReadinessService(
        runtime,
        slo,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, slo


def _slo_source(
    slo: _FakeSloService,
    *,
    suffix: str = "alpha",
    release_gate: str = "allow",
    decision: str = "allow",
) -> tuple[Path, Path, Path, Path]:
    snapshot_id = f"slo-snapshot-{suffix}"
    decision_id = f"slo-decision-{suffix}"
    snapshot_payload: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "generated_at": NOW.isoformat(),
        "status": "ready" if release_gate == "allow" else "ready_with_warnings",
        "release_gate": release_gate,
    }
    snapshot_payload["snapshot_sha256"] = _digest(snapshot_payload)
    snapshot_path = _write(
        slo.snapshots_dir / f"{snapshot_id}.json",
        snapshot_payload,
    )

    decision_payload: dict[str, object] = {
        "schema_version": 1,
        "decision_id": decision_id,
        "created_at": NOW.isoformat(),
        "decision": decision,
        "snapshot_filename": snapshot_path.name,
        "snapshot_sha256": _sha256(snapshot_path),
    }
    decision_payload["decision_sha256"] = _digest(decision_payload)
    decision_path = _write(
        slo.decisions_dir / f"{decision_id}.json",
        decision_payload,
    )

    pack_path = slo.audit_packs_dir / f"{decision_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("slo/snapshot.json", snapshot_path.read_bytes())
        archive.writestr("slo/decision.json", decision_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "decision_id": decision_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        slo.receipts_dir / f"{decision_id}-receipt.json",
        receipt_payload,
    )
    return snapshot_path, decision_path, pack_path, receipt_path


def _observation(
    service: CapacityReadinessService,
    *,
    current: int = 500,
    peak: int = 600,
    capacity: int = 1000,
    queue: int = 10,
    worker: float = 50.0,
    memory: float = 55.0,
    throttle: float = 0.0,
    growth: float = 0.2,
):
    result = service.create_observation(
        captured_at=NOW.isoformat(),
        interval_minutes=60,
        current_load_per_minute=current,
        peak_load_per_minute=peak,
        sustainable_capacity_per_minute=capacity,
        queue_depth=queue,
        worker_utilization_percent=worker,
        memory_utilization_percent=memory,
        provider_throttle_percent=throttle,
        daily_growth_percent=growth,
        owner="Reliability owner",
        notes="Human-reviewed aggregate capacity counters.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def _snapshot(root: Path, **observation_kwargs):
    service, slo = _service(root)
    observation = _observation(service, **observation_kwargs)
    source = _slo_source(slo)
    snapshot = service.snapshot(
        observation_paths=(observation.observation_path,),
        slo_snapshot_paths=(source[0],),
        slo_decision_paths=(source[1],),
        slo_pack_paths=(source[2],),
        slo_receipt_paths=(source[3],),
    )
    return service, observation, source, snapshot


def test_phase72_observation_is_reviewed_and_verifiable(tmp_path: Path) -> None:
    service, _slo = _service(tmp_path)
    dry_run = service.create_observation(
        captured_at=NOW.isoformat(),
        interval_minutes=60,
        current_load_per_minute=10,
        peak_load_per_minute=20,
        sustainable_capacity_per_minute=100,
        queue_depth=0,
        worker_utilization_percent=10,
        memory_utilization_percent=10,
        provider_throttle_percent=0,
        daily_growth_percent=0,
        owner="Owner",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"

    observation = _observation(service)
    ok, detail = service.verify_observation(observation.observation_path)
    assert ok, detail


def test_phase72_observation_rejects_inconsistent_or_private_input(
    tmp_path: Path,
) -> None:
    service, _slo = _service(tmp_path)
    inconsistent = service.create_observation(
        captured_at=NOW.isoformat(),
        interval_minutes=60,
        current_load_per_minute=100,
        peak_load_per_minute=90,
        sustainable_capacity_per_minute=80,
        queue_depth=0,
        worker_utilization_percent=10,
        memory_utilization_percent=10,
        provider_throttle_percent=0,
        daily_growth_percent=0,
        owner="Owner",
        acknowledge=True,
    )
    assert isinstance(inconsistent, dict)
    assert inconsistent["status"] == "blocked"

    private = service.create_observation(
        captured_at=NOW.isoformat(),
        interval_minutes=60,
        current_load_per_minute=10,
        peak_load_per_minute=20,
        sustainable_capacity_per_minute=100,
        queue_depth=0,
        worker_utilization_percent=10,
        memory_utilization_percent=10,
        provider_throttle_percent=0,
        daily_growth_percent=0,
        owner="api_key=secret",
        acknowledge=True,
    )
    assert isinstance(private, dict)
    assert private["status"] == "blocked"


def test_phase72_healthy_capacity_allows_release(tmp_path: Path) -> None:
    _service_instance, _observation_source, _slo, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.release_gate == "allow"
    assert snapshot.recommended_decision == "allow_release"
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0


def test_phase72_forecast_saturation_blocks_release(tmp_path: Path) -> None:
    _service_instance, _observation_source, _slo, snapshot = _snapshot(
        tmp_path,
        current=850,
        peak=900,
        capacity=1000,
        growth=2.0,
    )
    assert snapshot.status == "blocked"
    assert snapshot.release_gate == "hold"
    assert snapshot.projected_headroom_percent < 0
    assert any(
        gate.code == "forecast_headroom" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase72_pressure_warning_requires_manual_review(tmp_path: Path) -> None:
    _service_instance, _observation_source, _slo, snapshot = _snapshot(
        tmp_path,
        queue=150,
        worker=85,
    )
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.release_gate == "manual_review"
    assert snapshot.warning_count >= 2


def test_phase72_tampered_observation_or_held_slo_blocks(tmp_path: Path) -> None:
    service, slo = _service(tmp_path)
    observation = _observation(service)
    payload = _read(observation.observation_path)
    assert payload is not None
    payload["queue_depth"] = 9999
    _write(observation.observation_path, payload)
    source = _slo_source(slo, release_gate="hold", decision="hold")
    snapshot = service.snapshot(
        observation_paths=(observation.observation_path,),
        slo_snapshot_paths=(source[0],),
        slo_decision_paths=(source[1],),
        slo_pack_paths=(source[2],),
        slo_receipt_paths=(source[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.rejected_source_count >= 1


def test_phase72_decision_respects_gate_and_acknowledgement(tmp_path: Path) -> None:
    service, _observation_source, _slo, snapshot = _snapshot(tmp_path)
    dry_run = service.create_decision(
        snapshot,
        decision="allow_release",
        owner="Release owner",
        statement="Human reviewed capacity and SLO evidence.",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"

    result = service.create_decision(
        snapshot,
        decision="allow_release",
        owner="Release owner",
        statement="Human reviewed capacity and SLO evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    ok, detail = service.verify_decision(result.decision_path)
    assert ok, detail


def test_phase72_decision_tamper_is_detected(tmp_path: Path) -> None:
    service, _observation_source, _slo, snapshot = _snapshot(tmp_path)
    result = service.create_decision(
        snapshot,
        decision="allow_release",
        owner="Release owner",
        statement="Human reviewed capacity and SLO evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    payload = _read(result.decision_path)
    assert payload is not None
    payload["decision"] = "hold_release"
    _write(result.decision_path, payload)
    ok, detail = service.verify_decision(result.decision_path)
    assert not ok
    assert "SHA-256" in detail


def test_phase72_audit_pack_is_verifiable_and_never_acts_automatically(
    tmp_path: Path,
) -> None:
    service, _observation_source, _slo, snapshot = _snapshot(tmp_path)
    result = service.create_decision(
        snapshot,
        decision="allow_release",
        owner="Release owner",
        statement="Human reviewed capacity and SLO evidence.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    ok, detail = service.verify_audit_pack(result.audit_pack_path, result.receipt_path)
    assert ok, detail

    decision = _read(result.decision_path)
    assert decision is not None
    assert decision["automatic_scale"] is False
    assert decision["automatic_load_shedding"] is False
    assert decision["automatic_queue_change"] is False
    assert decision["automatic_deploy"] is False
    assert decision["automatic_release_decision"] is False

    result.audit_pack_path.write_bytes(result.audit_pack_path.read_bytes() + b"tamper")
    ok, _detail = service.verify_audit_pack(result.audit_pack_path, result.receipt_path)
    assert not ok

    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app" / "gui" / "dialogs" / "capacity_readiness_dialog.py").read_text(
        encoding="utf-8"
    )
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "capacity-readiness.ps1").read_text(
        encoding="utf-8"
    )
    assert "CapacityReadinessDialog" in dialog
    assert "capacity_readiness_service" in container
    assert "--capacity-snapshot" in frozen
    assert "--verify-capacity-pack" in frozen
    assert "automatic_scale" in service._safety_contract()
    assert "automatic_load_shedding" in service._safety_contract()
    assert "capacity-snapshot" in script
