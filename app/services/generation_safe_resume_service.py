from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import AppSettings, JobStatus, TTSJob
from app.models.generation_execution_receipt import GenerationExecutionReceipt
from app.models.generation_safe_resume import (
    GenerationResumeCandidate,
    GenerationResumePreview,
    GenerationResumeReceipt,
)


class GenerationSafeResumeService:
    """Plan, persist, verify, and apply safe recovery of historical execution runs."""

    FILE_NAME = "generation-resume.json"
    MARKDOWN_NAME = "generation-resume.md"
    SCHEMA_VERSION = 1
    SCOPES = {
        "unresolved": "Failed, missing, and incomplete",
        "failed_only": "Failed only",
        "missing_only": "Missing outputs only",
        "incomplete_only": "Incomplete only",
        "entire_run": "Entire parent run",
    }
    SECRET_VALUE = re.compile(
        r"(sk[_-][A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;}]+)",
        re.IGNORECASE,
    )

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def preview(
        self,
        *,
        receipt: GenerationExecutionReceipt,
        current_jobs: Iterable[TTSJob],
        settings: AppSettings,
        output_directory: Path,
        project_name: str,
        scope: str = "unresolved",
    ) -> GenerationResumePreview:
        normalized_scope = scope if scope in self.SCOPES else "unresolved"
        blockers: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []
        current_output = Path(output_directory)

        if receipt.integrity_status != "verified":
            blockers.append("The parent execution receipt must pass integrity verification before recovery.")
        if receipt.project_name.casefold() != str(project_name or "").casefold():
            blockers.append("The selected receipt belongs to a different project.")
        if receipt.status not in {"partial", "failed", "cancelled", "completed"}:
            blockers.append(f"Execution status '{receipt.status}' is not recoverable.")
        if receipt.provider and receipt.provider != settings.provider:
            blockers.append(f"Provider changed from {receipt.provider} to {settings.provider}.")
        if receipt.model_id and receipt.model_id != settings.model_id:
            blockers.append(f"Model changed from {receipt.model_id} to {settings.model_id}.")
        if receipt.voice_id and receipt.voice_id != settings.voice_id:
            blockers.append(f"Voice changed from {receipt.voice_id} to {settings.voice_id}.")
        if receipt.output_directory and not self._same_path(Path(receipt.output_directory), current_output):
            blockers.append("Output directory differs from the parent run.")

        parent_jobs = self._parent_job_metadata(receipt.execution_session_path)
        jobs_by_row = {job.row_number: job for job in current_jobs}
        jobs_by_name = {self._filename_key(job.filename): job for job in current_jobs}
        candidates: list[GenerationResumeCandidate] = []
        selected_rows: list[int] = []
        missing_matches = 0

        for entry in receipt.entries:
            if entry.disposition == "unexpected":
                continue
            current = jobs_by_row.get(entry.row_number)
            if current is None:
                current = jobs_by_name.get(self._filename_key(entry.filename))
            selected = self._selected_for_scope(entry.disposition, normalized_scope)
            found = current is not None
            parent_meta = parent_jobs.get(entry.row_number, {})
            parent_characters = self._integer(parent_meta.get("character_count"))
            current_characters = current.character_count if current is not None else 0
            if selected and not found:
                missing_matches += 1
            if selected and found:
                current_expected = current.output_path(current_output, settings.file_extension)
                if entry.expected_path and not self._same_path(Path(entry.expected_path), current_expected):
                    blockers.append(
                        f"Output mapping changed for row {current.row_number}: {entry.filename}."
                    )
                if parent_characters and parent_characters != current.character_count:
                    blockers.append(
                        f"Source character count changed for row {current.row_number}: {parent_characters} to {current.character_count}."
                    )
                selected_rows.append(current.row_number)
            actual = Path(entry.actual_path or entry.expected_path) if (entry.actual_path or entry.expected_path) else None
            output_exists = bool(actual and actual.is_file())
            reason = self._candidate_reason(entry.disposition, selected, found, output_exists)
            candidates.append(
                GenerationResumeCandidate(
                    row_number=current.row_number if current is not None else entry.row_number,
                    filename=current.filename if current is not None else entry.filename,
                    parent_disposition=entry.disposition,
                    parent_job_status=entry.job_status,
                    expected_path=entry.expected_path,
                    actual_path=entry.actual_path,
                    output_exists=output_exists,
                    parent_character_count=parent_characters,
                    current_character_count=current_characters,
                    selected=selected,
                    current_job_found=found,
                    reason=reason,
                )
            )

        if missing_matches:
            blockers.append(f"{missing_matches} selected parent job(s) could not be matched to the current queue.")
        if not selected_rows:
            blockers.append("The selected recovery scope contains no eligible jobs.")

        selected_candidates = [item for item in candidates if item.selected and item.current_job_found]
        existing_selected = [item for item in selected_candidates if item.output_exists]
        if existing_selected:
            if not settings.skip_existing and not settings.overwrite_existing:
                blockers.append(
                    "Selected recovery jobs include existing outputs, but neither Skip existing nor Overwrite is enabled."
                )
            elif settings.overwrite_existing:
                warnings.append(f"{len(existing_selected)} selected output(s) may be overwritten.")
            elif settings.skip_existing:
                warnings.append(f"{len(existing_selected)} selected output(s) will be protected by Skip existing.")

        if normalized_scope == "entire_run":
            warnings.append("Entire-run recovery may revisit outputs that were already completed in the parent run.")
        if receipt.unexpected_outputs:
            warnings.append(
                f"The parent run contains {receipt.unexpected_outputs} unexpected output(s); they are not selected for recovery."
            )
        recommendations.extend(
            (
                "Run Unified Preflight again before starting the recovery run.",
                "Keep the original provider, model, voice, and output directory until recovery completes.",
                "Use Failed/Missing/Incomplete scope instead of Entire run whenever possible.",
            )
        )
        return GenerationResumePreview(
            project_name=project_name,
            parent_run_id=receipt.run_id,
            parent_execution_receipt_id=receipt.receipt_id,
            parent_execution_receipt_path=str(receipt.path),
            scope=normalized_scope,
            provider=settings.provider,
            model_id=settings.model_id,
            voice_id=settings.voice_id,
            output_directory=str(current_output),
            skip_existing=settings.skip_existing,
            overwrite_existing=settings.overwrite_existing,
            selected_rows=tuple(sorted(set(selected_rows))),
            candidates=tuple(candidates),
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            recommendations=tuple(dict.fromkeys(recommendations)),
        )

    def compatibility_issues(
        self,
        receipt: GenerationResumeReceipt,
        *,
        current_jobs: Iterable[TTSJob],
        settings: AppSettings,
        output_directory: Path,
        project_name: str,
    ) -> tuple[str, ...]:
        issues: list[str] = []
        if receipt.integrity_status != "verified":
            issues.append("resume receipt integrity")
        if receipt.status != "planned":
            issues.append(f"resume status {receipt.status}")
        if receipt.project_name.casefold() != str(project_name or "").casefold():
            issues.append("project")
        if receipt.provider != settings.provider:
            issues.append("provider")
        if receipt.model_id != settings.model_id:
            issues.append("model")
        if receipt.voice_id != settings.voice_id:
            issues.append("voice")
        if receipt.skip_existing != settings.skip_existing or receipt.overwrite_existing != settings.overwrite_existing:
            issues.append("file policy")
        if not self._same_path(Path(receipt.output_directory), Path(output_directory)):
            issues.append("output directory")
        jobs_by_row = {job.row_number: job for job in current_jobs}
        selected_candidates = {item.row_number: item for item in receipt.candidates if item.selected}
        for row in receipt.selected_rows:
            job = jobs_by_row.get(row)
            candidate = selected_candidates.get(row)
            if job is None or candidate is None:
                issues.append(f"missing queue row {row}")
                continue
            if self._filename_key(job.filename) != self._filename_key(candidate.filename):
                issues.append(f"filename changed for row {row}")
            if candidate.current_character_count and job.character_count != candidate.current_character_count:
                issues.append(f"source changed for row {row}")
            current_expected = job.output_path(Path(output_directory), settings.file_extension)
            if candidate.expected_path and not self._same_path(Path(candidate.expected_path), current_expected):
                issues.append(f"output mapping changed for row {row}")
        return tuple(dict.fromkeys(issues))

    def create_receipt(
        self,
        preview: GenerationResumePreview,
        *,
        created_at: datetime | None = None,
    ) -> GenerationResumeReceipt:
        if not preview.allowed:
            raise ValueError("Blocked recovery previews cannot be persisted as resumable receipts.")
        now = created_at or datetime.now(timezone.utc)
        resume_id = f"resume-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
        folder = self._folder(preview.project_name, resume_id)
        folder.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "resume_id": resume_id,
            "status": "planned",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "started_at": "",
            "finished_at": "",
            "cancelled_at": "",
            "project_name": preview.project_name,
            "parent": {
                "run_id": preview.parent_run_id,
                "execution_receipt_id": preview.parent_execution_receipt_id,
                "execution_receipt_path": preview.parent_execution_receipt_path,
            },
            "new_run_id": "",
            "result": "",
            "execution_receipt_id": "",
            "execution_receipt_path": "",
            "scope": preview.scope,
            "settings": {
                "provider": preview.provider,
                "model_id": preview.model_id,
                "voice_id": preview.voice_id,
                "output_directory": preview.output_directory,
                "skip_existing": preview.skip_existing,
                "overwrite_existing": preview.overwrite_existing,
            },
            "selected_rows": list(preview.selected_rows),
            "candidates": [asdict(item) for item in preview.candidates],
            "blockers": list(preview.blockers),
            "warnings": list(preview.warnings),
            "recommendations": list(preview.recommendations),
        }
        self._write(folder, payload)
        return self.load(folder / self.FILE_NAME)

    def mark_started(self, receipt: GenerationResumeReceipt | Path, *, new_run_id: str) -> GenerationResumeReceipt:
        path = receipt.path if isinstance(receipt, GenerationResumeReceipt) else Path(receipt)
        current = self.load(path)
        if current.integrity_status != "verified" or current.status != "planned":
            raise ValueError("Only verified planned resume receipts can start a run.")
        payload = self._read_payload(path)
        now = datetime.now(timezone.utc).isoformat()
        payload["status"] = "started"
        payload["new_run_id"] = str(new_run_id)
        payload["started_at"] = now
        payload["updated_at"] = now
        self._write(path.parent, payload)
        return self.load(path)

    def mark_finished(
        self,
        receipt: GenerationResumeReceipt | Path,
        *,
        result: str,
        execution_receipt_id: str = "",
        execution_receipt_path: Path | None = None,
    ) -> GenerationResumeReceipt:
        path = receipt.path if isinstance(receipt, GenerationResumeReceipt) else Path(receipt)
        current = self.load(path)
        if current.integrity_status != "verified" or current.status != "started":
            raise ValueError("Only a verified started resume receipt can be finalized.")
        normalized = str(result or "failed").strip().casefold()
        if normalized not in {"completed", "partial", "failed", "cancelled"}:
            normalized = "failed"
        payload = self._read_payload(path)
        now = datetime.now(timezone.utc).isoformat()
        payload["status"] = normalized
        payload["result"] = normalized
        payload["finished_at"] = now
        payload["updated_at"] = now
        payload["execution_receipt_id"] = str(execution_receipt_id or "")
        payload["execution_receipt_path"] = str(execution_receipt_path or "")
        self._write(path.parent, payload)
        return self.load(path)

    def mark_cancelled(self, receipt: GenerationResumeReceipt | Path) -> GenerationResumeReceipt:
        path = receipt.path if isinstance(receipt, GenerationResumeReceipt) else Path(receipt)
        current = self.load(path)
        if current.integrity_status != "verified":
            raise ValueError("A tampered resume receipt cannot be updated.")
        payload = self._read_payload(path)
        now = datetime.now(timezone.utc).isoformat()
        payload["status"] = "cancelled"
        payload["cancelled_at"] = now
        payload["updated_at"] = now
        self._write(path.parent, payload)
        return self.load(path)

    def prepare_jobs(
        self,
        receipt: GenerationResumeReceipt,
        current_jobs: Iterable[TTSJob],
    ) -> tuple[list[TTSJob], tuple[int, ...]]:
        if receipt.integrity_status != "verified" or not receipt.allowed or receipt.status != "planned":
            raise ValueError("Resume receipt is not safe to apply.")
        selected = set(receipt.selected_rows)
        prepared = list(current_jobs)
        found: set[int] = set()
        for job in prepared:
            if job.row_number not in selected:
                continue
            found.add(job.row_number)
            job.status = JobStatus.PENDING
            job.error = None
            job.failure_category = None
            job.error_code = None
            job.error_fingerprint = None
            job.retryable = None
            job.retry_exhausted = False
            job.next_retry_at = None
            job.generated_output_path = None
            job.duration_seconds = 0.0
        missing = selected - found
        if missing:
            raise ValueError(f"Current queue is missing selected recovery rows: {sorted(missing)}")
        return prepared, tuple(sorted(selected))

    def load(self, path: Path) -> GenerationResumeReceipt:
        file_path = Path(path)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Resume receipt root must be a JSON object.")
        except Exception as exc:
            return GenerationResumeReceipt(
                path=file_path,
                markdown_path=file_path.with_name(self.MARKDOWN_NAME),
                integrity_status="unreadable",
                integrity_message=f"Resume receipt could not be read: {exc}",
            )
        integrity_status, integrity_message = self.verify_payload(payload)
        parent = payload.get("parent") if isinstance(payload.get("parent"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        candidates = tuple(
            GenerationResumeCandidate(
                row_number=self._integer(item.get("row_number")),
                filename=str(item.get("filename") or ""),
                parent_disposition=str(item.get("parent_disposition") or ""),
                parent_job_status=str(item.get("parent_job_status") or ""),
                expected_path=str(item.get("expected_path") or ""),
                actual_path=str(item.get("actual_path") or ""),
                output_exists=bool(item.get("output_exists")),
                parent_character_count=self._integer(item.get("parent_character_count")),
                current_character_count=self._integer(item.get("current_character_count")),
                selected=bool(item.get("selected")),
                current_job_found=bool(item.get("current_job_found", True)),
                reason=str(item.get("reason") or ""),
            )
            for item in payload.get("candidates", [])
            if isinstance(item, dict)
        )
        return GenerationResumeReceipt(
            path=file_path,
            markdown_path=file_path.with_name(self.MARKDOWN_NAME),
            schema_version=self._integer(payload.get("schema_version"), 1),
            resume_id=str(payload.get("resume_id") or ""),
            status=str(payload.get("status") or "planned"),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            cancelled_at=str(payload.get("cancelled_at") or ""),
            project_name=str(payload.get("project_name") or ""),
            parent_run_id=str(parent.get("run_id") or ""),
            parent_execution_receipt_id=str(parent.get("execution_receipt_id") or ""),
            parent_execution_receipt_path=str(parent.get("execution_receipt_path") or ""),
            new_run_id=str(payload.get("new_run_id") or ""),
            result=str(payload.get("result") or ""),
            execution_receipt_id=str(payload.get("execution_receipt_id") or ""),
            execution_receipt_path=str(payload.get("execution_receipt_path") or ""),
            scope=str(payload.get("scope") or "unresolved"),
            provider=str(settings.get("provider") or ""),
            model_id=str(settings.get("model_id") or ""),
            voice_id=str(settings.get("voice_id") or ""),
            output_directory=str(settings.get("output_directory") or ""),
            skip_existing=bool(settings.get("skip_existing", True)),
            overwrite_existing=bool(settings.get("overwrite_existing", False)),
            selected_rows=tuple(self._integer(item) for item in payload.get("selected_rows", [])),
            candidates=candidates,
            blockers=tuple(str(item) for item in payload.get("blockers", []) if str(item)),
            warnings=tuple(str(item) for item in payload.get("warnings", []) if str(item)),
            recommendations=tuple(str(item) for item in payload.get("recommendations", []) if str(item)),
            integrity_status=integrity_status,
            integrity_message=integrity_message,
        )

    def list_receipts(self, *, project_name: str | None = None, limit: int = 1000) -> list[GenerationResumeReceipt]:
        records = [self.load(path) for path in self.reports_dir.rglob(self.FILE_NAME)]
        key = str(project_name or "").strip().casefold()
        if key:
            records = [item for item in records if item.project_name.casefold() == key]
        records.sort(key=lambda item: (item.created_at, item.resume_id), reverse=True)
        return records[: max(0, int(limit))]

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
            return "legacy", "Resume receipt predates integrity metadata."
        expected = str(integrity.get("digest") or "")
        actual = cls.canonical_digest(payload)
        if expected and expected == actual:
            return "verified", "Resume receipt integrity verified."
        return "mismatch", "Resume receipt content does not match its SHA-256 digest."

    def _write(self, folder: Path, payload: dict[str, object]) -> None:
        payload["integrity"] = {"algorithm": "sha256", "digest": self.canonical_digest(payload)}
        (folder / self.FILE_NAME).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / self.MARKDOWN_NAME).write_text(self._markdown(payload), encoding="utf-8")

    def _read_payload(self, path: Path) -> dict[str, object]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Resume receipt root must be a JSON object.")
        payload.pop("integrity", None)
        return payload

    def _folder(self, project_name: str, resume_id: str) -> Path:
        return self.reports_dir / self._safe_name(project_name) / "recoveries" / self._safe_name(resume_id)

    @staticmethod
    def _parent_job_metadata(session_path: str) -> dict[int, dict[str, object]]:
        if not session_path:
            return {}
        try:
            payload = json.loads(Path(session_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            GenerationSafeResumeService._integer(item.get("row_number")): item
            for item in payload.get("jobs", [])
            if isinstance(item, dict) and GenerationSafeResumeService._integer(item.get("row_number")) > 0
        }

    @staticmethod
    def _selected_for_scope(disposition: str, scope: str) -> bool:
        if scope == "entire_run":
            return disposition != "unexpected"
        if scope == "failed_only":
            return disposition == "failed"
        if scope == "missing_only":
            return disposition == "missing"
        if scope == "incomplete_only":
            return disposition == "incomplete"
        return disposition in {"failed", "missing", "incomplete"}

    @staticmethod
    def _candidate_reason(disposition: str, selected: bool, found: bool, output_exists: bool) -> str:
        if not found:
            return "No matching current queue job."
        if not selected:
            return "Outside the selected recovery scope."
        if output_exists:
            return "Selected; an output currently exists and file policy will be revalidated."
        return f"Selected from parent disposition '{disposition}'."

    @staticmethod
    def _filename_key(value: str) -> str:
        return Path(str(value or "")).name.casefold()

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._") or "unknown"

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _markdown(payload: dict[str, object]) -> str:
        parent = payload.get("parent") if isinstance(payload.get("parent"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        lines = [
            "# S Talking Safe Resume Receipt",
            "",
            f"- Resume ID: `{payload.get('resume_id', '')}`",
            f"- Status: {payload.get('status', 'planned')}",
            f"- Project: {payload.get('project_name', '')}",
            f"- Parent run: `{parent.get('run_id', '')}`",
            f"- New run: `{payload.get('new_run_id', '') or 'Not started'}`",
            f"- Result: {payload.get('result', '') or 'In progress'}",
            f"- Execution receipt: `{payload.get('execution_receipt_id', '') or '—'}`",
            f"- Scope: {payload.get('scope', '')}",
            f"- Provider / model / voice: {settings.get('provider', '')} / {settings.get('model_id', '')} / {settings.get('voice_id', '')}",
            f"- Output: {settings.get('output_directory', '')}",
            f"- File policy: skip={settings.get('skip_existing', True)} / overwrite={settings.get('overwrite_existing', False)}",
            f"- Selected rows: {', '.join(str(item) for item in payload.get('selected_rows', []))}",
            "",
            "## Warnings",
        ]
        warnings = payload.get("warnings", [])
        lines.extend(f"- {GenerationSafeResumeService._sanitize_text(str(item))}" for item in warnings)
        lines.extend(("", "## Selected jobs"))
        for item in payload.get("candidates", []):
            if isinstance(item, dict) and item.get("selected"):
                lines.append(
                    f"- Row {item.get('row_number', 0)} · {item.get('filename', '')} · "
                    f"{item.get('parent_disposition', '')}"
                )
        return "\n".join(lines) + "\n"

    @staticmethod
    def _sanitize_text(value: str) -> str:
        return GenerationSafeResumeService.SECRET_VALUE.sub("[REDACTED]", str(value or ""))
