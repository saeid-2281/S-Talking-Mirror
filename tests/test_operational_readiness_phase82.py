from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.services.operational_readiness_service import OperationalReadinessCertificationService


NOW = datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)
COMMIT = "7238d3885d0c9e2ebeb2057dadb330e4b9f2b55e"


class FakeProductionReleaseService:
    ATTESTATION_NAME = "production-release-attestation.json"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / self.ATTESTATION_NAME
        self.path.write_text(json.dumps({"valid": True}), encoding="utf-8")

    def verify_attestation(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("valid") is True, "Production release attestation verified.")


class FakeOperationsService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshots_dir = root / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "latest-operations-command-center.json"
        self.path.write_text(
            json.dumps({"valid": True, "overall_status": "healthy"}),
            encoding="utf-8",
        )

    def verify_snapshot(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("valid") is True, "Operations snapshot verified.")


class FakeEvidenceRefreshService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.registries_dir = root / "registries"
        self.certifications_dir = root / "certifications"
        self.registries_dir.mkdir(parents=True, exist_ok=True)
        self.certifications_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "latest-evidence-registry.json"
        self.certification_path = self.root / "latest-certification-refresh.json"
        self.registry_path.write_text(
            json.dumps(
                {
                    "valid": True,
                    "fresh_count": 8,
                    "due_soon_count": 0,
                    "expired_count": 0,
                    "missing_count": 0,
                    "blocked_count": 0,
                }
            ),
            encoding="utf-8",
        )
        self.certification_path.write_text(
            json.dumps({"valid": True, "status": "certified"}),
            encoding="utf-8",
        )

    def verify_registry(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("valid") is True, "Evidence registry verified.")

    def verify_certification(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("valid") is True, "Certification refresh verified.")


class FakeRenewalService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "latest-reliability-renewal.json"
        self.path.write_text(
            json.dumps({"valid": True, "decision": "renew"}), encoding="utf-8"
        )

    def verify_renewal(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("valid") is True, "Reliability renewal verified.")


def _service(tmp_path: Path, *, channel: str = "stable"):
    runtime = SimpleNamespace(
        artifacts_dir=tmp_path / "artifacts",
        app_root=tmp_path / "project",
    )
    runtime.app_root.mkdir(parents=True, exist_ok=True)
    production = FakeProductionReleaseService(runtime.artifacts_dir / "production-certification")
    operations = FakeOperationsService(runtime.artifacts_dir / "operations-command-center")
    evidence = FakeEvidenceRefreshService(runtime.artifacts_dir / "evidence-refresh")
    renewal = FakeRenewalService(runtime.artifacts_dir / "reliability-assurance-renewal")
    service = OperationalReadinessCertificationService(
        runtime,
        evidence,
        operations,
        production,
        renewal,
        channel=channel,
        now=lambda: NOW,
    )
    return service, production, operations, evidence, renewal


def test_phase82_all_verified_evidence_is_certified(tmp_path: Path) -> None:
    service, *_ = _service(tmp_path)
    snapshot = service.assess(project_id=9, source_commit=COMMIT)
    assert snapshot.status == "certified"
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert len(snapshot.sources) == 5
    assert snapshot.project_id == 9


def test_phase82_due_soon_evidence_requires_warning_review(tmp_path: Path) -> None:
    service, _production, _operations, evidence, _renewal = _service(tmp_path)
    payload = json.loads(evidence.registry_path.read_text(encoding="utf-8"))
    payload["due_soon_count"] = 2
    payload["fresh_count"] = 6
    evidence.registry_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.warning_count == 1


def test_phase82_expired_or_missing_evidence_blocks_certification(tmp_path: Path) -> None:
    service, _production, _operations, evidence, _renewal = _service(tmp_path)
    payload = json.loads(evidence.registry_path.read_text(encoding="utf-8"))
    payload["expired_count"] = 1
    payload["missing_count"] = 1
    evidence.registry_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "blocked"
    assert snapshot.blocker_count >= 1


def test_phase82_invalid_production_attestation_blocks(tmp_path: Path) -> None:
    service, production, *_ = _service(tmp_path)
    production.path.write_text(json.dumps({"valid": False}), encoding="utf-8")
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "blocked"
    gate = next(item for item in snapshot.gates if item.code == "source_production_release")
    assert gate.status == "block"


def test_phase82_withheld_reliability_renewal_blocks(tmp_path: Path) -> None:
    service, _production, _operations, _evidence, renewal = _service(tmp_path)
    renewal.path.write_text(
        json.dumps({"valid": True, "decision": "withhold_renewal"}),
        encoding="utf-8",
    )
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "blocked"
    gate = next(item for item in snapshot.gates if item.code == "reliability_renewal_status")
    assert gate.status == "block"


def test_phase82_certification_requires_human_acknowledgement(tmp_path: Path) -> None:
    service, *_ = _service(tmp_path)
    snapshot = service.assess(source_commit=COMMIT)
    result = service.create_certification(
        snapshot,
        reviewer="Release reviewer",
        statement="Operational evidence reviewed and approved.",
        acknowledge=False,
    )
    assert result["status"] == "dry_run"
    assert not list(service.attestations_dir.glob("*.json"))


def test_phase82_final_attestation_is_verifiable_and_tamper_evident(tmp_path: Path) -> None:
    service, *_ = _service(tmp_path)
    snapshot = service.assess(source_commit=COMMIT)
    result = service.create_certification(
        snapshot,
        reviewer="Release reviewer",
        statement="Operational evidence reviewed and approved.",
        acknowledge=True,
    )
    assert result["status"] == "certified"
    attestation = Path(str(result["path"]))
    ok, detail = service.verify_attestation(attestation)
    assert ok, detail
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["status"] = "blocked"
    attestation.write_text(json.dumps(payload), encoding="utf-8")
    ok, _detail = service.verify_attestation(attestation)
    assert not ok


def test_phase82_audit_pack_and_source_custody_are_verified(tmp_path: Path) -> None:
    service, _production, _operations, evidence, _renewal = _service(tmp_path)
    snapshot = service.assess(source_commit=COMMIT)
    result = service.create_certification(
        snapshot,
        reviewer="Release reviewer",
        statement="Operational evidence reviewed and approved.",
        acknowledge=True,
    )
    pack = Path(str(result["audit_pack_path"]))
    receipt = Path(str(result["receipt_path"]))
    ok, detail = service.verify_audit_pack(pack, receipt)
    assert ok, detail
    evidence.registry_path.write_text(json.dumps({"valid": True}), encoding="utf-8")
    ok, detail = service.verify_audit_pack(pack, receipt)
    assert not ok
    assert "source" in detail.lower() or "registry" in detail.lower()


def test_phase82_certification_is_private_and_has_no_automatic_actions(tmp_path: Path) -> None:
    service, production, operations, evidence, renewal = _service(tmp_path)
    before = {
        "production": production.path.read_bytes(),
        "operations": operations.path.read_bytes(),
        "registry": evidence.registry_path.read_bytes(),
        "refresh": evidence.certification_path.read_bytes(),
        "renewal": renewal.path.read_bytes(),
    }
    snapshot = service.assess(source_commit=COMMIT)
    blocked = service.create_certification(
        snapshot,
        reviewer="Release reviewer",
        statement=f"Evidence reviewed at {tmp_path / 'private.txt'}",
        acknowledge=True,
    )
    assert blocked["status"] == "blocked"
    result = service.create_certification(
        snapshot,
        reviewer="Release reviewer",
        statement="Operational evidence reviewed and approved.",
        acknowledge=True,
    )
    attestation = json.loads(Path(str(result["path"])).read_text(encoding="utf-8"))
    assert attestation["automatic_deploy"] is False
    assert attestation["automatic_restart"] is False
    assert attestation["automatic_publish"] is False
    assert attestation["automatic_tag"] is False
    assert attestation["private_data_included"] is False
    assert before == {
        "production": production.path.read_bytes(),
        "operations": operations.path.read_bytes(),
        "registry": evidence.registry_path.read_bytes(),
        "refresh": evidence.certification_path.read_bytes(),
        "renewal": renewal.path.read_bytes(),
    }
