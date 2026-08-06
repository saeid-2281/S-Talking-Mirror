from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from app.config.runtime import RuntimeConfig
from app.models.reliability_assurance_renewal import ReliabilityAssuranceRenewalRecord
from app.services.reliability_assurance_renewal_service import (
    ReliabilityAssuranceRenewalService,
)


NOW = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)


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


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class _FakeAssuranceService:
    ASSURANCE_DECISIONS = (
        "assure",
        "assure_with_exceptions",
        "withhold_assurance",
    )

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.root = runtime.artifacts_dir / "reliability-assurance"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        for path in (self.attestations_dir, self.audit_packs_dir, self.receipts_dir):
            path.mkdir(parents=True, exist_ok=True)

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "Assurance attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if expected != _digest(payload):
            return False, "Assurance attestation SHA-256 does not match."
        if payload.get("status") != "verified":
            return False, "Assurance attestation is not verified."
        if payload.get("human_assurance_completed") is not True:
            return False, "Assurance attestation lacks human assurance."
        if str(payload.get("decision") or "") not in self.ASSURANCE_DECISIONS:
            return False, "Assurance decision is invalid."
        return True, "Assurance attestation is intact."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        receipt = self._read(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Assurance pack or receipt is missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if expected != _digest(receipt):
            return False, "Assurance receipt SHA-256 does not match."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Assurance pack filename changed."
        if int(receipt.get("pack_size_bytes") or -1) != pack_path.stat().st_size:
            return False, "Assurance pack size changed."
        if receipt.get("pack_sha256") != _sha256(pack_path):
            return False, "Assurance pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path) as archive:
                if "assurance/attestation.json" not in archive.namelist():
                    return False, "Assurance pack is incomplete."
        except zipfile.BadZipFile:
            return False, "Assurance pack is unreadable."
        return True, "Assurance pack is intact."

    @staticmethod
    def _read(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def _source(
    predecessor: _FakeAssuranceService,
    *,
    suffix: str = "alpha",
    decision: str = "assure",
    age_days: int = 10,
    open_exceptions: int = 0,
    next_review_date: str = "",
) -> tuple[Path, Path, Path]:
    assurance_id = f"assurance-{suffix}"
    created_at = (NOW - timedelta(days=age_days)).isoformat()
    attestation_payload: dict[str, object] = {
        "schema_version": 1,
        "assurance_id": assurance_id,
        "snapshot_id": f"snapshot-{suffix}",
        "created_at": created_at,
        "version": "1.0.0",
        "channel": "stable",
        "status": "verified",
        "decision": decision,
        "owner": "Reliability lead",
        "statement": "Human verified assurance evidence for lifecycle renewal governance.",
        "exception_owner": "Risk owner" if open_exceptions else "",
        "next_review_date": next_review_date,
        "assurance_window_days": 90,
        "metrics": {
            "verified_pair_count": 1,
            "close_effective_count": 1,
            "monitoring_count": 0,
            "escalation_count": 0,
            "accepted_risk_count": 0,
            "open_exception_count": open_exceptions,
            "high_exception_count": open_exceptions,
        },
        "sources": [{"review_id": f"review-{suffix}"}],
        "human_assurance_completed": True,
        "human_exception_ownership": bool(open_exceptions),
        "external_ticket_updated": False,
        "schedule_updated": False,
        "risk_register_updated": False,
        "automatic_risk_acceptance": False,
        "automatic_ticket_creation": False,
        "automatic_scheduling": False,
        "automatic_upload": False,
        "automatic_publish": False,
        "automatic_patch": False,
        "automatic_deploy": False,
        "automatic_rollback": False,
        "automatic_restart": False,
        "private_data_included": False,
    }
    attestation_payload["attestation_sha256"] = _digest(attestation_payload)
    attestation_path = _write(
        predecessor.attestations_dir / f"{assurance_id}.json",
        attestation_payload,
    )

    pack_path = predecessor.audit_packs_dir / f"{assurance_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("assurance/attestation.json", attestation_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "assurance_id": assurance_id,
        "created_at": created_at,
        "version": "1.0.0",
        "channel": "stable",
        "pack_filename": pack_path.name,
        "pack_size_bytes": pack_path.stat().st_size,
        "pack_sha256": _sha256(pack_path),
        "entry_count": 1,
        "automatic_upload": False,
        "automatic_publish": False,
        "private_data_included": False,
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        predecessor.receipts_dir / f"{assurance_id}-receipt.json",
        receipt_payload,
    )
    return attestation_path, pack_path, receipt_path


def _service(
    root: Path,
) -> tuple[ReliabilityAssuranceRenewalService, _FakeAssuranceService]:
    runtime = _runtime(root)
    predecessor = _FakeAssuranceService(runtime)
    service = ReliabilityAssuranceRenewalService(
        runtime,
        predecessor,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, predecessor


def test_phase69_current_assurance_is_ready_without_follow_up(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    attestation, pack, receipt = _source(predecessor)

    snapshot = service.snapshot(
        attestation_paths=(attestation,),
        audit_pack_paths=(pack,),
        receipt_paths=(receipt,),
    )

    assert snapshot.status == "ready"
    assert snapshot.renewal_allowed
    assert snapshot.verified_triplet_count == 1
    assert snapshot.current_count == 1
    assert snapshot.open_exception_count == 0


def test_phase69_due_soon_assurance_requires_follow_up(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    attestation, pack, receipt = _source(predecessor, age_days=80)

    snapshot = service.snapshot(
        attestation_paths=(attestation,),
        audit_pack_paths=(pack,),
        receipt_paths=(receipt,),
        validity_days=90,
        due_soon_days=14,
    )

    assert snapshot.status == "ready_with_follow_up"
    assert snapshot.due_soon_count == 1
    assert {item.category for item in snapshot.exceptions} == {"renewal_due_soon"}


def test_phase69_overdue_or_withheld_assurance_is_high_risk(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    old = _source(predecessor, suffix="old", age_days=100)
    withheld = _source(
        predecessor,
        suffix="withheld",
        decision="withhold_assurance",
        age_days=2,
    )

    snapshot = service.snapshot(
        attestation_paths=(old[0], withheld[0]),
        audit_pack_paths=(old[1], withheld[1]),
        receipt_paths=(old[2], withheld[2]),
    )

    assert snapshot.overdue_count == 1
    assert snapshot.withheld_count == 1
    assert snapshot.high_exception_count == 2
    assert {item.category for item in snapshot.exceptions} == {
        "renewal_overdue",
        "assurance_withheld",
    }


def test_phase69_tampered_or_unpaired_source_blocks_renewal(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    attestation, pack, receipt = _source(predecessor)
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["owner"] = "tampered"
    _write(attestation, payload)

    tampered = service.snapshot(
        attestation_paths=(attestation,),
        audit_pack_paths=(pack,),
        receipt_paths=(receipt,),
    )
    unpaired = service.snapshot(
        attestation_paths=(tmp_path / "missing.json",),
        audit_pack_paths=(pack,),
        receipt_paths=(receipt,),
    )

    assert tampered.status == "blocked"
    assert tampered.rejected_source_count > 0
    assert unpaired.status == "blocked"


def test_phase69_renewal_creation_is_dry_run_without_acknowledgement(
    tmp_path: Path,
) -> None:
    service, predecessor = _service(tmp_path)
    source = _source(predecessor)
    snapshot = service.snapshot(
        attestation_paths=(source[0],),
        audit_pack_paths=(source[1],),
        receipt_paths=(source[2],),
    )

    result = service.create_renewal(
        snapshot,
        decision="renew",
        owner="Reliability lead",
        statement="The verified assurance remains current and is ready for human renewal.",
    )

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"


def test_phase69_unqualified_renewal_is_blocked_by_follow_up(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    source = _source(predecessor, age_days=80)
    snapshot = service.snapshot(
        attestation_paths=(source[0],),
        audit_pack_paths=(source[1],),
        receipt_paths=(source[2],),
    )

    result = service.create_renewal(
        snapshot,
        decision="renew",
        owner="Reliability lead",
        statement="The assurance source was reviewed but lifecycle follow-up remains open.",
        acknowledge=True,
    )

    assert isinstance(result, dict)
    assert result["status"] == "blocked"
    assert "follow-up" in str(result["detail"]).lower()


def test_phase69_qualified_renewal_requires_owner_date_and_privacy(
    tmp_path: Path,
) -> None:
    service, predecessor = _service(tmp_path)
    source = _source(
        predecessor,
        decision="assure_with_exceptions",
        open_exceptions=1,
    )
    snapshot = service.snapshot(
        attestation_paths=(source[0],),
        audit_pack_paths=(source[1],),
        receipt_paths=(source[2],),
    )

    missing = service.create_renewal(
        snapshot,
        decision="renew_with_follow_up",
        owner="Reliability lead",
        statement="The assurance is renewed with explicit exception follow-up governance.",
        acknowledge=True,
    )
    private = service.create_renewal(
        snapshot,
        decision="renew_with_follow_up",
        owner="Reliability lead",
        statement="The assurance is renewed with explicit exception follow-up governance.",
        follow_up_owner="password=secret",
        next_review_date="2026-08-20",
        acknowledge=True,
    )

    assert isinstance(missing, dict) and missing["status"] == "blocked"
    assert isinstance(private, dict) and private["status"] == "blocked"


def test_phase69_creates_and_verifies_renewal_audit_pack(tmp_path: Path) -> None:
    service, predecessor = _service(tmp_path)
    source = _source(predecessor)
    snapshot = service.snapshot(
        attestation_paths=(source[0],),
        audit_pack_paths=(source[1],),
        receipt_paths=(source[2],),
    )

    result = service.create_renewal(
        snapshot,
        decision="renew",
        owner="Reliability lead",
        statement="The verified assurance remains current and is renewed by a human reviewer.",
        acknowledge=True,
    )

    assert isinstance(result, ReliabilityAssuranceRenewalRecord)
    assert result.audit_pack_path.is_file()
    assert result.receipt_path.is_file()
    assert service.verify_renewal(result.renewal_path)[0]
    assert service.verify_follow_up(result.follow_up_path)[0]
    assert service.verify_audit_pack(result.audit_pack_path, result.receipt_path)[0]
    with zipfile.ZipFile(result.audit_pack_path) as archive:
        assert "manifest.json" in archive.namelist()
        assert "renewal/record.json" in archive.namelist()
        assert "renewal/follow-up.json" in archive.namelist()


def test_phase69_tampering_renewal_follow_up_or_pack_is_detected(
    tmp_path: Path,
) -> None:
    service, predecessor = _service(tmp_path)
    source = _source(predecessor)
    snapshot = service.snapshot(
        attestation_paths=(source[0],),
        audit_pack_paths=(source[1],),
        receipt_paths=(source[2],),
    )
    result = service.create_renewal(
        snapshot,
        decision="renew",
        owner="Reliability lead",
        statement="The verified assurance remains current and is renewed by a human reviewer.",
        acknowledge=True,
    )
    assert isinstance(result, ReliabilityAssuranceRenewalRecord)

    renewal_payload = json.loads(result.renewal_path.read_text(encoding="utf-8"))
    renewal_payload["decision"] = "withhold_renewal"
    _write(result.renewal_path, renewal_payload)
    assert not service.verify_renewal(result.renewal_path)[0]

    follow_up_payload = json.loads(result.follow_up_path.read_text(encoding="utf-8"))
    follow_up_payload["status"] = "open"
    _write(result.follow_up_path, follow_up_payload)
    assert not service.verify_follow_up(result.follow_up_path)[0]

    with result.audit_pack_path.open("ab") as handle:
        handle.write(b"tamper")
    assert not service.verify_audit_pack(result.audit_pack_path, result.receipt_path)[0]

    root = Path(__file__).resolve().parents[1]
    dialog = (
        root / "app" / "gui" / "dialogs" / "reliability_assurance_renewal_dialog.py"
    ).read_text(encoding="utf-8")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "reliability-assurance-renewal.ps1").read_text(
        encoding="utf-8"
    )
    documentation = (
        root / "docs" / "RELIABILITY_ASSURANCE_RENEWAL_PHASE69.md"
    ).read_text(encoding="utf-8")

    assert "reliabilityAssuranceRenewalDialog" in dialog
    assert "Assurance Renewal & Follow-up" in main
    assert "ReliabilityAssuranceRenewalService" in container
    assert "--create-reliability-renewal" in frozen
    assert "--verify-reliability-renewal-pack" in frozen
    assert "automatic_upload" not in script
    assert "never automatically accepts risk" in documentation
