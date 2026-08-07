from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.services.evidence_refresh_service import EvidenceRefreshService


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
CODES = (
    "health",
    "incidents",
    "slo",
    "capacity",
    "recovery",
    "providers",
    "billing",
    "audit",
)


class FakeOperationsService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.snapshots_dir = root / "operations"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.sources: dict[str, Path] = {}
        self.domains = []
        for code in CODES:
            source = root / f"{code}.json"
            source.write_text(json.dumps({"code": code, "status": "verified"}), encoding="utf-8")
            self.sources[code] = source
            self.domains.append(
                SimpleNamespace(
                    code=code,
                    label=code.title(),
                    status="healthy",
                    headline="Verified evidence is available.",
                    metric="Verified",
                    detail="Source verification passed.",
                    evidence_filename=source.name,
                    evidence_sha256="",
                    action_code=f"open-{code}",
                )
            )

    def snapshot(self, *, project_id=None):
        return SimpleNamespace(domains=tuple(self.domains), project_id=project_id)

    def _evidence_path(self, code: str, filename: str) -> Path | None:
        path = self.sources.get(code)
        return path if path is not None and path.name == filename else None

    def export_snapshot(self, snapshot) -> Path:
        path = self.snapshots_dir / "operations-refresh.json"
        path.write_text(json.dumps({"verified": True, "project_id": snapshot.project_id}), encoding="utf-8")
        return path

    def verify_snapshot(self, path: Path):
        if not Path(path).is_file():
            return False, "Operations snapshot is missing."
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "Operations snapshot is unreadable."
        return (payload.get("verified") is True, "Operations snapshot verified.")


def _service(tmp_path: Path) -> tuple[EvidenceRefreshService, FakeOperationsService]:
    operations = FakeOperationsService(tmp_path / "sources")
    runtime = SimpleNamespace(artifacts_dir=tmp_path / "artifacts")
    service = EvidenceRefreshService(runtime, operations, now=lambda: NOW)
    return service, operations


def _set_age(path: Path, days: float) -> None:
    timestamp = NOW.timestamp() - days * 86400
    os.utime(path, (timestamp, timestamp))


def test_phase81_all_current_evidence_is_fresh(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    snapshot = service.assess(project_id=7)
    assert snapshot.overall_status == "current"
    assert snapshot.count("fresh") == 8
    assert snapshot.project_id == 7


def test_phase81_due_soon_is_attention(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    _set_age(operations.sources["slo"], 6)
    snapshot = service.assess()
    assert snapshot.overall_status == "attention"
    slo = next(item for item in snapshot.entries if item.code == "slo")
    assert slo.status == "due_soon"


def test_phase81_expired_evidence_is_attention(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    _set_age(operations.sources["billing"], 31)
    snapshot = service.assess()
    billing = next(item for item in snapshot.entries if item.code == "billing")
    assert billing.status == "expired"
    assert snapshot.count("expired") == 1


def test_phase81_missing_evidence_is_reported(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    operations.domains[2].evidence_filename = ""
    snapshot = service.assess()
    slo = next(item for item in snapshot.entries if item.code == "slo")
    assert slo.status == "missing"
    assert snapshot.overall_status == "attention"


def test_phase81_verification_failure_blocks_refresh(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    operations.domains[3].metric = "Verification failed"
    operations.domains[3].detail = "Source custody changed."
    snapshot = service.assess()
    capacity = next(item for item in snapshot.entries if item.code == "capacity")
    assert capacity.status == "blocked"
    assert snapshot.overall_status == "blocked"


def test_phase81_registry_is_verifiable_and_tamper_evident(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    registry = service.export_registry(service.assess())
    ok, detail = service.verify_registry(registry)
    assert ok, detail
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["overall_status"] = "blocked"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    ok, _detail = service.verify_registry(registry)
    assert not ok


def test_phase81_certification_refresh_is_read_only_and_verifiable(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    before = {code: path.read_bytes() for code, path in operations.sources.items()}
    registry, certification = service.refresh_certification(project_id=3)
    assert registry.is_file()
    ok, detail = service.verify_certification(certification)
    assert ok, detail
    payload = json.loads(certification.read_text(encoding="utf-8"))
    assert payload["status"] == "certified"
    assert payload["read_only_refresh"] is True
    assert payload["source_evidence_mutated"] is False
    assert before == {code: path.read_bytes() for code, path in operations.sources.items()}


def test_phase81_certification_detects_registry_custody_change(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    registry, certification = service.refresh_certification()
    registry.write_text("{}", encoding="utf-8")
    ok, detail = service.verify_certification(certification)
    assert not ok
    assert "registry" in detail.lower()


def test_phase81_refresh_evidence_contains_no_absolute_paths_or_automatic_actions(tmp_path: Path) -> None:
    service, operations = _service(tmp_path)
    for path in operations.sources.values():
        _set_age(path, 1)
    operations.domains[0].detail = f"Diagnostic source: {tmp_path / 'private.log'}"
    registry, certification = service.refresh_certification()
    combined = registry.read_text(encoding="utf-8") + certification.read_text(encoding="utf-8")
    assert str(tmp_path) not in combined
    payload = json.loads(certification.read_text(encoding="utf-8"))
    assert payload["automatic_deploy"] is False
    assert payload["automatic_restart"] is False
    assert payload["automatic_publish"] is False
    assert payload["private_data_included"] is False
