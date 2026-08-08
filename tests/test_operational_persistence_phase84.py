from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest

from app.database.connection import Database
from app.models.operational_persistence import OperationalEvidenceRecord
from app.repositories.operational_evidence_repository import OperationalEvidenceRepository
from app.release import SCHEMA_VERSION
from app.services.operational_persistence_service import OperationalPersistenceService


NOW = datetime(2026, 8, 8, 8, 30, tzinfo=timezone.utc)


class FakeOperationsService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "latest-operations-command-center.json"
        self.write()

    def write(self, **changes: object) -> None:
        payload = {
            "schema_version": 1,
            "snapshot_id": "operations-command-phase84",
            "generated_at": "2026-08-08T08:00:00+00:00",
            "project_id": 4,
            "overall_status": "healthy",
        }
        payload.update(changes)
        self.path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def verify_snapshot(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("invalid") is not True, "Operations snapshot verified.")


class FakeEvidenceRefreshService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "latest-evidence-registry.json"
        self.certification_path = self.root / "latest-certification-refresh.json"
        self.registry_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "snapshot_id": "evidence-refresh-phase84",
                    "generated_at": "2026-08-08T08:05:00+00:00",
                    "project_id": 4,
                    "overall_status": "current",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.certification_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "refresh_id": "certification-refresh-phase84",
                    "generated_at": "2026-08-08T08:06:00+00:00",
                    "project_id": 4,
                    "status": "certified",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def verify_registry(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("invalid") is not True, "Evidence registry verified.")

    def verify_certification(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("invalid") is not True, "Certification refresh verified.")


class FakeOperationalReadinessService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = self.root / "latest-operational-readiness-snapshot.json"
        self.attestation_path = self.root / "latest-operational-readiness-attestation.json"
        self.snapshot_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "certification_id": "operational-certification-phase84",
                    "generated_at": "2026-08-08T08:10:00+00:00",
                    "project_id": 4,
                    "status": "certified",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.attestation_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "certification_id": "operational-certification-phase84",
                    "generated_at": "2026-08-08T08:12:00+00:00",
                    "project_id": 4,
                    "status": "certified",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def verify_snapshot(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("invalid") is not True, "Readiness snapshot verified.")

    def verify_attestation(self, path: Path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return (payload.get("invalid") is not True, "Readiness attestation verified.")


def _service(tmp_path: Path):
    database = Database(tmp_path / "data" / "s_talking.db")
    database.initialize()
    repository = OperationalEvidenceRepository(database)
    operations = FakeOperationsService(tmp_path / "artifacts" / "operations-command-center")
    evidence = FakeEvidenceRefreshService(tmp_path / "artifacts" / "evidence-refresh")
    readiness = FakeOperationalReadinessService(
        tmp_path / "artifacts" / "operational-readiness-certification"
    )
    service = OperationalPersistenceService(
        repository,
        operations,
        evidence,
        readiness,
        now=lambda: NOW,
    )
    return service, repository, database, operations, evidence, readiness


def test_phase84_migration_adds_operational_persistence_schema(tmp_path: Path) -> None:
    database = Database(tmp_path / "s_talking.db")
    database.initialize()
    assert SCHEMA_VERSION == database.expected_schema_version == 23
    with database.connect() as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "operational_evidence_records" in tables
    assert "operational_persistence_runs" in tables


def test_phase84_verified_latest_sync_is_idempotent(tmp_path: Path) -> None:
    service, repository, *_ = _service(tmp_path)
    first = service.sync_verified_latest()
    assert first.status == "verified"
    assert first.imported == 5
    assert first.failed == 0
    assert repository.count() == 5

    second = service.sync_verified_latest()
    assert second.status == "verified"
    assert second.imported == 0
    assert second.unchanged == 5
    assert repository.count() == 5


def test_phase84_missing_source_is_partial_not_destructive(tmp_path: Path) -> None:
    service, repository, _database, _operations, _evidence, readiness = _service(tmp_path)
    readiness.attestation_path.unlink()
    summary = service.sync_verified_latest()
    assert summary.status == "partial"
    assert summary.skipped == 1
    assert summary.failed == 0
    assert repository.count() == 4


def test_phase84_invalid_verified_source_is_not_persisted(tmp_path: Path) -> None:
    service, repository, _database, operations, *_ = _service(tmp_path)
    operations.write(invalid=True)
    summary = service.sync_verified_latest()
    assert summary.failed == 1
    assert repository.count() == 4
    assert not repository.list_records(evidence_type="operations_snapshot")


def test_phase84_sync_never_mutates_authoritative_json_artifacts(tmp_path: Path) -> None:
    service, _repository, _database, operations, evidence, readiness = _service(tmp_path)
    paths = (
        operations.path,
        evidence.registry_path,
        evidence.certification_path,
        readiness.snapshot_path,
        readiness.attestation_path,
    )
    before = {path: path.read_bytes() for path in paths}
    service.sync_verified_latest()
    assert before == {path: path.read_bytes() for path in paths}


def test_phase84_repository_rejects_evidence_key_reuse_with_changed_digest(tmp_path: Path) -> None:
    service, repository, *_ = _service(tmp_path)
    service.sync_verified_latest()
    record = repository.list_records(evidence_type="operations_snapshot")[0]
    changed = OperationalEvidenceRecord(
        **{
            **record.to_dict(),
            "artifact_sha256": "0" * 64,
            "payload": record.payload,
        }
    )
    with pytest.raises(ValueError, match="collision"):
        repository.store(changed)


def test_phase84_database_verification_detects_payload_tampering(tmp_path: Path) -> None:
    service, repository, database, *_ = _service(tmp_path)
    service.sync_verified_latest()
    record = repository.list_records()[0]
    with database.connect() as connection:
        connection.execute(
            "UPDATE operational_evidence_records SET payload_json = ? WHERE evidence_key = ?",
            (json.dumps({"status": "tampered"}), record.evidence_key),
        )
    ok, detail = service.verify_database()
    assert not ok
    assert "digest" in detail.lower()


def test_phase84_private_payload_is_rejected_even_if_source_verifier_accepts_it(tmp_path: Path) -> None:
    service, repository, _database, operations, *_ = _service(tmp_path)
    operations.write(note=r"C:\\Users\\operator\\private.txt")
    summary = service.sync_verified_latest()
    assert summary.failed == 1
    assert not repository.list_records(evidence_type="operations_snapshot")


def test_phase84_status_exposes_secondary_index_safety_contract_without_auto_sync(tmp_path: Path) -> None:
    service, repository, database, *_ = _service(tmp_path)
    assert repository.count() == 0
    status = service.status()
    contract = status["safety_contract"]
    assert status["database_ok"] is True
    assert status["schema_version"] == database.expected_schema_version
    assert contract["source_artifacts_authoritative"] is True
    assert contract["database_is_secondary_index"] is True
    assert contract["automatic_source_mutation"] is False
    assert contract["automatic_evidence_deletion"] is False
    assert contract["automatic_publish"] is False
    assert contract["private_data_included"] is False
