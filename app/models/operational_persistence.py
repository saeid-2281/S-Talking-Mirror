from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class OperationalEvidenceRecord:
    evidence_key: str
    source_record_id: str
    evidence_type: str
    source_service: str
    artifact_filename: str
    artifact_sha256: str
    payload_sha256: str
    record_sha256: str
    status: str
    schema_version: int
    project_id: int | None
    source_created_at: str
    recorded_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_key": self.evidence_key,
            "source_record_id": self.source_record_id,
            "evidence_type": self.evidence_type,
            "source_service": self.source_service,
            "artifact_filename": self.artifact_filename,
            "artifact_sha256": self.artifact_sha256,
            "payload_sha256": self.payload_sha256,
            "record_sha256": self.record_sha256,
            "status": self.status,
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "source_created_at": self.source_created_at,
            "recorded_at": self.recorded_at,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class OperationalPersistenceSyncSummary:
    run_id: str
    started_at: str
    completed_at: str
    scanned: int
    imported: int
    unchanged: int
    skipped: int
    failed: int
    status: str
    details: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "scanned": self.scanned,
            "imported": self.imported,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "failed": self.failed,
            "status": self.status,
            "details": list(self.details),
        }
