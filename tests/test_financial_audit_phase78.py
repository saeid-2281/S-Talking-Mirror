from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.financial_audit_service import FinancialAuditService


NOW = datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc)


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


class _FakeBillingReconciliationService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "billing-reconciliation"
        self.results_dir = root / "results"
        self.attestations_dir = root / "attestations"
        self.dispute_packs_dir = root / "dispute-packs"
        self.receipts_dir = root / "receipts"
        for path in (
            self.results_dir,
            self.attestations_dir,
            self.dispute_packs_dir,
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
        return expected == _digest(payload), "Attestation verified."

    def verify_dispute_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        receipt = _read(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Pack missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if expected != _digest(receipt):
            return False, "Receipt changed."
        if receipt.get("pack_sha256") != _sha256(pack_path):
            return False, "Pack changed."
        return True, "Pack verified."


class _FakeProviderCreditCloseService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "provider-credit-close"
        self.snapshots_dir = root / "snapshots"
        self.closes_dir = root / "closes"
        self.attestations_dir = root / "attestations"
        self.audit_packs_dir = root / "audit-packs"
        self.receipts_dir = root / "receipts"
        for path in (
            self.snapshots_dir,
            self.closes_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def verify_close(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Close unreadable."
        expected = str(payload.pop("close_sha256", ""))
        if expected != _digest(payload):
            return False, "Close changed."
        snapshot = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot.is_file() or payload.get("snapshot_sha256") != _sha256(snapshot):
            return False, "Snapshot changed."
        return True, "Close verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = _read(path)
        if payload is None:
            return False, "Attestation unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        return expected == _digest(payload), "Attestation verified."

    def verify_audit_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        receipt = _read(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Pack missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if expected != _digest(receipt):
            return False, "Receipt changed."
        if receipt.get("pack_sha256") != _sha256(pack_path):
            return False, "Pack changed."
        return True, "Pack verified."


def _service(
    root: Path,
) -> tuple[
    FinancialAuditService,
    _FakeBillingReconciliationService,
    _FakeProviderCreditCloseService,
]:
    runtime = _runtime(root)
    billing = _FakeBillingReconciliationService(runtime)
    close = _FakeProviderCreditCloseService(runtime)
    service = FinancialAuditService(
        runtime,
        billing,  # type: ignore[arg-type]
        close,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, billing, close


def _reconciliation_source(
    billing: _FakeBillingReconciliationService,
    *,
    suffix: str = "alpha",
    invoice_total: float = 100.0,
    provider_credits: float = 0.0,
    ledger_total: float = 90.0,
) -> tuple[Path, Path, Path, Path]:
    reconciliation_id = f"billing-reconciliation-{suffix}"
    net_invoice = invoice_total - provider_credits
    variance = net_invoice - ledger_total
    result_payload: dict[str, object] = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "created_at": NOW.isoformat(),
        "outcome_status": "withheld" if abs(variance) > 0.01 else "verified",
        "provider": "Example Provider",
        "invoice_id": f"INV-{suffix}",
        "currency": "USD",
        "invoice_total_amount": f"{invoice_total:.4f}",
        "provider_credits_amount": f"{provider_credits:.4f}",
        "net_invoice_amount": f"{net_invoice:.4f}",
        "ledger_total_amount": f"{ledger_total:.4f}",
        "variance_amount": f"{variance:.4f}",
        "human_reviewed": True,
    }
    result_payload["result_sha256"] = _digest(result_payload)
    result_path = _write(
        billing.results_dir / f"{reconciliation_id}-result.json",
        result_payload,
    )

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "result_filename": result_path.name,
        "result_sha256": _sha256(result_path),
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        billing.attestations_dir / f"{reconciliation_id}-attestation.json",
        attestation_payload,
    )

    pack_path = billing.dispute_packs_dir / f"{reconciliation_id}-dispute-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("result.json", result_path.read_bytes())
        archive.writestr("attestation.json", attestation_path.read_bytes())
    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        billing.receipts_dir / f"{reconciliation_id}-receipt.json",
        receipt_payload,
    )
    return result_path, attestation_path, pack_path, receipt_path


def _close_source(
    close: _FakeProviderCreditCloseService,
    *,
    suffix: str = "alpha",
    applied_credit: float = 10.0,
    invoice_id: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    close_id = f"provider-credit-close-{suffix}"
    settlement_id = f"billing-settlement-{suffix}"
    snapshot_payload: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": f"provider-credit-close-snapshot-{suffix}",
        "accounting_period": "2026-08",
        "status": "ready",
        "sources": [
            {
                "settlement_id": settlement_id,
                "provider": "Example Provider",
                "invoice_id": invoice_id or f"INV-{suffix}",
                "currency": "USD",
                "applied_credit_amount": applied_credit,
                "remaining_variance_amount": 0.0,
            }
        ],
    }
    snapshot_payload["snapshot_sha256"] = _digest(snapshot_payload)
    snapshot_path = _write(
        close.snapshots_dir / f"{snapshot_payload['snapshot_id']}.json",
        snapshot_payload,
    )
    close_payload: dict[str, object] = {
        "schema_version": 1,
        "close_id": close_id,
        "accounting_period": "2026-08",
        "outcome_status": "closed",
        "currency": "USD",
        "total_applied_credit": f"{applied_credit:.4f}",
        "total_remaining_variance": "0.0000",
        "snapshot_filename": snapshot_path.name,
        "snapshot_sha256": _sha256(snapshot_path),
    }
    close_payload["close_sha256"] = _digest(close_payload)
    close_path = _write(close.closes_dir / f"{close_id}.json", close_payload)

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "close_id": close_id,
        "close_filename": close_path.name,
        "close_sha256": _sha256(close_path),
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        close.attestations_dir / f"{close_id}-attestation.json",
        attestation_payload,
    )
    pack_path = close.audit_packs_dir / f"{close_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("close.json", close_path.read_bytes())
        archive.writestr("attestation.json", attestation_path.read_bytes())
    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "close_id": close_id,
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        close.receipts_dir / f"{close_id}-receipt.json",
        receipt_payload,
    )
    return close_path, attestation_path, pack_path, receipt_path


def _snapshot(
    root: Path,
    *,
    invoice_total: float = 100.0,
    ledger_total: float = 90.0,
    settlement_credit: float = 10.0,
):
    service, billing, close = _service(root)
    reconciliation = _reconciliation_source(
        billing,
        invoice_total=invoice_total,
        ledger_total=ledger_total,
    )
    close_paths = _close_source(close, applied_credit=settlement_credit)
    snapshot = service.snapshot(
        accounting_period="2026-08",
        tolerance_amount=0.01,
        reconciliation_paths=(reconciliation[0],),
        reconciliation_attestation_paths=(reconciliation[1],),
        reconciliation_pack_paths=(reconciliation[2],),
        reconciliation_receipt_paths=(reconciliation[3],),
        close_paths=(close_paths[0],),
        close_attestation_paths=(close_paths[1],),
        close_pack_paths=(close_paths[2],),
        close_receipt_paths=(close_paths[3],),
    )
    return service, billing, close, reconciliation, close_paths, snapshot


def _audit(service: FinancialAuditService, snapshot):
    result = service.create_audit(
        snapshot,
        owner="Finance auditor",
        statement="Verified invoice, settlement credit and ledger integrity for the period.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def test_phase78_clean_financial_chain_is_ready(tmp_path: Path) -> None:
    _service_instance, _billing, _close, _reconciliation, _close_paths, snapshot = _snapshot(
        tmp_path
    )
    assert snapshot.status == "ready"
    assert snapshot.audit_gate == "allow"
    assert snapshot.invoice_count == 1
    assert snapshot.matched_invoice_count == 1
    assert snapshot.total_settlement_credits == 10.0
    assert snapshot.total_final_net_invoice == 90.0
    assert snapshot.total_ledger_amount == 90.0
    assert snapshot.total_residual_variance == 0.0
    assert snapshot.blocker_count == 0


def test_phase78_missing_required_settlement_blocks_audit(tmp_path: Path) -> None:
    service, billing, close = _service(tmp_path)
    reconciliation = _reconciliation_source(billing)
    snapshot = service.snapshot(
        accounting_period="2026-08",
        reconciliation_paths=(reconciliation[0],),
        reconciliation_attestation_paths=(reconciliation[1],),
        reconciliation_pack_paths=(reconciliation[2],),
        reconciliation_receipt_paths=(reconciliation[3],),
        close_paths=(),
        close_attestation_paths=(),
        close_pack_paths=(),
        close_receipt_paths=(),
    )
    assert snapshot.status == "blocked"
    assert snapshot.unmatched_invoice_count >= 1
    assert snapshot.blocker_count >= 1
    assert close.closes_dir.is_dir()


def test_phase78_duplicate_reconciliation_invoice_is_blocked(tmp_path: Path) -> None:
    service, billing, close = _service(tmp_path)
    first = _reconciliation_source(billing, suffix="a")
    second = _reconciliation_source(billing, suffix="b")
    # Force the second result to refer to the same invoice while preserving its hash.
    payload = _read(second[0])
    assert payload is not None
    payload.pop("result_sha256")
    payload["invoice_id"] = "INV-a"
    payload["result_sha256"] = _digest(payload)
    _write(second[0], payload)
    close_paths = _close_source(close, suffix="a", invoice_id="INV-a")
    snapshot = service.snapshot(
        accounting_period="2026-08",
        reconciliation_paths=(first[0], second[0]),
        reconciliation_attestation_paths=(first[1], second[1]),
        reconciliation_pack_paths=(first[2], second[2]),
        reconciliation_receipt_paths=(first[3], second[3]),
        close_paths=(close_paths[0],),
        close_attestation_paths=(close_paths[1],),
        close_pack_paths=(close_paths[2],),
        close_receipt_paths=(close_paths[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.duplicate_invoice_count >= 1


def test_phase78_residual_variance_blocks_audit(tmp_path: Path) -> None:
    _service_instance, _billing, _close, _reconciliation, _close_paths, snapshot = _snapshot(
        tmp_path,
        settlement_credit=5.0,
    )
    assert snapshot.status == "blocked"
    assert snapshot.findings[0].residual_variance_amount == 5.0
    assert snapshot.blocker_count >= 1


def test_phase78_tampered_phase77_close_is_rejected(tmp_path: Path) -> None:
    service, _billing, _close, reconciliation, close_paths, _snapshot_value = _snapshot(tmp_path)
    close_payload = _read(close_paths[0])
    assert close_payload is not None
    close_payload["total_applied_credit"] = "999.0000"
    _write(close_paths[0], close_payload)
    snapshot = service.snapshot(
        accounting_period="2026-08",
        reconciliation_paths=(reconciliation[0],),
        reconciliation_attestation_paths=(reconciliation[1],),
        reconciliation_pack_paths=(reconciliation[2],),
        reconciliation_receipt_paths=(reconciliation[3],),
        close_paths=(close_paths[0],),
        close_attestation_paths=(close_paths[1],),
        close_pack_paths=(close_paths[2],),
        close_receipt_paths=(close_paths[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.rejected_source_count >= 1


def test_phase78_create_audit_requires_explicit_acknowledgement(tmp_path: Path) -> None:
    service, _billing, _close, _reconciliation, _close_paths, snapshot = _snapshot(tmp_path)
    result = service.create_audit(
        snapshot,
        owner="Finance auditor",
        statement="Reviewed financial integrity evidence.",
        acknowledge=False,
    )
    assert isinstance(result, dict)
    assert result["status"] == "dry_run"


def test_phase78_audit_artifacts_are_verifiable(tmp_path: Path) -> None:
    service, _billing, _close, _reconciliation, _close_paths, snapshot = _snapshot(tmp_path)
    record = _audit(service, snapshot)
    ok, detail = service.verify_audit(record.audit_path)
    assert ok, detail
    ok, detail = service.verify_attestation(record.attestation_path)
    assert ok, detail
    ok, detail = service.verify_audit_pack(record.audit_pack_path, record.receipt_path)
    assert ok, detail


def test_phase78_tamper_detection_rejects_audit_pack(tmp_path: Path) -> None:
    service, _billing, _close, _reconciliation, _close_paths, snapshot = _snapshot(tmp_path)
    record = _audit(service, snapshot)
    with record.audit_pack_path.open("ab") as handle:
        handle.write(b"tamper")
    ok, _detail = service.verify_audit_pack(record.audit_pack_path, record.receipt_path)
    assert not ok


def test_phase78_private_statement_and_automation_are_blocked(tmp_path: Path) -> None:
    service, _billing, _close, _reconciliation, _close_paths, snapshot = _snapshot(tmp_path)
    blocked = service.create_audit(
        snapshot,
        owner="Finance auditor",
        statement=r"Evidence stored at C:\Users\Someone\secret.json",
        acknowledge=True,
    )
    assert isinstance(blocked, dict)
    assert blocked["status"] == "blocked"
    record = _audit(service, snapshot)
    payload = _read(record.audit_path)
    assert payload is not None
    for key in (
        "automatic_ledger_change",
        "automatic_invoice_change",
        "automatic_payment_action",
        "automatic_credit_action",
        "automatic_provider_action",
        "automatic_accounting_export",
        "automatic_evidence_upload",
    ):
        assert payload[key] is False
