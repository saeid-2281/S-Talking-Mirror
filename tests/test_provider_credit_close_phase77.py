from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.provider_credit_close_service import ProviderCreditCloseService


NOW = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


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


class _FakeBillingDisputeResolutionService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "billing-dispute-resolution"
        self.settlements_dir = root / "settlements"
        self.attestations_dir = root / "attestations"
        self.closure_packs_dir = root / "closure-packs"
        self.receipts_dir = root / "receipts"
        for path in (
            self.settlements_dir,
            self.attestations_dir,
            self.closure_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def verify_settlement(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Settlement unreadable."
        expected = str(payload.pop("settlement_sha256", ""))
        return expected == _digest(payload), "Settlement verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Attestation unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if expected != _digest(payload):
            return False, "Attestation hash changed."
        settlement_path = self.settlements_dir / str(
            payload.get("settlement_filename") or ""
        )
        if not settlement_path.is_file() or payload.get("settlement_sha256") != _sha256(
            settlement_path
        ):
            return False, "Linked settlement changed."
        return True, "Attestation verified."

    def verify_closure_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
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


def _service(
    root: Path,
) -> tuple[ProviderCreditCloseService, _FakeBillingDisputeResolutionService]:
    runtime = _runtime(root)
    dispute = _FakeBillingDisputeResolutionService(runtime)
    service = ProviderCreditCloseService(
        runtime,
        dispute,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, dispute


def _source(
    dispute: _FakeBillingDisputeResolutionService,
    *,
    suffix: str = "alpha",
    outcome_status: str = "settled",
    currency: str = "USD",
    requested: float = 10.0,
    applied: float = 10.0,
    remaining: float = 0.0,
) -> tuple[Path, Path, Path, Path]:
    settlement_id = f"billing-settlement-{suffix}"
    settlement_payload: dict[str, object] = {
        "schema_version": 1,
        "settlement_id": settlement_id,
        "case_id": f"billing-dispute-case-{suffix}",
        "created_at": NOW.isoformat(),
        "outcome_status": outcome_status,
        "decision": (
            "close_billing_dispute"
            if outcome_status == "settled"
            else "continue_manual_provider_follow_up"
        ),
        "provider": "Example Provider",
        "invoice_id": f"INV-{suffix}",
        "currency": currency,
        "requested_credit_amount": f"{requested:.4f}",
        "approved_credit_amount": f"{applied:.4f}",
        "applied_credit_amount": f"{applied:.4f}",
        "remaining_variance_amount": f"{remaining:.4f}",
        "human_reviewed": True,
    }
    settlement_payload["settlement_sha256"] = _digest(settlement_payload)
    settlement_path = _write(
        dispute.settlements_dir / f"{settlement_id}.json",
        settlement_payload,
    )

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "settlement_id": settlement_id,
        "created_at": NOW.isoformat(),
        "status": outcome_status,
        "settlement_filename": settlement_path.name,
        "settlement_sha256": _sha256(settlement_path),
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        dispute.attestations_dir / f"{settlement_id}-attestation.json",
        attestation_payload,
    )

    pack_path = dispute.closure_packs_dir / f"{settlement_id}-closure-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("settlement.json", settlement_path.read_bytes())
        archive.writestr("attestation.json", attestation_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "settlement_id": settlement_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        dispute.receipts_dir / f"{settlement_id}-receipt.json",
        receipt_payload,
    )
    return settlement_path, attestation_path, pack_path, receipt_path


def _snapshot(
    root: Path,
    *,
    outcome_status: str = "settled",
    currency: str = "USD",
    requested: float = 10.0,
    applied: float = 10.0,
    remaining: float = 0.0,
):
    service, dispute = _service(root)
    source = _source(
        dispute,
        outcome_status=outcome_status,
        currency=currency,
        requested=requested,
        applied=applied,
        remaining=remaining,
    )
    snapshot = service.snapshot(
        accounting_period="2026-08",
        settlement_paths=(source[0],),
        attestation_paths=(source[1],),
        closure_pack_paths=(source[2],),
        receipt_paths=(source[3],),
    )
    return service, dispute, source, snapshot


def _close(service: ProviderCreditCloseService, snapshot):
    result = service.create_close(
        snapshot,
        owner="Finance reviewer",
        statement="Reviewed provider credits agree with the verified settlement evidence.",
        ledger_export_verified=True,
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def test_phase77_settled_evidence_is_ready_for_close(tmp_path: Path) -> None:
    _service_instance, _dispute, _source_paths, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.close_gate == "allow"
    assert snapshot.settled_count == 1
    assert snapshot.unresolved_count == 0
    assert snapshot.total_applied_credit == 10.0
    assert snapshot.total_remaining_variance == 0.0
    assert snapshot.recovery_rate_percent == 100.0
    assert snapshot.blocker_count == 0


def test_phase77_unresolved_settlement_blocks_close(tmp_path: Path) -> None:
    _service_instance, _dispute, _source_paths, snapshot = _snapshot(
        tmp_path,
        outcome_status="partially_settled",
        applied=6.0,
        remaining=4.0,
    )
    assert snapshot.status == "blocked"
    assert snapshot.close_gate == "hold"
    assert snapshot.unresolved_count == 1
    assert snapshot.blocker_count >= 1


def test_phase77_tampered_source_is_rejected(tmp_path: Path) -> None:
    service, dispute, source, _snapshot_value = _snapshot(tmp_path)
    source[0].write_text("{}", encoding="utf-8")
    snapshot = service.snapshot(
        accounting_period="2026-08",
        settlement_paths=(source[0],),
        attestation_paths=(source[1],),
        closure_pack_paths=(source[2],),
        receipt_paths=(source[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.rejected_source_count == 1


def test_phase77_mixed_currency_and_invalid_period_are_blocked(tmp_path: Path) -> None:
    service, dispute = _service(tmp_path)
    first = _source(dispute, suffix="usd", currency="USD")
    second = _source(dispute, suffix="eur", currency="EUR")
    snapshot = service.snapshot(
        accounting_period="2026-13",
        settlement_paths=(first[0], second[0]),
        attestation_paths=(first[1], second[1]),
        closure_pack_paths=(first[2], second[2]),
        receipt_paths=(first[3], second[3]),
    )
    assert snapshot.status == "blocked"
    assert snapshot.blocker_count >= 2


def test_phase77_close_requires_acknowledgement_and_ledger_review(
    tmp_path: Path,
) -> None:
    service, _dispute, _source_paths, snapshot = _snapshot(tmp_path)
    blocked = service.create_close(
        snapshot,
        owner="Finance reviewer",
        statement="Ledger verification is pending.",
        ledger_export_verified=False,
        acknowledge=True,
    )
    assert isinstance(blocked, dict)
    assert blocked["status"] == "blocked"

    dry_run = service.create_close(
        snapshot,
        owner="Finance reviewer",
        statement="Reviewed settlement evidence is ready.",
        ledger_export_verified=True,
        acknowledge=False,
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"


def test_phase77_close_rejects_private_input(tmp_path: Path) -> None:
    service, _dispute, _source_paths, snapshot = _snapshot(tmp_path)
    result = service.create_close(
        snapshot,
        owner="api_key=secret",
        statement="Reviewed settlement evidence is ready.",
        ledger_export_verified=True,
        acknowledge=True,
    )
    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase77_close_creates_verifiable_audit_chain(tmp_path: Path) -> None:
    service, _dispute, _source_paths, snapshot = _snapshot(tmp_path)
    close = _close(service, snapshot)
    for path, verifier in (
        (close.snapshot_path, service.verify_snapshot),
        (close.close_path, service.verify_close),
        (close.attestation_path, service.verify_attestation),
    ):
        ok, detail = verifier(path)
        assert ok, detail
    ok, detail = service.verify_audit_pack(close.audit_pack_path, close.receipt_path)
    assert ok, detail


def test_phase77_duplicate_settlement_identifier_is_blocked(tmp_path: Path) -> None:
    service, dispute = _service(tmp_path)
    source = _source(dispute)
    snapshot = service.snapshot(
        accounting_period="2026-08",
        settlement_paths=(source[0], source[0]),
        attestation_paths=(source[1],),
        closure_pack_paths=(source[2],),
        receipt_paths=(source[3],),
    )
    assert snapshot.status == "blocked"
    assert any(gate.code == "unique_settlement_ids" and gate.status == "block" for gate in snapshot.gates)


def test_phase77_tamper_detection_covers_close_and_audit_pack(tmp_path: Path) -> None:
    service, _dispute, _source_paths, snapshot = _snapshot(tmp_path)
    close = _close(service, snapshot)

    payload = _read(close.close_path)
    assert payload is not None
    payload["total_applied_credit"] = "9.0000"
    _write(close.close_path, payload)
    ok, _detail = service.verify_close(close.close_path)
    assert not ok

    service, _dispute, _source_paths, snapshot = _snapshot(tmp_path / "fresh")
    close = _close(service, snapshot)
    with close.audit_pack_path.open("ab") as handle:
        handle.write(b"tamper")
    ok, _detail = service.verify_audit_pack(close.audit_pack_path, close.receipt_path)
    assert not ok
