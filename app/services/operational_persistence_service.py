from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from app.models.operational_persistence import (
    OperationalEvidenceRecord,
    OperationalPersistenceSyncSummary,
)
from app.repositories.operational_evidence_repository import OperationalEvidenceRepository
from app.services.evidence_integrity import EvidenceIntegrityMixin


class OperationalPersistenceService(EvidenceIntegrityMixin):
    """Indexes verified operational JSON evidence without replacing source artifacts."""

    SCHEMA_VERSION = 1
    SOURCE_CODES = (
        "operations_snapshot",
        "evidence_registry",
        "certification_refresh",
        "readiness_snapshot",
        "readiness_attestation",
    )
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(
        r"(?i)(?:[a-z]:[\\/]|/(?:home|users|tmp|var/tmp)/)"
    )

    def __init__(
        self,
        repository: OperationalEvidenceRepository,
        operations_command_center_service: Any,
        evidence_refresh_service: Any,
        operational_readiness_service: Any,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.database = repository.database
        self.operations_command_center_service = operations_command_center_service
        self.evidence_refresh_service = evidence_refresh_service
        self.operational_readiness_service = operational_readiness_service
        self._now_provider = now or (lambda: datetime.now(timezone.utc))

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "source_artifacts_authoritative": True,
            "database_is_secondary_index": True,
            "automatic_source_mutation": False,
            "automatic_evidence_deletion": False,
            "automatic_publish": False,
            "private_data_included": False,
        }

    def sync_verified_latest(self) -> OperationalPersistenceSyncSummary:
        started = self._now_iso()
        run_id = f"operational-persistence-{uuid.uuid4().hex[:12]}"
        imported = 0
        unchanged = 0
        skipped = 0
        failed = 0
        details: list[str] = []

        sources = self._source_specs()
        for code in self.SOURCE_CODES:
            spec = sources[code]
            path = Path(spec["path"])
            if not path.is_file():
                skipped += 1
                details.append(f"{code}: source artifact is not available")
                continue

            verifier = spec["verifier"]
            ok, detail = verifier(path)
            if not ok:
                failed += 1
                details.append(self._safe_detail(f"{code}: verification failed — {detail}"))
                continue

            payload = self._read_json(path)
            if not isinstance(payload, dict):
                failed += 1
                details.append(f"{code}: source artifact is unreadable")
                continue
            if self._contains_private_payload(payload):
                failed += 1
                details.append(f"{code}: private material was rejected")
                continue

            try:
                record = self._build_record(code, spec, path, payload)
                result = self.repository.store(record)
            except (OSError, ValueError, TypeError) as exc:
                failed += 1
                details.append(self._safe_detail(f"{code}: persistence rejected — {exc}"))
                continue

            if result == "inserted":
                imported += 1
                details.append(f"{code}: imported {path.name}")
            else:
                unchanged += 1
                details.append(f"{code}: already indexed {path.name}")

        completed = self._now_iso()
        status = "failed" if failed else "partial" if skipped else "verified"
        summary = OperationalPersistenceSyncSummary(
            run_id=run_id,
            started_at=started,
            completed_at=completed,
            scanned=len(self.SOURCE_CODES),
            imported=imported,
            unchanged=unchanged,
            skipped=skipped,
            failed=failed,
            status=status,
            details=tuple(details),
        )
        self.repository.record_sync_run(summary)
        return summary

    def verify_record(self, record: OperationalEvidenceRecord) -> tuple[bool, str]:
        payload = dict(record.payload)
        if self._contains_private_payload(payload):
            return False, "Persisted operational record contains private material."
        payload_sha256 = self._payload_digest(payload)
        if payload_sha256 != record.payload_sha256:
            return False, "Persisted operational payload digest changed."
        expected_record_sha256 = self._record_digest(
            evidence_key=record.evidence_key,
            source_record_id=record.source_record_id,
            evidence_type=record.evidence_type,
            source_service=record.source_service,
            artifact_filename=record.artifact_filename,
            artifact_sha256=record.artifact_sha256,
            payload_sha256=record.payload_sha256,
            status=record.status,
            schema_version=record.schema_version,
            project_id=record.project_id,
            source_created_at=record.source_created_at,
        )
        if expected_record_sha256 != record.record_sha256:
            return False, "Persisted operational record digest changed."
        return True, "Persisted operational record integrity verified."

    def verify_database(self) -> tuple[bool, str]:
        quick_check = self.database.quick_check()
        if quick_check != "ok":
            return False, f"SQLite quick_check failed: {quick_check}"
        if self.database.foreign_key_violations():
            return False, "SQLite foreign-key verification failed."
        for record in self.repository.list_records(limit=5000):
            ok, detail = self.verify_record(record)
            if not ok:
                return False, f"{record.evidence_key}: {detail}"
        return True, "Operational persistence database and record digests verified."

    def status(self) -> dict[str, object]:
        ok, detail = self.verify_database()
        latest = self.repository.latest_sync_run()
        return {
            "database_filename": self.database.path.name,
            "database_ok": ok,
            "database_detail": detail,
            "schema_version": self.database.expected_schema_version,
            "record_count": self.repository.count(),
            "counts_by_type": self.repository.counts_by_type(),
            "latest_by_type": self.repository.latest_by_type(),
            "latest_sync": latest,
            "safety_contract": self._safety_contract(),
        }

    def _safe_detail(self, detail: object) -> str:
        text = str(detail or "").replace("\r", " ").replace("\n", " ").strip()
        if self._contains_private_text(text):
            return "Operational persistence diagnostic detail omitted for privacy."
        return text[:600]

    def _source_specs(self) -> dict[str, dict[str, object]]:
        return {
            "operations_snapshot": {
                "path": Path(self.operations_command_center_service.root)
                / "latest-operations-command-center.json",
                "verifier": self.operations_command_center_service.verify_snapshot,
                "id_field": "snapshot_id",
                "status_field": "overall_status",
                "service": "operations-command-center",
            },
            "evidence_registry": {
                "path": Path(self.evidence_refresh_service.root)
                / "latest-evidence-registry.json",
                "verifier": self.evidence_refresh_service.verify_registry,
                "id_field": "snapshot_id",
                "status_field": "overall_status",
                "service": "evidence-refresh",
            },
            "certification_refresh": {
                "path": Path(self.evidence_refresh_service.root)
                / "latest-certification-refresh.json",
                "verifier": self.evidence_refresh_service.verify_certification,
                "id_field": "refresh_id",
                "status_field": "status",
                "service": "evidence-refresh",
            },
            "readiness_snapshot": {
                "path": Path(self.operational_readiness_service.root)
                / "latest-operational-readiness-snapshot.json",
                "verifier": self.operational_readiness_service.verify_snapshot,
                "id_field": "certification_id",
                "status_field": "status",
                "service": "operational-readiness-certification",
            },
            "readiness_attestation": {
                "path": Path(self.operational_readiness_service.root)
                / "latest-operational-readiness-attestation.json",
                "verifier": self.operational_readiness_service.verify_attestation,
                "id_field": "certification_id",
                "status_field": "status",
                "service": "operational-readiness-certification",
            },
        }

    def _build_record(
        self,
        code: str,
        spec: Mapping[str, object],
        path: Path,
        payload: Mapping[str, object],
    ) -> OperationalEvidenceRecord:
        source_record_id = str(payload.get(str(spec["id_field"])) or "").strip()
        artifact_sha256 = self._sha256(path)
        if not source_record_id:
            source_record_id = artifact_sha256[:24]
        evidence_key = f"{code}:{source_record_id}"
        payload_sha256 = self._payload_digest(payload)
        schema_version = int(payload.get("schema_version") or 1)
        project_id_value = payload.get("project_id")
        project_id = int(project_id_value) if isinstance(project_id_value, int) else None
        source_created_at = str(payload.get("generated_at") or "")
        status = str(payload.get(str(spec["status_field"])) or "unknown")
        source_service = str(spec["service"])
        record_sha256 = self._record_digest(
            evidence_key=evidence_key,
            source_record_id=source_record_id,
            evidence_type=code,
            source_service=source_service,
            artifact_filename=path.name,
            artifact_sha256=artifact_sha256,
            payload_sha256=payload_sha256,
            status=status,
            schema_version=schema_version,
            project_id=project_id,
            source_created_at=source_created_at,
        )
        return OperationalEvidenceRecord(
            evidence_key=evidence_key,
            source_record_id=source_record_id,
            evidence_type=code,
            source_service=source_service,
            artifact_filename=path.name,
            artifact_sha256=artifact_sha256,
            payload_sha256=payload_sha256,
            record_sha256=record_sha256,
            status=status,
            schema_version=schema_version,
            project_id=project_id,
            source_created_at=source_created_at,
            recorded_at=self._now_iso(),
            payload=dict(payload),
        )

    @classmethod
    def _record_digest(cls, **fields: object) -> str:
        return cls._payload_digest(fields)
