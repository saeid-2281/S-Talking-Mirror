from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.billing_dispute_resolution_service import (
    BillingDisputeResolutionService,
)


NOW = datetime(2026, 8, 7, 1, 0, tzinfo=timezone.utc)


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
        if expected != _digest(payload):
            return False, "Attestation hash changed."
        result_path = self.results_dir / str(payload.get("result_filename") or "")
        if not result_path.is_file() or payload.get("result_sha256") != _sha256(
            result_path
        ):
            return False, "Linked result changed."
        return True, "Attestation verified."

    def verify_dispute_pack(
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
) -> tuple[BillingDisputeResolutionService, _FakeBillingReconciliationService]:
    runtime = _runtime(root)
    billing = _FakeBillingReconciliationService(runtime)
    service = BillingDisputeResolutionService(
        runtime,
        billing,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, billing


def _source(
    billing: _FakeBillingReconciliationService,
    *,
    suffix: str = "alpha",
    outcome_status: str = "withheld",
    variance_amount: float = 10.0,
    currency: str = "USD",
) -> tuple[Path, Path, Path, Path]:
    reconciliation_id = f"billing-reconciliation-{suffix}"
    result_payload: dict[str, object] = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "created_at": NOW.isoformat(),
        "outcome_status": outcome_status,
        "decision": (
            "prepare_manual_billing_dispute"
            if outcome_status == "withheld"
            else "approve_billing_reconciliation"
        ),
        "provider": "Example Provider",
        "invoice_id": f"INV-{suffix}",
        "currency": currency,
        "variance_amount": f"{variance_amount:.4f}",
        "duplicate_charge_count": 1 if outcome_status == "withheld" else 0,
        "missing_invoice_request_count": 0,
        "unexpected_invoice_request_count": 0,
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
        "created_at": NOW.isoformat(),
        "status": outcome_status,
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
        archive.writestr("billing/result.json", result_path.read_bytes())
        archive.writestr("billing/attestation.json", attestation_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "reconciliation_id": reconciliation_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        billing.receipts_dir / f"{reconciliation_id}-receipt.json",
        receipt_payload,
    )
    return result_path, attestation_path, pack_path, receipt_path


def _snapshot(
    root: Path,
    *,
    outcome_status: str = "withheld",
    variance_amount: float = 10.0,
):
    service, billing = _service(root)
    source = _source(
        billing,
        outcome_status=outcome_status,
        variance_amount=variance_amount,
    )
    snapshot = service.snapshot(
        result_paths=(source[0],),
        attestation_paths=(source[1],),
        dispute_pack_paths=(source[2],),
        receipt_paths=(source[3],),
    )
    return service, source, snapshot


def _case(service, source, snapshot):
    result = service.create_dispute_case(
        snapshot,
        result_path=source[0],
        requested_credit_amount=10.0,
        owner="Billing owner",
        summary="Provider invoice variance requires manual review.",
        internal_reference="BILL-76-001",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def _settlement(service, case, *, applied: float = 10.0, remaining: float = 0.0):
    result = service.record_settlement(
        case_path=case.case_path,
        provider_response_reference="RESP-2026-100",
        credit_memo_reference="CM-2026-100" if applied else "",
        approved_credit_amount=applied,
        applied_credit_amount=applied,
        remaining_variance_amount=remaining,
        owner="Billing reviewer",
        statement="Provider response and reviewed ledger entry were reconciled.",
        provider_response_verified=True,
        ledger_entry_verified=True,
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def test_phase76_withheld_reconciliation_is_ready_for_dispute(tmp_path: Path) -> None:
    _service_instance, _source_paths, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.release_gate == "manual_review"
    assert snapshot.dispute_required_count == 1
    assert snapshot.total_claim_amount == 10.0
    assert snapshot.blocker_count == 0


def test_phase76_verified_reconciliation_requires_no_dispute(tmp_path: Path) -> None:
    _service_instance, _source_paths, snapshot = _snapshot(
        tmp_path, outcome_status="verified", variance_amount=0.0
    )
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.release_gate == "allow"
    assert snapshot.no_dispute_required_count == 1
    assert snapshot.dispute_required_count == 0


def test_phase76_tampered_or_incomplete_source_is_blocked(tmp_path: Path) -> None:
    service, billing = _service(tmp_path)
    source = _source(billing)
    source[0].write_text("{}", encoding="utf-8")
    snapshot = service.snapshot(
        result_paths=(source[0],),
        attestation_paths=(source[1],),
        dispute_pack_paths=(source[2],),
        receipt_paths=(source[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.blocker_count >= 1


def test_phase76_case_requires_acknowledgement_and_withheld_source(
    tmp_path: Path,
) -> None:
    service, source, snapshot = _snapshot(tmp_path)
    dry_run = service.create_dispute_case(
        snapshot,
        result_path=source[0],
        requested_credit_amount=10.0,
        owner="Billing owner",
        summary="Manual provider dispute is required.",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"
    verified_service, verified_source, verified_snapshot = _snapshot(
        tmp_path / "verified", outcome_status="verified", variance_amount=0.0
    )
    blocked = verified_service.create_dispute_case(
        verified_snapshot,
        result_path=verified_source[0],
        requested_credit_amount=1.0,
        owner="Billing owner",
        summary="No dispute should be opened.",
        acknowledge=True,
    )
    assert isinstance(blocked, dict)
    assert blocked["status"] == "blocked"


def test_phase76_case_rejects_excess_claim_and_private_input(tmp_path: Path) -> None:
    service, source, snapshot = _snapshot(tmp_path)
    excessive = service.create_dispute_case(
        snapshot,
        result_path=source[0],
        requested_credit_amount=11.0,
        owner="Billing owner",
        summary="Claim exceeds evidence.",
        acknowledge=True,
    )
    assert isinstance(excessive, dict)
    private = service.create_dispute_case(
        snapshot,
        result_path=source[0],
        requested_credit_amount=10.0,
        owner="api_key=secret",
        summary="Manual review.",
        acknowledge=True,
    )
    assert isinstance(private, dict)
    assert private["status"] == "blocked"


def test_phase76_dispute_case_creates_verifiable_evidence(tmp_path: Path) -> None:
    service, source, snapshot = _snapshot(tmp_path)
    case = _case(service, source, snapshot)
    ok, detail = service.verify_case(case.case_path)
    assert ok, detail
    snapshot_ok, snapshot_detail = service.verify_snapshot(case.snapshot_path)
    assert snapshot_ok, snapshot_detail


def test_phase76_full_settlement_creates_verifiable_closure_chain(
    tmp_path: Path,
) -> None:
    service, source, snapshot = _snapshot(tmp_path)
    case = _case(service, source, snapshot)
    settlement = _settlement(service, case)
    assert settlement.outcome_status == "settled"
    for path, verifier in (
        (settlement.settlement_path, service.verify_settlement),
        (settlement.attestation_path, service.verify_attestation),
    ):
        ok, detail = verifier(path)
        assert ok, detail
    ok, detail = service.verify_closure_pack(
        settlement.closure_pack_path, settlement.receipt_path
    )
    assert ok, detail


def test_phase76_partial_or_unverified_settlement_cannot_close_case(
    tmp_path: Path,
) -> None:
    service, source, snapshot = _snapshot(tmp_path)
    case = _case(service, source, snapshot)
    partial = _settlement(service, case, applied=6.0, remaining=4.0)
    assert partial.outcome_status == "partially_settled"
    withheld = service.record_settlement(
        case_path=case.case_path,
        provider_response_reference="RESP-2",
        credit_memo_reference="CM-2",
        approved_credit_amount=10.0,
        applied_credit_amount=10.0,
        remaining_variance_amount=0.0,
        owner="Reviewer",
        statement="Ledger verification is pending.",
        provider_response_verified=True,
        ledger_entry_verified=False,
        acknowledge=True,
    )
    assert not isinstance(withheld, dict)
    assert withheld.outcome_status == "withheld"


def test_phase76_tamper_detection_covers_case_settlement_and_pack(
    tmp_path: Path,
) -> None:
    service, source, snapshot = _snapshot(tmp_path)
    case = _case(service, source, snapshot)
    settlement = _settlement(service, case)

    case_payload = _read(case.case_path)
    assert case_payload is not None
    case_payload["requested_credit_amount"] = "9.0000"
    _write(case.case_path, case_payload)
    ok, _detail = service.verify_case(case.case_path)
    assert not ok

    service, source, snapshot = _snapshot(tmp_path / "fresh")
    case = _case(service, source, snapshot)
    settlement = _settlement(service, case)
    settlement_payload = _read(settlement.settlement_path)
    assert settlement_payload is not None
    settlement_payload["applied_credit_amount"] = "9.0000"
    _write(settlement.settlement_path, settlement_payload)
    ok, _detail = service.verify_settlement(settlement.settlement_path)
    assert not ok

    with settlement.closure_pack_path.open("ab") as handle:
        handle.write(b"tamper")
    ok, _detail = service.verify_closure_pack(
        settlement.closure_pack_path, settlement.receipt_path
    )
    assert not ok
