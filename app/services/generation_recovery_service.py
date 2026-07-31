from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.domain import AppSettings, JobStatus, TTSJob
from app.models.generation_recovery import GenerationRecoverySnapshot
from app.models.generation_session import GenerationSession


class GenerationRecoveryService:
    """Atomically persist and validate one resumable generation session."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        *,
        session: GenerationSession,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        project_key: str,
    ) -> GenerationRecoverySnapshot:
        body: dict[str, Any] = {
            "version": self.VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "project_key": str(project_key),
            "provider": settings.provider,
            "profile_id": settings.active_api_profile_id,
            "model_id": settings.model_id,
            "voice_id": settings.voice_id,
            "output_dir": str(output_dir),
            "session": session.__dict__,
            "jobs": [job.model_dump(mode="json") for job in jobs],
        }
        body["checksum"] = self._checksum(body)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self._snapshot(body)

    def load(self) -> GenerationRecoverySnapshot | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
            return None
        checksum = str(payload.get("checksum") or "")
        if not checksum or checksum != self._checksum(payload):
            return None
        try:
            return self._snapshot(payload)
        except (KeyError, TypeError, ValueError):
            return None

    def restore_jobs(
        self,
        snapshot: GenerationRecoverySnapshot,
        *,
        retry_failed: bool = False,
    ) -> list[TTSJob]:
        restored: list[TTSJob] = []
        for raw in snapshot.jobs:
            job = TTSJob.model_validate(raw)
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.PENDING
                job.error = "Recovered after interrupted generation."
            elif retry_failed and job.status == JobStatus.FAILED:
                job.status = JobStatus.PENDING
                job.error = None
            restored.append(job)
        return restored

    def is_compatible(
        self,
        snapshot: GenerationRecoverySnapshot,
        *,
        settings: AppSettings,
        project_key: str,
    ) -> bool:
        return (
            snapshot.project_key == str(project_key)
            and snapshot.provider == settings.provider
            and snapshot.profile_id == settings.active_api_profile_id
            and snapshot.model_id == settings.model_id
            and snapshot.voice_id == settings.voice_id
        )

    def incompatibility_reason(
        self,
        snapshot: GenerationRecoverySnapshot,
        *,
        settings: AppSettings,
        project_key: str,
    ) -> str:
        mismatches: list[str] = []
        if snapshot.project_key != str(project_key):
            mismatches.append("project")
        if snapshot.provider != settings.provider:
            mismatches.append("provider")
        if snapshot.profile_id != settings.active_api_profile_id:
            mismatches.append("API profile")
        if snapshot.model_id != settings.model_id:
            mismatches.append("model")
        if snapshot.voice_id != settings.voice_id:
            mismatches.append("voice")
        if not mismatches:
            return ""
        return "Snapshot mismatch: " + ", ".join(mismatches) + "."

    def discard(self) -> None:
        self.path.unlink(missing_ok=True)
        self.path.with_suffix(self.path.suffix + ".tmp").unlink(missing_ok=True)

    @staticmethod
    def _checksum(payload: dict[str, Any]) -> str:
        clean = {key: value for key, value in payload.items() if key != "checksum"}
        canonical = json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _snapshot(payload: dict[str, Any]) -> GenerationRecoverySnapshot:
        return GenerationRecoverySnapshot(
            version=int(payload["version"]),
            saved_at=str(payload["saved_at"]),
            project_key=str(payload["project_key"]),
            provider=str(payload["provider"]),
            profile_id=(
                str(payload["profile_id"])
                if payload.get("profile_id") is not None
                else None
            ),
            model_id=str(payload.get("model_id") or ""),
            voice_id=str(payload.get("voice_id") or ""),
            output_dir=str(payload.get("output_dir") or ""),
            session=dict(payload.get("session") or {}),
            jobs=tuple(dict(job) for job in payload.get("jobs") or []),
            checksum=str(payload["checksum"]),
        )
