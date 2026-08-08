from __future__ import annotations

import json

from app.database.connection import Database
from app.models.operational_persistence import (
    OperationalEvidenceRecord,
    OperationalPersistenceSyncSummary,
)


class OperationalEvidenceRepository:
    """Append-only operational evidence index backed by the application database."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def store(self, record: OperationalEvidenceRecord) -> str:
        existing = self.get(record.evidence_key)
        if existing is not None:
            if (
                existing.artifact_sha256 == record.artifact_sha256
                and existing.payload_sha256 == record.payload_sha256
                and existing.record_sha256 == record.record_sha256
            ):
                return "unchanged"
            raise ValueError(
                f"Operational evidence key collision: {record.evidence_key}"
            )

        payload_json = json.dumps(
            dict(record.payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO operational_evidence_records(
                    evidence_key, source_record_id, evidence_type, source_service,
                    artifact_filename, artifact_sha256, payload_sha256, record_sha256,
                    status, schema_version, project_id, source_created_at, recorded_at,
                    payload_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.evidence_key,
                    record.source_record_id,
                    record.evidence_type,
                    record.source_service,
                    record.artifact_filename,
                    record.artifact_sha256,
                    record.payload_sha256,
                    record.record_sha256,
                    record.status,
                    int(record.schema_version),
                    record.project_id,
                    record.source_created_at,
                    record.recorded_at,
                    payload_json,
                ),
            )
        return "inserted"

    def get(self, evidence_key: str) -> OperationalEvidenceRecord | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM operational_evidence_records WHERE evidence_key = ?",
                (evidence_key,),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def list_records(
        self,
        *,
        evidence_type: str | None = None,
        limit: int = 200,
    ) -> list[OperationalEvidenceRecord]:
        limit = max(1, min(int(limit), 5000))
        with self.database.connect() as connection:
            if evidence_type:
                rows = connection.execute(
                    """
                    SELECT * FROM operational_evidence_records
                    WHERE evidence_type = ?
                    ORDER BY recorded_at DESC, evidence_key DESC
                    LIMIT ?
                    """,
                    (evidence_type, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM operational_evidence_records
                    ORDER BY recorded_at DESC, evidence_key DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def count(self) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM operational_evidence_records"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def counts_by_type(self) -> dict[str, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence_type, COUNT(*) AS record_count
                FROM operational_evidence_records
                GROUP BY evidence_type
                ORDER BY evidence_type
                """
            ).fetchall()
        return {str(row["evidence_type"]): int(row["record_count"]) for row in rows}

    def latest_by_type(self) -> dict[str, OperationalEvidenceRecord]:
        records = self.list_records(limit=5000)
        latest: dict[str, OperationalEvidenceRecord] = {}
        for record in records:
            latest.setdefault(record.evidence_type, record)
        return latest

    def record_sync_run(self, summary: OperationalPersistenceSyncSummary) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO operational_persistence_runs(
                    run_id, started_at, completed_at, scanned, imported,
                    unchanged, skipped, failed, status, details_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.run_id,
                    summary.started_at,
                    summary.completed_at,
                    summary.scanned,
                    summary.imported,
                    summary.unchanged,
                    summary.skipped,
                    summary.failed,
                    summary.status,
                    json.dumps(list(summary.details), ensure_ascii=False),
                ),
            )

    def latest_sync_run(self) -> OperationalPersistenceSyncSummary | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM operational_persistence_runs
                ORDER BY completed_at DESC, run_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        details = json.loads(str(row["details_json"] or "[]"))
        return OperationalPersistenceSyncSummary(
            run_id=str(row["run_id"]),
            started_at=str(row["started_at"]),
            completed_at=str(row["completed_at"]),
            scanned=int(row["scanned"]),
            imported=int(row["imported"]),
            unchanged=int(row["unchanged"]),
            skipped=int(row["skipped"]),
            failed=int(row["failed"]),
            status=str(row["status"]),
            details=tuple(str(item) for item in details),
        )

    @staticmethod
    def _record_from_row(row) -> OperationalEvidenceRecord:
        payload = json.loads(str(row["payload_json"] or "{}"))
        return OperationalEvidenceRecord(
            evidence_key=str(row["evidence_key"]),
            source_record_id=str(row["source_record_id"]),
            evidence_type=str(row["evidence_type"]),
            source_service=str(row["source_service"]),
            artifact_filename=str(row["artifact_filename"]),
            artifact_sha256=str(row["artifact_sha256"]),
            payload_sha256=str(row["payload_sha256"]),
            record_sha256=str(row["record_sha256"]),
            status=str(row["status"]),
            schema_version=int(row["schema_version"]),
            project_id=row["project_id"],
            source_created_at=str(row["source_created_at"] or ""),
            recorded_at=str(row["recorded_at"]),
            payload=payload if isinstance(payload, dict) else {},
        )
