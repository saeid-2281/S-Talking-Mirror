from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import AppSettings, TTSJob
from app.models.generation_execution_session import (
    GenerationExecutionJob,
    GenerationExecutionSession,
    GenerationExecutionSessionSummary,
)


class GenerationExecutionSessionService:
    """Create, update, verify, discover, and export real generation run sessions."""

    FILE_NAME = "generation-execution.json"
    MARKDOWN_NAME = "generation-execution.md"
    SCHEMA_VERSION = 1
    SECRET_VALUE = re.compile(
        r"(sk[_-][A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*[\'\"]?[^\'\"\s,;}]+)",
        re.IGNORECASE,
    )

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def new_run_id(launch_fingerprint: str = "") -> str:
        now = datetime.now(timezone.utc)
        suffix = re.sub(r"[^a-fA-F0-9]", "", str(launch_fingerprint or ""))[:10].lower()
        if not suffix:
            suffix = hashlib.sha256(now.isoformat().encode("utf-8")).hexdigest()[:10]
        return f"run-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{suffix}-{uuid.uuid4().hex[:6]}"

    def start_session(
        self,
        *,
        run_id: str,
        project_name: str,
        project_id: int | None,
        project_key: str,
        launch_receipt_path: Path | None,
        launch_receipt_id: str,
        launch_fingerprint: str,
        decision_trace_id: str,
        guard_approval_id: str,
        settings: AppSettings,
        jobs: Iterable[TTSJob],
        output_directory: Path,
        started_at: datetime | None = None,
        initial_status: str = "running",
    ) -> GenerationExecutionSession:
        started = started_at or datetime.now(timezone.utc)
        folder = self._session_folder(project_name, run_id)
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": run_id,
            "status": str(initial_status or "running"),
            "project": {
                "name": project_name,
                "id": project_id,
                "key": project_key,
            },
            "launch": {
                "receipt_id": launch_receipt_id,
                "receipt_path": str(launch_receipt_path or ""),
                "fingerprint": launch_fingerprint,
                "decision_trace_id": decision_trace_id,
                "guard_approval_id": guard_approval_id,
            },
            "settings": {
                "provider": settings.provider,
                "model_id": settings.model_id,
                "voice_id": settings.voice_id,
                "generation_scope": settings.generation_scope,
                "execution_order": settings.execution_order,
            },
            "output_directory": str(Path(output_directory)),
            "report_path": "",
            "started_at": started.isoformat(),
            "updated_at": started.isoformat(),
            "finished_at": "",
            "metrics": {},
            "jobs": [self._job_payload(job, settings, output_directory) for job in jobs],
        }
        self._refresh_metrics(payload)
        self._write(folder, payload)
        return self.load(folder / self.FILE_NAME)

    def sync_session(
        self,
        run_id: str,
        jobs: Iterable[TTSJob],
        *,
        project_name: str,
        settings: AppSettings,
        output_directory: Path,
        status: str | None = None,
        elapsed_seconds: float | None = None,
        retry_events: int | None = None,
    ) -> GenerationExecutionSession:
        path = self.path_for(project_name, run_id)
        payload = self._read_payload(path)
        payload["jobs"] = [self._job_payload(job, settings, output_directory) for job in jobs]
        if status:
            payload["status"] = status
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        metrics = payload.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
            payload["metrics"] = metrics
        if elapsed_seconds is not None:
            metrics["elapsed_seconds"] = max(0.0, float(elapsed_seconds))
        if retry_events is not None:
            metrics["retry_events"] = max(0, int(retry_events))
        self._refresh_metrics(payload)
        self._write(path.parent, payload)
        return self.load(path)

    def finish_session(
        self,
        run_id: str,
        jobs: Iterable[TTSJob],
        *,
        project_name: str,
        settings: AppSettings,
        output_directory: Path,
        result: str,
        report_path: Path | None = None,
        monitor_metrics: dict[str, object] | None = None,
    ) -> GenerationExecutionSession:
        path = self.path_for(project_name, run_id)
        payload = self._read_payload(path)
        payload["status"] = self._normalize_result(result)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload["finished_at"] = payload["updated_at"]
        payload["report_path"] = str(report_path or "")
        payload["jobs"] = [self._job_payload(job, settings, output_directory) for job in jobs]
        metrics = payload.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
            payload["metrics"] = metrics
        for key in ("elapsed_seconds", "retry_events"):
            if monitor_metrics and key in monitor_metrics:
                metrics[key] = monitor_metrics[key]
        self._refresh_metrics(payload)
        self._write(path.parent, payload)
        return self.load(path)

    def load(self, path: Path) -> GenerationExecutionSession:
        file_path = Path(path)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Execution session root must be a JSON object.")
        except Exception as exc:
            return GenerationExecutionSession(
                path=file_path,
                markdown_path=file_path.with_name(self.MARKDOWN_NAME),
                integrity_status="unreadable",
                integrity_message=f"Execution session could not be read: {exc}",
            )
        integrity_status, integrity_message = self.verify_payload(payload)
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        launch = payload.get("launch") if isinstance(payload.get("launch"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        jobs = tuple(
            self._job_from_payload(item)
            for item in payload.get("jobs", [])
            if isinstance(item, dict)
        )
        return GenerationExecutionSession(
            path=file_path,
            markdown_path=file_path.with_name(self.MARKDOWN_NAME),
            schema_version=self._integer(payload.get("schema_version"), 1),
            run_id=str(payload.get("run_id") or ""),
            status=str(payload.get("status") or "unknown"),
            project_name=str(project.get("name") or ""),
            project_id=self._optional_integer(project.get("id")),
            project_key=str(project.get("key") or ""),
            launch_receipt_id=str(launch.get("receipt_id") or ""),
            launch_receipt_path=str(launch.get("receipt_path") or ""),
            launch_fingerprint=str(launch.get("fingerprint") or ""),
            decision_trace_id=str(launch.get("decision_trace_id") or ""),
            guard_approval_id=str(launch.get("guard_approval_id") or ""),
            provider=str(settings.get("provider") or ""),
            model_id=str(settings.get("model_id") or ""),
            voice_id=str(settings.get("voice_id") or ""),
            generation_scope=str(settings.get("generation_scope") or ""),
            execution_order=str(settings.get("execution_order") or ""),
            output_directory=str(payload.get("output_directory") or ""),
            report_path=str(payload.get("report_path") or ""),
            started_at=str(payload.get("started_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            total_jobs=self._integer(metrics.get("total_jobs")),
            pending_jobs=self._integer(metrics.get("pending_jobs")),
            running_jobs=self._integer(metrics.get("running_jobs")),
            completed_jobs=self._integer(metrics.get("completed_jobs")),
            failed_jobs=self._integer(metrics.get("failed_jobs")),
            skipped_jobs=self._integer(metrics.get("skipped_jobs")),
            total_characters=self._integer(metrics.get("total_characters")),
            processed_characters=self._integer(metrics.get("processed_characters")),
            retry_events=self._integer(metrics.get("retry_events")),
            elapsed_seconds=self._number(metrics.get("elapsed_seconds")),
            jobs=jobs,
            integrity_status=integrity_status,
            integrity_message=integrity_message,
        )

    def list_sessions(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
        search: str = "",
        limit: int = 1000,
    ) -> list[GenerationExecutionSession]:
        paths = list(self.reports_dir.rglob(self.FILE_NAME))
        sessions = [self.load(path) for path in paths]
        project_key = str(project_name or "").strip().casefold()
        status_key = str(status or "").strip().casefold()
        search_key = str(search or "").strip().casefold()
        filtered: list[GenerationExecutionSession] = []
        for session in sessions:
            if project_key and session.project_name.casefold() != project_key:
                continue
            if status_key and session.status.casefold() != status_key:
                continue
            if search_key and search_key not in self._search_text(session):
                continue
            filtered.append(session)
        filtered.sort(key=lambda item: (item.started_at, item.run_id), reverse=True)
        return filtered[: max(0, int(limit))]

    @staticmethod
    def summary(sessions: Iterable[GenerationExecutionSession]) -> GenerationExecutionSessionSummary:
        records = list(sessions)
        return GenerationExecutionSessionSummary(
            total_count=len(records),
            running_count=sum(item.status in {"starting", "running", "paused", "stopping"} for item in records),
            completed_count=sum(item.status == "completed" for item in records),
            partial_count=sum(item.status == "partial" for item in records),
            failed_count=sum(item.status == "failed" for item in records),
            cancelled_count=sum(item.status == "cancelled" for item in records),
            integrity_issue_count=sum(item.integrity_status in {"mismatch", "unreadable"} for item in records),
            total_jobs=sum(item.total_jobs for item in records),
            completed_jobs=sum(item.completed_jobs for item in records),
            failed_jobs=sum(item.failed_jobs for item in records),
            skipped_jobs=sum(item.skipped_jobs for item in records),
        )

    def export(
        self,
        sessions: Iterable[GenerationExecutionSession],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        records = list(sessions)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe = self._safe_name(project_name)
        json_path = target / f"generation-execution-sessions-{safe}-{stamp}.json"
        csv_path = target / f"generation-execution-sessions-{safe}-{stamp}.csv"
        rows = [self._export_row(item) for item in records]
        json_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "summary": asdict(self.summary(records)),
                    "sessions": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fieldnames = list(rows[0]) if rows else list(self._export_row(GenerationExecutionSession(Path(""), Path(""))))
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path

    def path_for(self, project_name: str, run_id: str) -> Path:
        return self._session_folder(project_name, run_id) / self.FILE_NAME

    @staticmethod
    def canonical_digest(payload: dict[str, object]) -> str:
        clean = dict(payload)
        clean.pop("integrity", None)
        serialized = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @classmethod
    def verify_payload(cls, payload: dict[str, object]) -> tuple[str, str]:
        integrity = payload.get("integrity")
        if not isinstance(integrity, dict):
            return "legacy", "Execution session predates integrity metadata."
        expected = str(integrity.get("digest") or "")
        actual = cls.canonical_digest(payload)
        if expected and expected == actual:
            return "verified", "Execution session integrity verified."
        return "mismatch", "Execution session content does not match its SHA-256 digest."

    def _write(self, folder: Path, payload: dict[str, object]) -> None:
        payload["integrity"] = {
            "algorithm": "sha256",
            "digest": self.canonical_digest(payload),
        }
        (folder / self.FILE_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (folder / self.MARKDOWN_NAME).write_text(self._markdown(payload), encoding="utf-8")

    def _read_payload(self, path: Path) -> dict[str, object]:
        if not path.exists():
            raise FileNotFoundError(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Execution session root must be a JSON object.")
        payload.pop("integrity", None)
        return payload

    def _session_folder(self, project_name: str, run_id: str) -> Path:
        return self.reports_dir / self._safe_name(project_name) / "runs" / self._safe_name(run_id)

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._") or "unknown"

    @staticmethod
    def _normalize_result(result: str) -> str:
        value = str(result or "").strip().casefold()
        aliases = {"stopped": "cancelled", "stop": "cancelled", "error": "failed"}
        value = aliases.get(value, value)
        return value if value in {"completed", "partial", "failed", "cancelled"} else "completed"

    @staticmethod
    def _job_payload(job: TTSJob, settings: AppSettings, output_directory: Path) -> dict[str, object]:
        output_path = str(job.generated_output_path or job.output_path(Path(output_directory), settings.file_extension))
        return {
            "row_number": job.row_number,
            "filename": job.filename,
            "source_id": job.source_id or "",
            "source_name": job.source_display_name or "",
            "source_sheet": job.source_sheet or "",
            "source_row": job.source_row,
            "character_count": job.character_count,
            "status": job.status.value,
            "retry_count": job.retry_count,
            "duration_seconds": job.duration_seconds,
            "output_path": output_path,
            "error": GenerationExecutionSessionService._sanitize_text(job.error or ""),
            "error_code": job.error_code or "",
            "error_fingerprint": job.error_fingerprint or "",
            "provider": job.provider_override or settings.provider,
            "model_id": job.model_override or settings.model_id,
            "voice_id": job.voice_override or settings.voice_id,
        }

    @staticmethod
    def _job_from_payload(payload: dict[str, object]) -> GenerationExecutionJob:
        return GenerationExecutionJob(
            row_number=GenerationExecutionSessionService._integer(payload.get("row_number")),
            filename=str(payload.get("filename") or ""),
            source_id=str(payload.get("source_id") or ""),
            source_name=str(payload.get("source_name") or ""),
            source_sheet=str(payload.get("source_sheet") or ""),
            source_row=GenerationExecutionSessionService._optional_integer(payload.get("source_row")),
            character_count=GenerationExecutionSessionService._integer(payload.get("character_count")),
            status=str(payload.get("status") or "pending"),
            retry_count=GenerationExecutionSessionService._integer(payload.get("retry_count")),
            duration_seconds=GenerationExecutionSessionService._number(payload.get("duration_seconds")),
            output_path=str(payload.get("output_path") or ""),
            error=str(payload.get("error") or ""),
            error_code=str(payload.get("error_code") or ""),
            error_fingerprint=str(payload.get("error_fingerprint") or ""),
            provider=str(payload.get("provider") or ""),
            model_id=str(payload.get("model_id") or ""),
            voice_id=str(payload.get("voice_id") or ""),
        )

    @staticmethod
    def _refresh_metrics(payload: dict[str, object]) -> None:
        jobs = payload.get("jobs") if isinstance(payload.get("jobs"), list) else []
        statuses = [str(item.get("status") or "pending") for item in jobs if isinstance(item, dict)]
        metrics = payload.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
            payload["metrics"] = metrics
        metrics.update(
            {
                "total_jobs": len(jobs),
                "pending_jobs": statuses.count("pending"),
                "running_jobs": statuses.count("running"),
                "completed_jobs": statuses.count("completed"),
                "failed_jobs": statuses.count("failed"),
                "skipped_jobs": statuses.count("skipped"),
                "total_characters": sum(
                    GenerationExecutionSessionService._integer(item.get("character_count"))
                    for item in jobs
                    if isinstance(item, dict)
                ),
                "processed_characters": sum(
                    GenerationExecutionSessionService._integer(item.get("character_count"))
                    for item in jobs
                    if isinstance(item, dict)
                    and str(item.get("status") or "") in {"completed", "failed", "skipped"}
                ),
                "retry_events": GenerationExecutionSessionService._integer(metrics.get("retry_events")),
                "elapsed_seconds": GenerationExecutionSessionService._number(metrics.get("elapsed_seconds")),
            }
        )

    @staticmethod
    def _search_text(session: GenerationExecutionSession) -> str:
        return " ".join(
            (
                session.run_id,
                session.status,
                session.project_name,
                session.project_key,
                session.launch_receipt_id,
                session.launch_fingerprint,
                session.decision_trace_id,
                session.guard_approval_id,
                session.provider,
                session.model_id,
                session.voice_id,
                session.output_directory,
                session.report_path,
                " ".join(job.filename for job in session.jobs),
            )
        ).casefold()

    @staticmethod
    def _export_row(session: GenerationExecutionSession) -> dict[str, object]:
        return {
            "run_id": session.run_id,
            "status": session.status,
            "project_name": session.project_name,
            "project_id": session.project_id,
            "project_key": session.project_key,
            "launch_receipt_id": session.launch_receipt_id,
            "launch_receipt_path": session.launch_receipt_path,
            "launch_fingerprint": session.launch_fingerprint,
            "decision_trace_id": session.decision_trace_id,
            "guard_approval_id": session.guard_approval_id,
            "provider": session.provider,
            "model_id": session.model_id,
            "voice_id": session.voice_id,
            "generation_scope": session.generation_scope,
            "execution_order": session.execution_order,
            "output_directory": session.output_directory,
            "report_path": session.report_path,
            "started_at": session.started_at,
            "updated_at": session.updated_at,
            "finished_at": session.finished_at,
            "total_jobs": session.total_jobs,
            "completed_jobs": session.completed_jobs,
            "failed_jobs": session.failed_jobs,
            "skipped_jobs": session.skipped_jobs,
            "retry_events": session.retry_events,
            "elapsed_seconds": session.elapsed_seconds,
            "integrity_status": session.integrity_status,
            "session_path": str(session.path),
        }

    @staticmethod
    def _markdown(payload: dict[str, object]) -> str:
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        launch = payload.get("launch") if isinstance(payload.get("launch"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        lines = [
            "# S Talking Generation Execution Session",
            "",
            f"- Run ID: `{payload.get('run_id', '')}`",
            f"- Status: {payload.get('status', 'unknown')}",
            f"- Project: {project.get('name', '')}",
            f"- Started: {payload.get('started_at', '')}",
            f"- Finished: {payload.get('finished_at', '') or 'In progress'}",
            f"- Launch receipt: `{launch.get('receipt_id', '')}`",
            f"- Decision trace: `{launch.get('decision_trace_id', '')}`",
            f"- Provider: {settings.get('provider', '')}",
            f"- Model: {settings.get('model_id', '')}",
            f"- Voice: {settings.get('voice_id', '')}",
            f"- Output: {payload.get('output_directory', '')}",
            f"- Jobs: {metrics.get('total_jobs', 0)} total / {metrics.get('completed_jobs', 0)} completed / {metrics.get('failed_jobs', 0)} failed / {metrics.get('skipped_jobs', 0)} skipped",
            "",
            "## Jobs",
        ]
        for item in payload.get("jobs", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- Row {item.get('row_number', 0)} · {item.get('filename', '')} · "
                f"{item.get('status', 'pending')} · retries {item.get('retry_count', 0)}"
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _sanitize_text(value: str) -> str:
        return GenerationExecutionSessionService.SECRET_VALUE.sub("[REDACTED]", str(value or ""))

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _number(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
