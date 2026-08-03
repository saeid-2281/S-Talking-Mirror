from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import AppSettings, TTSJob
from app.models.generation_execution_receipt import (
    GenerationExecutionReceipt,
    GenerationExecutionReceiptSummary,
    GenerationOutputManifestEntry,
)
from app.models.generation_execution_session import GenerationExecutionSession


class GenerationExecutionReceiptService:
    """Create and audit the immutable actual-output receipt for completed runs."""

    FILE_NAME = "generation-execution-receipt.json"
    MARKDOWN_NAME = "generation-execution-receipt.md"
    MANIFEST_NAME = "output-manifest.csv"
    SCHEMA_VERSION = 1
    SECRET_VALUE = re.compile(
        r"(sk[_-][A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;}]+)",
        re.IGNORECASE,
    )

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def create_receipt(
        self,
        *,
        session: GenerationExecutionSession,
        jobs: Iterable[TTSJob],
        settings: AppSettings,
        output_directory: Path,
        report_path: Path | None = None,
        hash_outputs: bool = True,
        discover_unexpected: bool = True,
        created_at: datetime | None = None,
    ) -> GenerationExecutionReceipt:
        if not session.run_id:
            raise ValueError("Execution session must have a run ID.")
        folder = session.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        now = created_at or datetime.now(timezone.utc)
        existing_before = {self._path_key(Path(item)) for item in session.planned_existing_outputs}
        job_entries = [
            self._entry_for_job(
                job,
                settings=settings,
                output_directory=Path(output_directory),
                existing_before=existing_before,
                hash_outputs=hash_outputs,
            )
            for job in jobs
        ]
        unexpected_entries: list[GenerationOutputManifestEntry] = []
        if discover_unexpected:
            unexpected_entries = self._unexpected_entries(
                expected={self._path_key(Path(item.expected_path)) for item in job_entries},
                output_directory=Path(output_directory),
                started_at=session.started_at,
                settings=settings,
                hash_outputs=hash_outputs,
            )
        entries = tuple(job_entries + unexpected_entries)
        counts = self._counts(entries)
        launch = self._launch_plan(session.launch_receipt_path)
        status = self._receipt_status(session.status, counts)
        receipt_id = f"execution-{session.run_id}-{uuid.uuid4().hex[:8]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "created_at": now.isoformat(),
            "run_id": session.run_id,
            "status": status,
            "project": {
                "name": session.project_name,
                "id": session.project_id,
                "key": session.project_key,
            },
            "links": {
                "launch_receipt_id": session.launch_receipt_id,
                "launch_receipt_path": session.launch_receipt_path,
                "execution_session_path": str(session.path),
                "decision_trace_id": session.decision_trace_id,
                "guard_approval_id": session.guard_approval_id,
                "report_path": str(report_path or session.report_path or ""),
            },
            "settings": {
                "provider": session.provider or settings.provider,
                "model_id": session.model_id or settings.model_id,
                "voice_id": session.voice_id or settings.voice_id,
            },
            "output_directory": str(Path(output_directory)),
            "started_at": session.started_at,
            "finished_at": session.finished_at or now.isoformat(),
            "elapsed_seconds": session.elapsed_seconds,
            "planned": {
                "files": self._integer(launch.get("files"), session.total_jobs),
                "characters": self._integer(launch.get("characters"), session.total_characters),
                "provider_requests": self._integer(launch.get("provider_requests"), session.total_jobs),
                "existing_outputs": len(existing_before)
                or self._integer(launch.get("existing_outputs")),
            },
            "actual": counts,
            "entries": [asdict(item) for item in entries],
        }
        self._write(folder, payload)
        return self.load(folder / self.FILE_NAME)

    def load(self, path: Path) -> GenerationExecutionReceipt:
        file_path = Path(path)
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Execution receipt root must be a JSON object.")
        except Exception as exc:
            return GenerationExecutionReceipt(
                path=file_path,
                markdown_path=file_path.with_name(self.MARKDOWN_NAME),
                manifest_csv_path=file_path.with_name(self.MANIFEST_NAME),
                integrity_status="unreadable",
                integrity_message=f"Execution receipt could not be read: {exc}",
            )
        integrity_status, integrity_message = self.verify_payload(payload)
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        planned = payload.get("planned") if isinstance(payload.get("planned"), dict) else {}
        actual = payload.get("actual") if isinstance(payload.get("actual"), dict) else {}
        entries = tuple(
            self._entry_from_payload(item)
            for item in payload.get("entries", [])
            if isinstance(item, dict)
        )
        return GenerationExecutionReceipt(
            path=file_path,
            markdown_path=file_path.with_name(self.MARKDOWN_NAME),
            manifest_csv_path=file_path.with_name(self.MANIFEST_NAME),
            schema_version=self._integer(payload.get("schema_version"), 1),
            receipt_id=str(payload.get("receipt_id") or ""),
            created_at=str(payload.get("created_at") or ""),
            run_id=str(payload.get("run_id") or ""),
            status=str(payload.get("status") or "unknown"),
            project_name=str(project.get("name") or ""),
            project_id=self._optional_integer(project.get("id")),
            project_key=str(project.get("key") or ""),
            launch_receipt_id=str(links.get("launch_receipt_id") or ""),
            launch_receipt_path=str(links.get("launch_receipt_path") or ""),
            execution_session_path=str(links.get("execution_session_path") or ""),
            decision_trace_id=str(links.get("decision_trace_id") or ""),
            guard_approval_id=str(links.get("guard_approval_id") or ""),
            provider=str(settings.get("provider") or ""),
            model_id=str(settings.get("model_id") or ""),
            voice_id=str(settings.get("voice_id") or ""),
            output_directory=str(payload.get("output_directory") or ""),
            report_path=str(links.get("report_path") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            elapsed_seconds=self._number(payload.get("elapsed_seconds")),
            planned_files=self._integer(planned.get("files")),
            planned_characters=self._integer(planned.get("characters")),
            planned_requests=self._integer(planned.get("provider_requests")),
            planned_existing_outputs=self._integer(planned.get("existing_outputs")),
            actual_outputs=self._integer(actual.get("actual_outputs")),
            created_outputs=self._integer(actual.get("created_outputs")),
            overwritten_outputs=self._integer(actual.get("overwritten_outputs")),
            skipped_outputs=self._integer(actual.get("skipped_outputs")),
            failed_outputs=self._integer(actual.get("failed_outputs")),
            missing_outputs=self._integer(actual.get("missing_outputs")),
            incomplete_outputs=self._integer(actual.get("incomplete_outputs")),
            unexpected_outputs=self._integer(actual.get("unexpected_outputs")),
            total_bytes=self._integer(actual.get("total_bytes")),
            entries=entries,
            integrity_status=integrity_status,
            integrity_message=integrity_message,
        )

    def list_receipts(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
        search: str = "",
        limit: int = 1000,
    ) -> list[GenerationExecutionReceipt]:
        records = [self.load(path) for path in self.reports_dir.rglob(self.FILE_NAME)]
        project_key = str(project_name or "").strip().casefold()
        status_key = str(status or "").strip().casefold()
        search_key = str(search or "").strip().casefold()
        filtered: list[GenerationExecutionReceipt] = []
        for receipt in records:
            if project_key and receipt.project_name.casefold() != project_key:
                continue
            if status_key and receipt.status.casefold() != status_key:
                continue
            if search_key and search_key not in self._search_text(receipt):
                continue
            filtered.append(receipt)
        filtered.sort(key=lambda item: (item.finished_at, item.receipt_id), reverse=True)
        return filtered[: max(0, int(limit))]

    @staticmethod
    def summary(receipts: Iterable[GenerationExecutionReceipt]) -> GenerationExecutionReceiptSummary:
        records = list(receipts)
        return GenerationExecutionReceiptSummary(
            total_count=len(records),
            completed_count=sum(item.status == "completed" for item in records),
            partial_count=sum(item.status == "partial" for item in records),
            failed_count=sum(item.status == "failed" for item in records),
            cancelled_count=sum(item.status == "cancelled" for item in records),
            integrity_issue_count=sum(item.integrity_status in {"mismatch", "unreadable"} for item in records),
            planned_files=sum(item.planned_files for item in records),
            actual_outputs=sum(item.actual_outputs for item in records),
            created_outputs=sum(item.created_outputs for item in records),
            overwritten_outputs=sum(item.overwritten_outputs for item in records),
            skipped_outputs=sum(item.skipped_outputs for item in records),
            failed_outputs=sum(item.failed_outputs for item in records),
            missing_outputs=sum(item.missing_outputs for item in records),
            unexpected_outputs=sum(item.unexpected_outputs for item in records),
            total_bytes=sum(item.total_bytes for item in records),
        )

    def export(
        self,
        receipts: Iterable[GenerationExecutionReceipt],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        records = list(receipts)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe = self._safe_name(project_name)
        json_path = target / f"generation-execution-receipts-{safe}-{stamp}.json"
        csv_path = target / f"generation-execution-receipts-{safe}-{stamp}.csv"
        rows = [self._export_row(item) for item in records]
        json_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "summary": asdict(self.summary(records)),
                    "receipts": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fields = list(rows[0]) if rows else list(self._export_row(self._empty_receipt()))
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path

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
            return "legacy", "Execution receipt predates integrity metadata."
        expected = str(integrity.get("digest") or "")
        actual = cls.canonical_digest(payload)
        if expected and expected == actual:
            return "verified", "Execution receipt integrity verified."
        return "mismatch", "Execution receipt content does not match its SHA-256 digest."

    def _write(self, folder: Path, payload: dict[str, object]) -> None:
        payload["integrity"] = {"algorithm": "sha256", "digest": self.canonical_digest(payload)}
        (folder / self.FILE_NAME).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / self.MARKDOWN_NAME).write_text(self._markdown(payload), encoding="utf-8")
        self._write_manifest(folder / self.MANIFEST_NAME, payload)

    def _write_manifest(self, path: Path, payload: dict[str, object]) -> None:
        fields = list(asdict(self._entry_from_payload({})))
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in payload.get("entries", []):
                if isinstance(item, dict):
                    writer.writerow({key: item.get(key, "") for key in fields})

    def _entry_for_job(
        self,
        job: TTSJob,
        *,
        settings: AppSettings,
        output_directory: Path,
        existing_before: set[str],
        hash_outputs: bool,
    ) -> GenerationOutputManifestEntry:
        expected = Path(job.generated_output_path or job.output_path(output_directory, settings.file_extension))
        exists_after = expected.is_file()
        existed_before = self._path_key(expected) in existing_before
        status = job.status.value
        if status == "completed" and exists_after:
            disposition = "overwritten" if existed_before and settings.overwrite_existing else "created"
        elif status == "completed":
            disposition = "missing"
        elif status == "skipped":
            disposition = "skipped_existing" if exists_after else "skipped"
        elif status == "failed":
            disposition = "failed"
        else:
            disposition = "incomplete"
        size, digest, modified_at = self._file_metadata(expected, hash_outputs=hash_outputs)
        return GenerationOutputManifestEntry(
            row_number=job.row_number,
            filename=job.filename,
            expected_path=str(expected),
            actual_path=str(expected) if exists_after else "",
            disposition=disposition,
            job_status=status,
            existed_before=existed_before,
            exists_after=exists_after,
            size_bytes=size,
            sha256=digest,
            modified_at=modified_at,
            provider=job.provider_override or settings.provider,
            model_id=job.model_override or settings.model_id,
            voice_id=job.voice_override or settings.voice_id,
            retry_count=job.retry_count,
            duration_seconds=job.duration_seconds,
            error_code=job.error_code or "",
            error_fingerprint=job.error_fingerprint or "",
        )

    def _unexpected_entries(
        self,
        *,
        expected: set[str],
        output_directory: Path,
        started_at: str,
        settings: AppSettings,
        hash_outputs: bool,
    ) -> list[GenerationOutputManifestEntry]:
        if not output_directory.exists():
            return []
        threshold = self._timestamp(started_at)
        suffixes = {str(settings.file_extension or "").casefold()}
        suffixes.discard("")
        entries: list[GenerationOutputManifestEntry] = []
        for path in output_directory.rglob("*"):
            if not path.is_file() or self._path_key(path) in expected:
                continue
            if suffixes and path.suffix.casefold() not in suffixes:
                continue
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            if threshold is not None and modified + 2.0 < threshold:
                continue
            size, digest, modified_at = self._file_metadata(path, hash_outputs=hash_outputs)
            entries.append(
                GenerationOutputManifestEntry(
                    row_number=0,
                    filename=path.name,
                    expected_path="",
                    actual_path=str(path),
                    disposition="unexpected",
                    job_status="unexpected",
                    exists_after=True,
                    size_bytes=size,
                    sha256=digest,
                    modified_at=modified_at,
                    provider=settings.provider,
                    model_id=settings.model_id,
                    voice_id=settings.voice_id,
                )
            )
            if len(entries) >= 1000:
                break
        return entries

    @staticmethod
    def _counts(entries: tuple[GenerationOutputManifestEntry, ...] | list[GenerationOutputManifestEntry]) -> dict[str, int]:
        records = list(entries)
        dispositions = [item.disposition for item in records]
        created = dispositions.count("created")
        overwritten = dispositions.count("overwritten")
        skipped = dispositions.count("skipped") + dispositions.count("skipped_existing")
        return {
            "actual_outputs": created + overwritten,
            "created_outputs": created,
            "overwritten_outputs": overwritten,
            "skipped_outputs": skipped,
            "failed_outputs": dispositions.count("failed"),
            "missing_outputs": dispositions.count("missing"),
            "incomplete_outputs": dispositions.count("incomplete"),
            "unexpected_outputs": dispositions.count("unexpected"),
            "total_bytes": sum(item.size_bytes for item in records if item.exists_after),
        }

    @staticmethod
    def _receipt_status(session_status: str, counts: dict[str, int]) -> str:
        issue_count = (
            counts["failed_outputs"]
            + counts["missing_outputs"]
            + counts["incomplete_outputs"]
            + counts["unexpected_outputs"]
        )
        produced = counts["actual_outputs"] + counts["skipped_outputs"]
        normalized = str(session_status or "unknown").casefold()
        if normalized == "cancelled":
            return "cancelled"
        if issue_count == 0 and normalized == "completed":
            return "completed"
        if produced > 0:
            return "partial"
        return "failed" if normalized in {"failed", "partial"} or issue_count else normalized

    @staticmethod
    def _launch_plan(path: str) -> dict[str, object]:
        if not path:
            return {}
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        return dict(scope)

    @staticmethod
    def _entry_from_payload(payload: dict[str, object]) -> GenerationOutputManifestEntry:
        return GenerationOutputManifestEntry(
            row_number=GenerationExecutionReceiptService._integer(payload.get("row_number")),
            filename=str(payload.get("filename") or ""),
            expected_path=str(payload.get("expected_path") or ""),
            actual_path=str(payload.get("actual_path") or ""),
            disposition=str(payload.get("disposition") or "missing"),
            job_status=str(payload.get("job_status") or "pending"),
            existed_before=bool(payload.get("existed_before")),
            exists_after=bool(payload.get("exists_after")),
            size_bytes=GenerationExecutionReceiptService._integer(payload.get("size_bytes")),
            sha256=str(payload.get("sha256") or ""),
            modified_at=str(payload.get("modified_at") or ""),
            provider=str(payload.get("provider") or ""),
            model_id=str(payload.get("model_id") or ""),
            voice_id=str(payload.get("voice_id") or ""),
            retry_count=GenerationExecutionReceiptService._integer(payload.get("retry_count")),
            duration_seconds=GenerationExecutionReceiptService._number(payload.get("duration_seconds")),
            error_code=str(payload.get("error_code") or ""),
            error_fingerprint=str(payload.get("error_fingerprint") or ""),
        )

    @staticmethod
    def _file_metadata(path: Path, *, hash_outputs: bool) -> tuple[int, str, str]:
        if not path.is_file():
            return 0, "", ""
        try:
            stat = path.stat()
            digest = GenerationExecutionReceiptService._sha256(path) if hash_outputs else ""
            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
            return int(stat.st_size), digest, modified
        except OSError:
            return 0, "", ""

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            value = str(path.resolve(strict=False))
        except OSError:
            value = str(path)
        return os.path.normcase(value)

    @staticmethod
    def _timestamp(value: str) -> float | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    @staticmethod
    def _search_text(receipt: GenerationExecutionReceipt) -> str:
        return " ".join(
            (
                receipt.receipt_id,
                receipt.run_id,
                receipt.status,
                receipt.project_name,
                receipt.launch_receipt_id,
                receipt.decision_trace_id,
                receipt.guard_approval_id,
                receipt.provider,
                receipt.model_id,
                receipt.voice_id,
                receipt.output_directory,
                receipt.report_path,
                " ".join(item.filename for item in receipt.entries),
            )
        ).casefold()

    @staticmethod
    def _export_row(receipt: GenerationExecutionReceipt) -> dict[str, object]:
        return {
            "receipt_id": receipt.receipt_id,
            "run_id": receipt.run_id,
            "status": receipt.status,
            "project_name": receipt.project_name,
            "launch_receipt_id": receipt.launch_receipt_id,
            "decision_trace_id": receipt.decision_trace_id,
            "guard_approval_id": receipt.guard_approval_id,
            "provider": receipt.provider,
            "model_id": receipt.model_id,
            "voice_id": receipt.voice_id,
            "output_directory": receipt.output_directory,
            "report_path": receipt.report_path,
            "started_at": receipt.started_at,
            "finished_at": receipt.finished_at,
            "elapsed_seconds": receipt.elapsed_seconds,
            "planned_files": receipt.planned_files,
            "actual_outputs": receipt.actual_outputs,
            "created_outputs": receipt.created_outputs,
            "overwritten_outputs": receipt.overwritten_outputs,
            "skipped_outputs": receipt.skipped_outputs,
            "failed_outputs": receipt.failed_outputs,
            "missing_outputs": receipt.missing_outputs,
            "unexpected_outputs": receipt.unexpected_outputs,
            "total_bytes": receipt.total_bytes,
            "integrity_status": receipt.integrity_status,
            "receipt_path": str(receipt.path),
            "manifest_path": str(receipt.manifest_csv_path),
        }

    @classmethod
    def _markdown(cls, payload: dict[str, object]) -> str:
        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        planned = payload.get("planned") if isinstance(payload.get("planned"), dict) else {}
        actual = payload.get("actual") if isinstance(payload.get("actual"), dict) else {}
        lines = [
            "# S Talking Generation Execution Receipt",
            "",
            f"- Receipt ID: `{payload.get('receipt_id', '')}`",
            f"- Run ID: `{payload.get('run_id', '')}`",
            f"- Status: {payload.get('status', 'unknown')}",
            f"- Project: {project.get('name', '')}",
            f"- Started: {payload.get('started_at', '')}",
            f"- Finished: {payload.get('finished_at', '')}",
            f"- Planned files: {planned.get('files', 0)}",
            f"- Actual outputs: {actual.get('actual_outputs', 0)}",
            f"- Created / overwritten / skipped: {actual.get('created_outputs', 0)} / {actual.get('overwritten_outputs', 0)} / {actual.get('skipped_outputs', 0)}",
            f"- Failed / missing / unexpected: {actual.get('failed_outputs', 0)} / {actual.get('missing_outputs', 0)} / {actual.get('unexpected_outputs', 0)}",
            "",
            "## Output manifest",
        ]
        for item in payload.get("entries", []):
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- Row {item.get('row_number', 0)} · {item.get('filename', '')} · "
                f"{item.get('disposition', 'unknown')} · {item.get('size_bytes', 0)} bytes"
            )
        return "\n".join(lines) + "\n"

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

    @staticmethod
    def _empty_receipt() -> GenerationExecutionReceipt:
        empty = Path("")
        return GenerationExecutionReceipt(empty, empty, empty)
