from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.generation_reliability import (
    GenerationProviderReliability,
    GenerationReliabilityDashboard,
    GenerationReliabilitySnapshot,
    GenerationSloPolicy,
)
from app.services.provider_governance_service import ProviderGovernanceService

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _digest(payload: dict[str, object]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class _FakeReliabilityService:
    def __init__(self, metrics: tuple[GenerationProviderReliability, ...]) -> None:
        self.metrics = metrics

    def dashboard(self, *, project_id: int | None = None):
        snapshot = GenerationReliabilitySnapshot(
            snapshot_id="reliability-phase79",
            project_id=project_id,
            period_start="2026-07-08T12:00:00+00:00",
            period_end=NOW.isoformat(),
            created_at=NOW.isoformat(),
            state="healthy",
            provider_metrics=self.metrics,
        )
        return GenerationReliabilityDashboard(
            policy=GenerationSloPolicy(project_id=project_id),
            snapshot=snapshot,
        )


class _FakeFinancialAuditService:
    def __init__(self, root: Path) -> None:
        self.root = root / "financial-audit"
        self.snapshots_dir = self.root / "snapshots"
        self.audits_dir = self.root / "audits"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        for path in (
            self.snapshots_dir,
            self.audits_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "snapshot missing"
        expected = str(payload.pop("snapshot_sha256", ""))
        return (expected == _digest(payload), "snapshot checked")

    def verify_audit(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "audit missing"
        expected = str(payload.pop("audit_sha256", ""))
        if expected != _digest(payload):
            return False, "audit hash changed"
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or _sha256(snapshot_path) != payload.get("snapshot_sha256"):
            return False, "snapshot link changed"
        return self.verify_snapshot(snapshot_path)

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "attestation missing"
        expected = str(payload.pop("attestation_sha256", ""))
        if expected != _digest(payload):
            return False, "attestation hash changed"
        audit_path = self.audits_dir / str(payload.get("audit_filename") or "")
        if not audit_path.is_file() or _sha256(audit_path) != payload.get("audit_sha256"):
            return False, "audit link changed"
        return True, "attestation checked"

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        receipt = self._read(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "pack missing"
        expected = str(receipt.pop("receipt_sha256", ""))
        if expected != _digest(receipt):
            return False, "receipt changed"
        if receipt.get("pack_sha256") != _sha256(pack_path):
            return False, "pack changed"
        return True, "pack checked"


def _runtime(root: Path) -> RuntimeConfig:
    return RuntimeConfig.from_root(root)


def _metrics(
    provider: str = "Example Provider",
    *,
    sessions: int = 12,
    success: float = 99.8,
    failure: float = 0.2,
    retry: float = 1.0,
    health: float = 96.0,
) -> tuple[GenerationProviderReliability, ...]:
    total = 1000
    completed = round(total * success / 100.0)
    failed = max(0, total - completed)
    retries = round(total * retry / 100.0)
    return (
        GenerationProviderReliability(
            provider=provider,
            session_count=sessions,
            total_jobs=total,
            completed_jobs=completed,
            failed_jobs=failed,
            retry_events=retries,
            job_success_rate=success,
            failure_rate=failure,
            retry_rate=retry,
            average_files_per_minute=22.5,
            average_health_score=health,
        ),
    )


def _financial_evidence(
    financial: _FakeFinancialAuditService,
    *,
    suffix: str = "alpha",
    provider: str = "Example Provider",
    invoice_id: str | None = None,
    invoice_total: float = 100.0,
    settlement_credit: float = 0.0,
    residual: float = 0.0,
) -> tuple[Path, Path, Path, Path]:
    audit_id = f"financial-audit-{suffix}"
    snapshot_id = f"financial-audit-snapshot-{suffix}"
    invoice_id = invoice_id or f"INV-{suffix}"
    snapshot_payload: dict[str, object] = {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "status": "ready",
        "findings": [
            {
                "provider": provider,
                "invoice_id": invoice_id,
                "invoice_total_amount": invoice_total,
                "settlement_credit_amount": settlement_credit,
                "residual_variance_amount": residual,
            }
        ],
    }
    snapshot_payload["snapshot_sha256"] = _digest(snapshot_payload)
    snapshot_path = _write(
        financial.snapshots_dir / f"{snapshot_id}.json", snapshot_payload
    )

    audit_payload: dict[str, object] = {
        "schema_version": 1,
        "audit_id": audit_id,
        "accounting_period": "2026-08",
        "outcome_status": "verified",
        "snapshot_filename": snapshot_path.name,
        "snapshot_sha256": _sha256(snapshot_path),
        "human_reviewed": True,
    }
    audit_payload["audit_sha256"] = _digest(audit_payload)
    audit_path = _write(financial.audits_dir / f"{audit_id}.json", audit_payload)

    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "audit_id": audit_id,
        "audit_filename": audit_path.name,
        "audit_sha256": _sha256(audit_path),
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        financial.attestations_dir / f"{audit_id}-attestation.json",
        attestation_payload,
    )

    pack_path = financial.audit_packs_dir / f"{audit_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("audit.json", audit_path.read_bytes())
        archive.writestr("attestation.json", attestation_path.read_bytes())
    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "audit_id": audit_id,
        "pack_filename": pack_path.name,
        "pack_sha256": _sha256(pack_path),
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        financial.receipts_dir / f"{audit_id}-receipt.json", receipt_payload
    )
    return audit_path, attestation_path, pack_path, receipt_path


def _service(
    root: Path,
    metrics: tuple[GenerationProviderReliability, ...] | None = None,
):
    runtime = _runtime(root)
    financial = _FakeFinancialAuditService(root)
    reliability = _FakeReliabilityService(metrics if metrics is not None else _metrics())
    service = ProviderGovernanceService(
        runtime,
        reliability,  # type: ignore[arg-type]
        financial,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, financial


def _snapshot(root: Path, **evidence_kwargs):
    service, financial = _service(root)
    evidence = _financial_evidence(financial, **evidence_kwargs)
    snapshot = service.snapshot(
        financial_audit_paths=(evidence[0],),
        financial_attestation_paths=(evidence[1],),
        financial_pack_paths=(evidence[2],),
        financial_receipt_paths=(evidence[3],),
    )
    return service, financial, evidence, snapshot


def test_phase79_clean_provider_is_preferred(tmp_path: Path) -> None:
    _service_instance, _financial, _evidence, snapshot = _snapshot(tmp_path)
    assert snapshot.status == "ready"
    assert snapshot.governance_gate == "allow"
    assert snapshot.provider_count == 1
    scorecard = snapshot.scorecards[0]
    assert scorecard.recommended_governance == "preferred"
    assert scorecard.risk_level == "low"
    assert scorecard.evidence_status == "complete"
    assert scorecard.overall_score >= 90.0


def test_phase79_limited_reliability_caps_provider_at_watch(tmp_path: Path) -> None:
    service, financial = _service(tmp_path, _metrics(sessions=1))
    evidence = _financial_evidence(financial)
    snapshot = service.snapshot(
        minimum_sessions=3,
        financial_audit_paths=(evidence[0],),
        financial_attestation_paths=(evidence[1],),
        financial_pack_paths=(evidence[2],),
        financial_receipt_paths=(evidence[3],),
    )
    assert snapshot.scorecards[0].recommended_governance == "watch"
    assert snapshot.status == "ready_with_warnings"


def test_phase79_billing_adjustment_reduces_governance_score(tmp_path: Path) -> None:
    _service_instance, _financial, _evidence, snapshot = _snapshot(
        tmp_path, invoice_total=100.0, settlement_credit=20.0
    )
    scorecard = snapshot.scorecards[0]
    assert scorecard.billing_adjustment_rate == 20.0
    assert scorecard.billing_accuracy_score == 80.0
    assert scorecard.recommended_governance != "preferred"


def test_phase79_missing_financial_evidence_requires_watch(tmp_path: Path) -> None:
    service, _financial = _service(tmp_path)
    snapshot = service.snapshot(
        financial_audit_paths=(),
        financial_attestation_paths=(),
        financial_pack_paths=(),
        financial_receipt_paths=(),
    )
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.scorecards[0].recommended_governance == "watch"
    assert snapshot.warning_count >= 1


def test_phase79_tampered_selected_financial_audit_blocks_snapshot(tmp_path: Path) -> None:
    service, financial = _service(tmp_path)
    evidence = _financial_evidence(financial)
    payload = json.loads(evidence[0].read_text(encoding="utf-8"))
    payload["accounting_period"] = "2026-07"
    evidence[0].write_text(json.dumps(payload), encoding="utf-8")
    snapshot = service.snapshot(
        financial_audit_paths=(evidence[0],),
        financial_attestation_paths=(evidence[1],),
        financial_pack_paths=(evidence[2],),
        financial_receipt_paths=(evidence[3],),
    )
    assert snapshot.status == "blocked"
    assert snapshot.rejected_financial_audit_count == 1
    assert snapshot.blocker_count >= 1


def test_phase79_overlapping_invoice_evidence_is_blocked(tmp_path: Path) -> None:
    service, financial = _service(tmp_path)
    first = _financial_evidence(financial, suffix="a", invoice_id="INV-ONE")
    second = _financial_evidence(financial, suffix="b", invoice_id="INV-ONE")
    snapshot = service.snapshot(
        financial_audit_paths=(first[0], second[0]),
        financial_attestation_paths=(first[1], second[1]),
        financial_pack_paths=(first[2], second[2]),
        financial_receipt_paths=(first[3], second[3]),
    )
    assert snapshot.status == "blocked"
    gate = next(gate for gate in snapshot.gates if gate.code == "financial_overlap")
    assert gate.status == "block"


def test_phase79_governance_record_is_verifiable_and_non_mutating(tmp_path: Path) -> None:
    service, _financial, _evidence, snapshot = _snapshot(tmp_path)
    dry_run = service.create_governance(
        snapshot,
        owner="Operations reviewer",
        statement="Reviewed provider reliability, billing accuracy and governance scorecards.",
        acknowledge=False,
    )
    assert isinstance(dry_run, dict)
    assert dry_run["status"] == "dry_run"

    record = service.create_governance(
        snapshot,
        owner="Operations reviewer",
        statement="Reviewed provider reliability, billing accuracy and governance scorecards.",
        acknowledge=True,
    )
    assert not isinstance(record, dict)
    assert service.verify_governance(record.governance_path)[0]
    assert service.verify_attestation(record.attestation_path)[0]
    assert service.verify_audit_pack(record.audit_pack_path, record.receipt_path)[0]
    payload = json.loads(record.governance_path.read_text(encoding="utf-8"))
    assert payload["routing_change_applied"] is False
    assert payload["automatic_failover"] is False
    assert payload["external_upload"] is False


def test_phase79_more_permissive_human_decision_is_rejected(tmp_path: Path) -> None:
    service, financial = _service(tmp_path, _metrics(sessions=1))
    evidence = _financial_evidence(financial)
    snapshot = service.snapshot(
        minimum_sessions=3,
        financial_audit_paths=(evidence[0],),
        financial_attestation_paths=(evidence[1],),
        financial_pack_paths=(evidence[2],),
        financial_receipt_paths=(evidence[3],),
    )
    result = service.create_governance(
        snapshot,
        owner="Operations reviewer",
        statement="Reviewed evidence.",
        decisions={"Example Provider": "preferred"},
        acknowledge=True,
    )
    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase79_tamper_and_private_material_are_rejected(tmp_path: Path) -> None:
    service, _financial, _evidence, snapshot = _snapshot(tmp_path)
    private_result = service.create_governance(
        snapshot,
        owner=r"C:\\Users\\Saeid\\provider-review.txt",
        statement="Reviewed evidence.",
        acknowledge=True,
    )
    assert isinstance(private_result, dict)
    assert private_result["status"] == "blocked"

    record = service.create_governance(
        snapshot,
        owner="Operations reviewer",
        statement="Reviewed evidence.",
        acknowledge=True,
    )
    assert not isinstance(record, dict)
    payload = json.loads(record.governance_path.read_text(encoding="utf-8"))
    payload["owner"] = "Changed reviewer"
    record.governance_path.write_text(json.dumps(payload), encoding="utf-8")
    ok, _detail = service.verify_governance(record.governance_path)
    assert not ok

    with record.audit_pack_path.open("ab") as handle:
        handle.write(b"tamper")
    pack_ok, _detail = service.verify_audit_pack(
        record.audit_pack_path, record.receipt_path
    )
    assert not pack_ok
