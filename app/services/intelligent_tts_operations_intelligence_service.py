from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.services.intelligent_tts_artifact_provenance_service import (
    IntelligentTTSArtifactReceipt,
)
from app.services.intelligent_tts_execution_service import (
    IntelligentTTSExecutionBinding,
)


OPERATIONS_SNAPSHOT_SCHEMA_VERSION = 1
OPERATIONS_ROLLUP_SCHEMA_VERSION = 1


class IntelligentTTSOperationsIntelligenceError(RuntimeError):
    """Base error for B6 production-operations evidence."""


class IntelligentTTSOperationsIntegrityError(
    IntelligentTTSOperationsIntelligenceError
):
    """Raised when persisted B6 operations evidence fails verification."""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _safe_component(value: str, fallback: str) -> str:
    normalized = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        str(value).strip(),
    ).strip(".-_")
    return (normalized or fallback)[:96]


def _number(
    value: Any,
    *,
    default: float = 0.0,
) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _count(value: Any) -> int:
    return max(0, int(_number(value)))


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class IntelligentTTSOperationsSnapshot:
    schema_version: int
    run_id: str
    project_key: str
    result: str
    manifest_digest: str
    authority_digest: str
    provider: str
    profile_id: str | None
    voice_id: str
    model_id: str
    default_language: str
    request_count: int
    character_count: int
    completed: int
    failed: int
    skipped: int
    accounted: int
    completion_rate: float
    elapsed_seconds: float
    retry_events: int
    files_per_minute: float
    characters_per_minute: float
    verified_files: int
    artifact_issue_count: int
    artifact_status: str
    artifact_receipt_digest: str | None
    execution_receipt_id: str | None
    resume_run: bool
    parent_run_id: str | None
    health: str
    captured_at: str
    snapshot_digest: str
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "project_key": self.project_key,
            "result": self.result,
            "manifest_digest": self.manifest_digest,
            "authority_digest": self.authority_digest,
            "provider": self.provider,
            "profile_id": self.profile_id,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "default_language": self.default_language,
            "request_count": self.request_count,
            "character_count": self.character_count,
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
            "accounted": self.accounted,
            "completion_rate": self.completion_rate,
            "elapsed_seconds": self.elapsed_seconds,
            "retry_events": self.retry_events,
            "files_per_minute": self.files_per_minute,
            "characters_per_minute": self.characters_per_minute,
            "verified_files": self.verified_files,
            "artifact_issue_count": self.artifact_issue_count,
            "artifact_status": self.artifact_status,
            "artifact_receipt_digest": self.artifact_receipt_digest,
            "execution_receipt_id": self.execution_receipt_id,
            "resume_run": self.resume_run,
            "parent_run_id": self.parent_run_id,
            "health": self.health,
            "captured_at": self.captured_at,
            "snapshot_digest": self.snapshot_digest,
        }


@dataclass(frozen=True)
class IntelligentTTSOperationsRollup:
    schema_version: int
    project_key: str
    total_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    request_count: int
    completed_jobs: int
    failed_jobs: int
    skipped_jobs: int
    completion_rate: float
    verified_files: int
    artifact_issue_count: int
    resume_runs: int
    retry_events: int
    average_elapsed_seconds: float
    average_files_per_minute: float
    average_characters_per_minute: float
    healthy_runs: int
    warning_runs: int
    attention_runs: int
    invalid_snapshot_count: int
    latest_run_id: str | None
    latest_result: str | None
    health: str
    generated_at: str
    rollup_digest: str
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_key": self.project_key,
            "total_runs": self.total_runs,
            "completed_runs": self.completed_runs,
            "failed_runs": self.failed_runs,
            "cancelled_runs": self.cancelled_runs,
            "request_count": self.request_count,
            "completed_jobs": self.completed_jobs,
            "failed_jobs": self.failed_jobs,
            "skipped_jobs": self.skipped_jobs,
            "completion_rate": self.completion_rate,
            "verified_files": self.verified_files,
            "artifact_issue_count": self.artifact_issue_count,
            "resume_runs": self.resume_runs,
            "retry_events": self.retry_events,
            "average_elapsed_seconds": self.average_elapsed_seconds,
            "average_files_per_minute": self.average_files_per_minute,
            "average_characters_per_minute": (
                self.average_characters_per_minute
            ),
            "healthy_runs": self.healthy_runs,
            "warning_runs": self.warning_runs,
            "attention_runs": self.attention_runs,
            "invalid_snapshot_count": self.invalid_snapshot_count,
            "latest_run_id": self.latest_run_id,
            "latest_result": self.latest_result,
            "health": self.health,
            "generated_at": self.generated_at,
            "rollup_digest": self.rollup_digest,
        }


class IntelligentTTSOperationsIntelligenceService:
    """Create privacy-safe production intelligence from existing evidence.

    B6 observes completed execution evidence. It does not control generation,
    retry, recovery, routing, provider/account/voice/model/language selection,
    queue order, Preflight, Smart Routing, or output files.
    """

    def observe_run(
        self,
        binding: IntelligentTTSExecutionBinding,
        *,
        run_id: str,
        project_key: str,
        result: str,
        summary: Mapping[str, Any] | None,
        monitor_metrics: Mapping[str, Any] | None,
        artifact_receipt: IntelligentTTSArtifactReceipt | None,
        execution_receipt: Any | None,
        recovery_assessment: Any | None,
        evidence_root: Path,
    ) -> IntelligentTTSOperationsSnapshot:
        normalized_result = (
            str(result or "unknown").strip().casefold()
            or "unknown"
        )
        path = self.snapshot_path(
            evidence_root,
            project_key,
            run_id,
        )
        expected_artifact_digest = (
            str(artifact_receipt.receipt_digest)
            if artifact_receipt is not None
            else None
        )
        if path.exists():
            existing = self.load_snapshot(path)
            if (
                existing.run_id == str(run_id)
                and existing.manifest_digest == binding.manifest_digest
                and existing.authority_digest == binding.authority_digest
                and existing.result == normalized_result
                and existing.artifact_receipt_digest
                == expected_artifact_digest
            ):
                return existing
            raise IntelligentTTSOperationsIntelligenceError(
                "Operations snapshot already exists for different run evidence"
            )

        source = summary or {}
        metrics = monitor_metrics or {}

        completed = _count(source.get("completed"))
        failed = _count(source.get("failed"))
        skipped = _count(source.get("skipped"))
        accounted = completed + failed + skipped
        request_count = int(binding.request_count)

        completion_rate = (
            completed / request_count
            if request_count
            else 0.0
        )
        elapsed_seconds = max(
            0.0,
            _number(
                metrics.get(
                    "elapsed_seconds",
                    metrics.get("total_elapsed_seconds", 0.0),
                )
            ),
        )
        retry_events = _count(metrics.get("retry_events"))
        files_per_minute = max(
            0.0,
            _number(metrics.get("files_per_minute")),
        )
        characters_per_minute = max(
            0.0,
            _number(metrics.get("characters_per_minute")),
        )

        verified_files = (
            int(artifact_receipt.verified_files)
            if artifact_receipt is not None
            else 0
        )
        artifact_issue_count = (
            int(artifact_receipt.issue_count)
            if artifact_receipt is not None
            else 0
        )
        artifact_status = (
            str(artifact_receipt.status)
            if artifact_receipt is not None
            else "unavailable"
        )
        artifact_receipt_digest = (
            str(artifact_receipt.receipt_digest)
            if artifact_receipt is not None
            else None
        )

        execution_receipt_id = None
        if execution_receipt is not None:
            value = getattr(
                execution_receipt,
                "receipt_id",
                None,
            )
            if value is not None:
                execution_receipt_id = str(value)

        resume_run = recovery_assessment is not None
        parent_run_id = None
        if recovery_assessment is not None:
            value = getattr(
                recovery_assessment,
                "parent_run_id",
                None,
            )
            if value:
                parent_run_id = str(value)

        health = self._health(
            normalized_result,
            failed=failed,
            skipped=skipped,
            artifact_issue_count=artifact_issue_count,
            request_count=request_count,
            accounted=accounted,
        )

        material = {
            "schema_version": OPERATIONS_SNAPSHOT_SCHEMA_VERSION,
            "run_id": str(run_id),
            "project_key": str(project_key),
            "result": normalized_result,
            "manifest_digest": binding.manifest_digest,
            "authority_digest": binding.authority_digest,
            "provider": binding.provider,
            "profile_id": binding.profile_id,
            "voice_id": binding.voice_id,
            "model_id": binding.model_id,
            "default_language": binding.default_language,
            "request_count": request_count,
            "character_count": int(binding.character_count),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "accounted": accounted,
            "completion_rate": completion_rate,
            "elapsed_seconds": elapsed_seconds,
            "retry_events": retry_events,
            "files_per_minute": files_per_minute,
            "characters_per_minute": characters_per_minute,
            "verified_files": verified_files,
            "artifact_issue_count": artifact_issue_count,
            "artifact_status": artifact_status,
            "artifact_receipt_digest": artifact_receipt_digest,
            "execution_receipt_id": execution_receipt_id,
            "resume_run": resume_run,
            "parent_run_id": parent_run_id,
            "health": health,
            "captured_at": _utc_iso(),
        }
        payload = dict(material)
        payload["snapshot_digest"] = _digest(material)

        self._write_idempotent(
            path,
            payload,
            digest_key="snapshot_digest",
        )
        return self.load_snapshot(path)

    def rollup_project(
        self,
        evidence_root: Path,
        project_key: str,
    ) -> IntelligentTTSOperationsRollup:
        project_dir = self.project_dir(
            evidence_root,
            project_key,
        )
        snapshots: list[IntelligentTTSOperationsSnapshot] = []
        invalid_snapshot_count = 0

        if project_dir.exists():
            for path in sorted(
                project_dir.glob(
                    "*.intelligent-tts-operations.json"
                )
            ):
                try:
                    snapshots.append(
                        self.load_snapshot(path)
                    )
                except IntelligentTTSOperationsIntegrityError:
                    invalid_snapshot_count += 1

        total_runs = len(snapshots)
        completed_runs = sum(
            1 for item in snapshots
            if item.result == "completed"
        )
        failed_runs = sum(
            1 for item in snapshots
            if item.result == "failed"
        )
        cancelled_runs = sum(
            1 for item in snapshots
            if item.result in {"cancelled", "canceled"}
        )

        request_count = sum(
            item.request_count for item in snapshots
        )
        completed_jobs = sum(
            item.completed for item in snapshots
        )
        failed_jobs = sum(
            item.failed for item in snapshots
        )
        skipped_jobs = sum(
            item.skipped for item in snapshots
        )
        completion_rate = (
            completed_jobs / request_count
            if request_count
            else 0.0
        )
        verified_files = sum(
            item.verified_files for item in snapshots
        )
        artifact_issue_count = sum(
            item.artifact_issue_count
            for item in snapshots
        )
        resume_runs = sum(
            1 for item in snapshots if item.resume_run
        )
        retry_events = sum(
            item.retry_events for item in snapshots
        )

        average_elapsed_seconds = self._average(
            item.elapsed_seconds for item in snapshots
        )
        average_files_per_minute = self._average(
            item.files_per_minute for item in snapshots
        )
        average_characters_per_minute = self._average(
            item.characters_per_minute
            for item in snapshots
        )

        healthy_runs = sum(
            1 for item in snapshots
            if item.health == "healthy"
        )
        warning_runs = sum(
            1 for item in snapshots
            if item.health == "warning"
        )
        attention_runs = sum(
            1 for item in snapshots
            if item.health == "attention"
        )

        latest = (
            max(
                snapshots,
                key=lambda item: item.captured_at,
            )
            if snapshots
            else None
        )

        if invalid_snapshot_count or attention_runs:
            health = "attention"
        elif warning_runs:
            health = "warning"
        elif snapshots:
            health = "healthy"
        else:
            health = "empty"

        material = {
            "schema_version": OPERATIONS_ROLLUP_SCHEMA_VERSION,
            "project_key": str(project_key),
            "total_runs": total_runs,
            "completed_runs": completed_runs,
            "failed_runs": failed_runs,
            "cancelled_runs": cancelled_runs,
            "request_count": request_count,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
            "skipped_jobs": skipped_jobs,
            "completion_rate": completion_rate,
            "verified_files": verified_files,
            "artifact_issue_count": artifact_issue_count,
            "resume_runs": resume_runs,
            "retry_events": retry_events,
            "average_elapsed_seconds": average_elapsed_seconds,
            "average_files_per_minute": average_files_per_minute,
            "average_characters_per_minute": (
                average_characters_per_minute
            ),
            "healthy_runs": healthy_runs,
            "warning_runs": warning_runs,
            "attention_runs": attention_runs,
            "invalid_snapshot_count": invalid_snapshot_count,
            "latest_run_id": (
                latest.run_id if latest is not None else None
            ),
            "latest_result": (
                latest.result if latest is not None else None
            ),
            "health": health,
            "generated_at": _utc_iso(),
        }
        payload = dict(material)
        payload["rollup_digest"] = _digest(material)

        path = self.rollup_path(
            evidence_root,
            project_key,
        )
        self._write_replace(path, payload)
        return self.load_rollup(path)

    def load_snapshot(
        self,
        path: Path,
    ) -> IntelligentTTSOperationsSnapshot:
        source = self._read_verified(
            Path(path),
            "snapshot_digest",
        )
        return IntelligentTTSOperationsSnapshot(
            schema_version=int(source["schema_version"]),
            run_id=str(source["run_id"]),
            project_key=str(source["project_key"]),
            result=str(source["result"]),
            manifest_digest=str(source["manifest_digest"]),
            authority_digest=str(source["authority_digest"]),
            provider=str(source["provider"]),
            profile_id=(
                None
                if source.get("profile_id") is None
                else str(source["profile_id"])
            ),
            voice_id=str(source["voice_id"]),
            model_id=str(source["model_id"]),
            default_language=str(
                source["default_language"]
            ),
            request_count=int(source["request_count"]),
            character_count=int(source["character_count"]),
            completed=int(source["completed"]),
            failed=int(source["failed"]),
            skipped=int(source["skipped"]),
            accounted=int(source["accounted"]),
            completion_rate=float(
                source["completion_rate"]
            ),
            elapsed_seconds=float(
                source["elapsed_seconds"]
            ),
            retry_events=int(source["retry_events"]),
            files_per_minute=float(
                source["files_per_minute"]
            ),
            characters_per_minute=float(
                source["characters_per_minute"]
            ),
            verified_files=int(
                source["verified_files"]
            ),
            artifact_issue_count=int(
                source["artifact_issue_count"]
            ),
            artifact_status=str(
                source["artifact_status"]
            ),
            artifact_receipt_digest=(
                None
                if source.get(
                    "artifact_receipt_digest"
                ) is None
                else str(
                    source["artifact_receipt_digest"]
                )
            ),
            execution_receipt_id=(
                None
                if source.get(
                    "execution_receipt_id"
                ) is None
                else str(
                    source["execution_receipt_id"]
                )
            ),
            resume_run=bool(source["resume_run"]),
            parent_run_id=(
                None
                if source.get("parent_run_id") is None
                else str(source["parent_run_id"])
            ),
            health=str(source["health"]),
            captured_at=str(source["captured_at"]),
            snapshot_digest=str(
                source["snapshot_digest"]
            ),
            path=Path(path),
        )

    def load_rollup(
        self,
        path: Path,
    ) -> IntelligentTTSOperationsRollup:
        source = self._read_verified(
            Path(path),
            "rollup_digest",
        )
        return IntelligentTTSOperationsRollup(
            schema_version=int(source["schema_version"]),
            project_key=str(source["project_key"]),
            total_runs=int(source["total_runs"]),
            completed_runs=int(
                source["completed_runs"]
            ),
            failed_runs=int(source["failed_runs"]),
            cancelled_runs=int(
                source["cancelled_runs"]
            ),
            request_count=int(source["request_count"]),
            completed_jobs=int(
                source["completed_jobs"]
            ),
            failed_jobs=int(source["failed_jobs"]),
            skipped_jobs=int(source["skipped_jobs"]),
            completion_rate=float(
                source["completion_rate"]
            ),
            verified_files=int(
                source["verified_files"]
            ),
            artifact_issue_count=int(
                source["artifact_issue_count"]
            ),
            resume_runs=int(source["resume_runs"]),
            retry_events=int(source["retry_events"]),
            average_elapsed_seconds=float(
                source["average_elapsed_seconds"]
            ),
            average_files_per_minute=float(
                source["average_files_per_minute"]
            ),
            average_characters_per_minute=float(
                source[
                    "average_characters_per_minute"
                ]
            ),
            healthy_runs=int(source["healthy_runs"]),
            warning_runs=int(source["warning_runs"]),
            attention_runs=int(
                source["attention_runs"]
            ),
            invalid_snapshot_count=int(
                source["invalid_snapshot_count"]
            ),
            latest_run_id=(
                None
                if source.get("latest_run_id") is None
                else str(source["latest_run_id"])
            ),
            latest_result=(
                None
                if source.get("latest_result") is None
                else str(source["latest_result"])
            ),
            health=str(source["health"]),
            generated_at=str(source["generated_at"]),
            rollup_digest=str(source["rollup_digest"]),
            path=Path(path),
        )

    @staticmethod
    def project_dir(
        evidence_root: Path,
        project_key: str,
    ) -> Path:
        return (
            Path(evidence_root)
            / _safe_component(project_key, "project")
        )

    @classmethod
    def snapshot_path(
        cls,
        evidence_root: Path,
        project_key: str,
        run_id: str,
    ) -> Path:
        return (
            cls.project_dir(
                evidence_root,
                project_key,
            )
            / (
                _safe_component(run_id, "run")
                + ".intelligent-tts-operations.json"
            )
        )

    @classmethod
    def rollup_path(
        cls,
        evidence_root: Path,
        project_key: str,
    ) -> Path:
        return (
            cls.project_dir(
                evidence_root,
                project_key,
            )
            / "project-operations-rollup.json"
        )

    @staticmethod
    def _average(values: Any) -> float:
        items = [float(value) for value in values]
        if not items:
            return 0.0
        return sum(items) / len(items)

    @staticmethod
    def _health(
        result: str,
        *,
        failed: int,
        skipped: int,
        artifact_issue_count: int,
        request_count: int,
        accounted: int,
    ) -> str:
        if (
            artifact_issue_count
            or failed
            or accounted > request_count
        ):
            return "attention"
        if (
            result != "completed"
            or skipped
            or accounted < request_count
        ):
            return "warning"
        return "healthy"

    @staticmethod
    def _read_verified(
        path: Path,
        digest_key: str,
    ) -> dict[str, Any]:
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise IntelligentTTSOperationsIntegrityError(
                f"Unable to read operations evidence: {exc}"
            ) from exc

        material = dict(payload)
        actual = str(material.pop(digest_key, ""))
        expected = _digest(material)
        if actual != expected:
            raise IntelligentTTSOperationsIntegrityError(
                "Operations evidence digest mismatch"
            )
        return payload

    @staticmethod
    def _write_idempotent(
        path: Path,
        payload: Mapping[str, Any],
        *,
        digest_key: str,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                existing = json.loads(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise IntelligentTTSOperationsIntegrityError(
                    f"Unable to read existing operations evidence: {exc}"
                ) from exc
            if (
                str(existing.get(digest_key) or "")
                == str(payload.get(digest_key) or "")
            ):
                return
            raise IntelligentTTSOperationsIntelligenceError(
                "Operations evidence path already contains different data"
            )
        IntelligentTTSOperationsIntelligenceService._write_replace(
            path,
            payload,
        )

    @staticmethod
    def _write_replace(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
