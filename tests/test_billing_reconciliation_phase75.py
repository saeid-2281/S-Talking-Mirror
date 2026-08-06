from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.billing_reconciliation_service import BillingReconciliationService


NOW = datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)


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


class _FakeRecoveryReplayService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        root = runtime.artifacts_dir / "recovery-replay"
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
        if not result_path.is_file() or payload.get("result_sha256") != _sha256(
            result_path
        ):
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


def _service(root: Path) -> tuple[BillingReconciliationService, _FakeRecoveryReplayService]:
    runtime = _runtime(root)
    replay = _FakeRecoveryReplayService(runtime)
    service = BillingReconciliationService(
        runtime,
        replay,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, replay


def _invoice_csv(path: Path, *, duplicate_request: bool = False) -> Path:
    request_3 = "req-2" if duplicate_request else "req-3"
    path.write_text(
        "line_id,request_id,usage_type,quantity,amount\n"
        "line-1,req-1,tts,1,2.50\n"
        "line-2,req-2,tts,1,3.00\n"
        f"line-3,{request_3},tts,1,4.50\n",
        encoding="utf-8",
    )
    return path


def _invoice(service: BillingReconciliationService, csv_path: Path):
    result = service.import_invoice_csv(
        csv_path,
        invoice_id="INV-2026-08",
        provider="Example Provider",
        currency="USD",
        billing_period_start="2026-08-01",
        billing_period_end="2026-08-31",
        owner="Billing reviewer",
        notes="Reviewed provider statement totals.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    return result


def _replay_source(
    service: _FakeRecoveryReplayService,
    *,
    suffix: str = "alpha",
    outcome_status: str = "verified",
    attempted_jobs: int = 3,
) -> tuple[Path, Path, Path, Path]:
    replay_id = f"recovery-replay-{suffix}"
    result_payload: dict[str, object] = {
        "schema_version": 1,
        "replay_id": replay_id,
        "created_at": NOW.isoformat(),
        "outcome_status": outcome_status,
        "attempted_jobs": attempted_jobs,
        "completed_jobs": attempted_jobs,
        "duplicate_api_requests": 0,
        "duplicate_outputs": 0,
        "human_reviewed": True,
    }
    result_payload["result_sha256"] = _digest(result_payload)
    result_path = _write(
        service.results_dir / f"{replay_id}-result.json", result_payload
    )

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "replay_id": replay_id,
        "created_at": NOW.isoformat(),
        "status": outcome_status,
        "result_filename": result_path.name,
        "result_sha256": _sha256(result_path),
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        service.attestations_dir / f"{replay_id}-attestation.json",
        attestation_payload,
    )

    pack_path = service.audit_packs_dir / f"{replay_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("recovery/result.json", result_path.read_bytes())
        archive.writestr("recovery/attestation.json", attestation_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "replay_id": replay_id,
        "created_at": NOW.isoformat(),
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        service.receipts_dir / f"{replay_id}-receipt.json", receipt_payload
    )
    return result_path, attestation_path, pack_path, receipt_path


def _snapshot(
    root: Path,
    *,
    duplicate_request: bool = False,
    replay_status: str = "verified",
    attempted_jobs: int = 3,
):
    service, replay = _service(root)
    invoice = _invoice(
        service,
        _invoice_csv(root / "invoice.csv", duplicate_request=duplicate_request),
    )
    source = _replay_source(
        replay,
        outcome_status=replay_status,
        attempted_jobs=attempted_jobs,
    )
    snapshot = service.snapshot(
        invoice_paths=(invoice.invoice_path,),
        replay_result_paths=(source[0],),
        replay_attestation_paths=(source[1],),
        replay_pack_paths=(source[2],),
        replay_receipt_paths=(source[3],),
    )
    return service, invoice, source, snapshot


def _successful_result(service, invoice, snapshot):
    return service.create_reconciliation_result(
        snapshot,
        invoice_path=invoice.invoice_path,
        ledger_total_amount=10.0,
        provider_credits_amount=0.0,
        matched_request_count=3,
        missing_invoice_request_count=0,
        unexpected_invoice_request_count=0,
        duplicate_charge_count=0,
        max_variance_percent=1.0,
        max_duplicate_charges=0,
        max_unmatched_requests=0,
        provider_statement_verified=True,
        owner="Billing reviewer",
        statement="The normalized provider invoice matches verified usage evidence.",
        acknowledge=True,
    )


def test_phase75_invoice_import_requires_acknowledgement_and_is_verifiable(
    tmp_path: Path,
) -> None:
    service, _replay = _service(tmp_path)
    csv_path = _invoice_csv(tmp_path / "invoice.csv")
    dry_run = service.import_invoice_csv(
        csv_path,
        invoice_id="INV-1",
        provider="Provider",
        currency="USD",
        billing_period_start="2026-08-01",
        billing_period_end="2026-08-31",
        owner="Reviewer",
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"
    invoice = _invoice(service, csv_path)
    ok, detail = service.verify_invoice(invoice.invoice_path)
    assert ok, detail


def test_phase75_invoice_import_rejects_invalid_or_private_input(tmp_path: Path) -> None:
    service, _replay = _service(tmp_path)
    invalid_csv = tmp_path / "invalid.csv"
    invalid_csv.write_text("line_id,amount\nline-1,2.00\n", encoding="utf-8")
    invalid = service.import_invoice_csv(
        invalid_csv,
        invoice_id="INV-1",
        provider="Provider",
        currency="USD",
        billing_period_start="2026-08-01",
        billing_period_end="2026-08-31",
        owner="Reviewer",
        acknowledge=True,
    )
    assert isinstance(invalid, dict)
    assert invalid["status"] == "blocked"
    private = service.import_invoice_csv(
        _invoice_csv(tmp_path / "private.csv"),
        invoice_id="INV-1",
        provider="api_key=secret",
        currency="USD",
        billing_period_start="2026-08-01",
        billing_period_end="2026-08-31",
        owner="Reviewer",
        acknowledge=True,
    )
    assert isinstance(private, dict)
    assert private["status"] == "blocked"


def test_phase75_verified_invoice_and_replay_are_ready(tmp_path: Path) -> None:
    _service_instance, _invoice_source, _source, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.release_gate == "allow"
    assert snapshot.expected_request_count == 3
    assert snapshot.invoice_request_count == 3
    assert snapshot.blocker_count == 0


def test_phase75_duplicate_or_withheld_sources_require_review_or_block(
    tmp_path: Path,
) -> None:
    _service_instance, _invoice_source, _source, warning = _snapshot(
        tmp_path / "warning",
        duplicate_request=True,
        attempted_jobs=2,
    )
    assert warning.status == "ready_with_warnings"
    assert warning.warning_count >= 1
    _service_instance, _invoice_source, _source, blocked = _snapshot(
        tmp_path / "blocked",
        replay_status="withheld",
    )
    assert blocked.status == "blocked"
    assert blocked.blocker_count >= 1


def test_phase75_successful_reconciliation_creates_verifiable_chain(
    tmp_path: Path,
) -> None:
    service, invoice, _source, snapshot = _snapshot(tmp_path)
    result = _successful_result(service, invoice, snapshot)
    assert not isinstance(result, dict)
    assert result.outcome_status == "verified"
    for path, verifier in (
        (result.result_path, service.verify_result),
        (result.attestation_path, service.verify_attestation),
    ):
        ok, detail = verifier(path)
        assert ok, detail
    ok, detail = service.verify_dispute_pack(
        result.dispute_pack_path, result.receipt_path
    )
    assert ok, detail


def test_phase75_threshold_failure_is_preserved_as_withheld(tmp_path: Path) -> None:
    service, invoice, _source, snapshot = _snapshot(tmp_path)
    result = service.create_reconciliation_result(
        snapshot,
        invoice_path=invoice.invoice_path,
        ledger_total_amount=8.0,
        provider_credits_amount=0.0,
        matched_request_count=2,
        missing_invoice_request_count=1,
        unexpected_invoice_request_count=1,
        duplicate_charge_count=1,
        max_variance_percent=1.0,
        max_duplicate_charges=0,
        max_unmatched_requests=0,
        provider_statement_verified=False,
        owner="Reviewer",
        statement="The provider statement requires manual dispute review.",
        acknowledge=True,
    )
    assert not isinstance(result, dict)
    assert result.outcome_status == "withheld"
    ok, detail = service.verify_result(result.result_path)
    assert ok, detail


def test_phase75_inconsistent_request_classification_is_blocked(tmp_path: Path) -> None:
    service, invoice, _source, snapshot = _snapshot(tmp_path)
    result = service.create_reconciliation_result(
        snapshot,
        invoice_path=invoice.invoice_path,
        ledger_total_amount=10.0,
        provider_credits_amount=0.0,
        matched_request_count=2,
        missing_invoice_request_count=0,
        unexpected_invoice_request_count=0,
        duplicate_charge_count=0,
        max_variance_percent=1.0,
        max_duplicate_charges=0,
        max_unmatched_requests=0,
        provider_statement_verified=True,
        owner="Reviewer",
        statement="Invalid request classification.",
        acknowledge=True,
    )
    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase75_tampering_is_detected(tmp_path: Path) -> None:
    service, invoice, _source, snapshot = _snapshot(tmp_path)
    result = _successful_result(service, invoice, snapshot)
    assert not isinstance(result, dict)
    payload = _read(result.result_path)
    assert payload is not None
    payload["variance_percent"] = "99.0000"
    _write(result.result_path, payload)
    ok, detail = service.verify_result(result.result_path)
    assert not ok
    assert "SHA-256" in detail
    ok, _detail = service.verify_attestation(result.attestation_path)
    assert not ok


def test_phase75_pack_is_safe_and_application_is_wired(tmp_path: Path) -> None:
    service, invoice, _source, snapshot = _snapshot(tmp_path)
    result = _successful_result(service, invoice, snapshot)
    assert not isinstance(result, dict)
    with zipfile.ZipFile(result.dispute_pack_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        names = archive.namelist()
    assert "billing/invoice-record.json" in names
    assert all("invoice.csv" not in name for name in names)
    for key, value in service._safety_contract().items():
        assert manifest[key] is value is False

    result.dispute_pack_path.write_bytes(result.dispute_pack_path.read_bytes() + b"tamper")
    ok, detail = service.verify_dispute_pack(
        result.dispute_pack_path, result.receipt_path
    )
    assert not ok
    assert "SHA-256" in detail or "size" in detail

    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app/gui/dialogs/billing_reconciliation_dialog.py").read_text(
        encoding="utf-8"
    )
    container = (root / "app/container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app/bootstrap.py").read_text(encoding="utf-8")
    main = (root / "app/gui/main.py").read_text(encoding="utf-8")
    frozen = (root / "app/frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts/billing-reconciliation.ps1").read_text(
        encoding="utf-8"
    )
    documentation = (root / "docs/BILLING_RECONCILIATION_PHASE75.md").read_text(
        encoding="utf-8"
    )
    assert "class BillingReconciliationDialog" in dialog
    assert "billing_reconciliation_service" in container
    assert "billing_reconciliation_service" in bootstrap
    assert "Provider Billing Reconciliation & Dispute Readiness" in main
    assert "_handle_billing_reconciliation_command" in frozen
    assert "--billing-reconciliation-snapshot" in script
    assert "never requests a refund" in documentation
