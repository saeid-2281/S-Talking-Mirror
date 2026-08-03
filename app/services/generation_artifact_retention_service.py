from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
import zipfile
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.models.generation_artifact_retention import (
    GenerationArtifactRetentionCandidate,
    GenerationArtifactRetentionPolicy,
    GenerationArtifactRetentionPreview,
    GenerationArtifactRetentionRun,
)


class GenerationArtifactRetentionService:
    """Preview, archive, and safely remove stale governance artifacts.

    The service only operates on known files below ``reports_dir``. Output audio,
    project sources, settings and database files are never retention candidates.
    """

    POLICY_NAME = "generation-artifact-retention-policies.json"
    RUN_INDEX_NAME = "generation-artifact-retention-runs.json"
    ARCHIVE_FOLDER = "artifact-retention-archives"
    AUDIT_FOLDER = "artifact-retention"
    SCHEMA_VERSION = 1

    PRIMARY_FILES = {
        "generation-launch.json": ("launch_receipt", "created_at", "launch_receipt_days"),
        "generation-execution.json": ("execution_run", "started_at", "execution_run_days"),
        "generation-resume.json": ("recovery_receipt", "created_at", "recovery_receipt_days"),
    }
    COMPANIONS = {
        "generation-launch.json": ("generation-launch.md",),
        "generation-execution.json": (
            "generation-execution.md",
            "generation-execution-receipt.json",
            "generation-execution-receipt.md",
            "output-manifest.csv",
        ),
        "generation-resume.json": ("generation-resume.md",),
    }
    KNOWN_COMPANIONS = {
        name for names in COMPANIONS.values() for name in names
    }
    TERMINAL_RUN_STATES = {"completed", "partial", "failed", "cancelled"}
    TERMINAL_RECOVERY_STATES = {"completed", "partial", "failed", "cancelled"}
    TERMINAL_APPROVAL_STATES = {"expired", "consumed", "revoked"}
    TERMINAL_BUDGET_STATES = {"settled", "released", "expired", "consumed", "revoked"}
    SECRET_VALUE = re.compile(
        r"(sk[_-][A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;}]+)",
        re.IGNORECASE,
    )

    def __init__(self, reports_dir: Path, *, now_factory=None) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    def get_policy(self, project_name: str = "") -> GenerationArtifactRetentionPolicy:
        key = self._project_key(project_name)
        payload = self._read_json(self._policy_path(), {"schema_version": 1, "policies": {}})
        policies = payload.get("policies") if isinstance(payload.get("policies"), dict) else {}
        record = policies.get(key) if isinstance(policies.get(key), dict) else {}
        defaults = GenerationArtifactRetentionPolicy(project_name=project_name)
        return GenerationArtifactRetentionPolicy(
            project_name=project_name,
            enabled=self._boolean(record.get("enabled"), defaults.enabled),
            launch_receipt_days=self._days(record.get("launch_receipt_days"), defaults.launch_receipt_days),
            execution_run_days=self._days(record.get("execution_run_days"), defaults.execution_run_days),
            recovery_receipt_days=self._days(record.get("recovery_receipt_days"), defaults.recovery_receipt_days),
            approval_record_days=self._days(record.get("approval_record_days"), defaults.approval_record_days),
            budget_record_days=self._days(record.get("budget_record_days"), defaults.budget_record_days),
            orphan_grace_days=self._days(record.get("orphan_grace_days"), defaults.orphan_grace_days),
            archive_before_delete=self._boolean(
                record.get("archive_before_delete"), defaults.archive_before_delete
            ),
            keep_integrity_issues=self._boolean(
                record.get("keep_integrity_issues"), defaults.keep_integrity_issues
            ),
            updated_at=str(record.get("updated_at") or ""),
        )

    def save_policy(
        self, policy: GenerationArtifactRetentionPolicy
    ) -> GenerationArtifactRetentionPolicy:
        now = self._now().isoformat()
        normalized = replace(
            policy,
            project_name=str(policy.project_name or "").strip(),
            launch_receipt_days=self._days(policy.launch_receipt_days, 365),
            execution_run_days=self._days(policy.execution_run_days, 365),
            recovery_receipt_days=self._days(policy.recovery_receipt_days, 180),
            approval_record_days=self._days(policy.approval_record_days, 365),
            budget_record_days=self._days(policy.budget_record_days, 180),
            orphan_grace_days=self._days(policy.orphan_grace_days, 14),
            updated_at=now,
        )
        payload = self._read_json(self._policy_path(), {"schema_version": 1, "policies": {}})
        policies = payload.setdefault("policies", {})
        if not isinstance(policies, dict):
            policies = {}
            payload["policies"] = policies
        policies[self._project_key(normalized.project_name)] = asdict(normalized)
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["updated_at"] = now
        self._atomic_json(self._policy_path(), payload)
        return normalized

    def preview(
        self,
        *,
        project_name: str = "",
        policy: GenerationArtifactRetentionPolicy | None = None,
    ) -> GenerationArtifactRetentionPreview:
        active = policy or self.get_policy(project_name)
        now = self._now()
        candidates: list[GenerationArtifactRetentionCandidate] = []
        if active.enabled:
            candidates.extend(self._file_candidates(active, now))
            candidates.extend(self._approval_candidates(active, now))
            candidates.extend(self._budget_candidates(active, now))
            candidates.extend(self._orphan_candidates(active, now))
        candidates = self._deduplicate(candidates)
        candidates.sort(key=lambda item: (item.action, item.created_at, str(item.path)))
        preview_id = self._preview_digest(active, candidates, now)
        return GenerationArtifactRetentionPreview(
            preview_id=preview_id,
            generated_at=now.isoformat(),
            project_name=active.project_name,
            policy=active,
            candidates=tuple(candidates),
            total_bytes=sum(max(0, item.size_bytes) for item in candidates),
            archive_count=sum(item.action == "archive" for item in candidates),
            delete_count=sum(item.action == "delete" for item in candidates),
            review_count=sum(item.action == "review" for item in candidates),
            orphan_count=sum(item.artifact_type == "orphan" for item in candidates),
            integrity_issue_count=sum(item.integrity_status in {"mismatch", "unreadable"} for item in candidates),
        )

    def apply(
        self,
        preview: GenerationArtifactRetentionPreview,
        *,
        dry_run: bool = False,
    ) -> GenerationArtifactRetentionRun:
        fresh = self.preview(project_name=preview.project_name, policy=preview.policy)
        if fresh.preview_id != preview.preview_id:
            raise ValueError("Retention preview is stale. Refresh the preview before cleanup.")
        now = self._now()
        run_id = f"retention-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
        actionable = [item for item in fresh.candidates if item.action in {"archive", "delete"}]
        archive_path: Path | None = None
        manifest_path: Path | None = None
        archive_sha256 = ""
        deleted = 0
        archived = 0
        skipped = 0
        reclaimed = 0
        errors: list[str] = []

        if dry_run:
            result = GenerationArtifactRetentionRun(
                run_id=run_id,
                preview_id=fresh.preview_id,
                project_name=fresh.project_name,
                status="dry_run",
                dry_run=True,
                started_at=now.isoformat(),
                finished_at=self._now().isoformat(),
                candidate_count=len(fresh.candidates),
                skipped_count=len(fresh.candidates),
            )
            self._record_run(result)
            return result

        if actionable and fresh.policy.archive_before_delete:
            archive_path, manifest_path, archive_sha256, archived = self._create_archive(
                run_id, fresh, actionable
            )

        virtual_ids = {item.candidate_id for item in actionable if item.virtual_record}
        if virtual_ids:
            deleted_virtual, virtual_errors = self._remove_virtual_records(virtual_ids)
            deleted += deleted_virtual
            errors.extend(virtual_errors)

        for item in actionable:
            if item.virtual_record:
                continue
            try:
                reclaimed += self._delete_candidate_files(item)
                deleted += 1
            except OSError as exc:
                errors.append(f"{item.candidate_id}: {self._sanitize(exc)}")
                skipped += 1

        status = "completed" if not errors else "partial"
        result = GenerationArtifactRetentionRun(
            run_id=run_id,
            preview_id=fresh.preview_id,
            project_name=fresh.project_name,
            status=status,
            dry_run=False,
            started_at=now.isoformat(),
            finished_at=self._now().isoformat(),
            archive_path=archive_path,
            manifest_path=manifest_path,
            archive_sha256=archive_sha256,
            candidate_count=len(fresh.candidates),
            archived_count=archived,
            deleted_count=deleted,
            skipped_count=skipped + fresh.review_count,
            reclaimed_bytes=reclaimed,
            errors=tuple(errors),
        )
        self._record_run(result)
        return result

    def list_runs(self, *, limit: int = 100) -> list[GenerationArtifactRetentionRun]:
        payload = self._read_json(self._run_index_path(), {"schema_version": 1, "runs": []})
        records = payload.get("runs") if isinstance(payload.get("runs"), list) else []
        result: list[GenerationArtifactRetentionRun] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            result.append(
                GenerationArtifactRetentionRun(
                    run_id=str(item.get("run_id") or ""),
                    preview_id=str(item.get("preview_id") or ""),
                    project_name=str(item.get("project_name") or ""),
                    status=str(item.get("status") or "unknown"),
                    dry_run=self._boolean(item.get("dry_run"), False),
                    started_at=str(item.get("started_at") or ""),
                    finished_at=str(item.get("finished_at") or ""),
                    archive_path=Path(str(item.get("archive_path"))) if item.get("archive_path") else None,
                    manifest_path=Path(str(item.get("manifest_path"))) if item.get("manifest_path") else None,
                    archive_sha256=str(item.get("archive_sha256") or ""),
                    candidate_count=self._integer(item.get("candidate_count")),
                    archived_count=self._integer(item.get("archived_count")),
                    deleted_count=self._integer(item.get("deleted_count")),
                    skipped_count=self._integer(item.get("skipped_count")),
                    reclaimed_bytes=self._integer(item.get("reclaimed_bytes")),
                    errors=tuple(str(value) for value in item.get("errors", []) if str(value)),
                )
            )
        result.sort(key=lambda item: (item.started_at, item.run_id), reverse=True)
        return result[: max(0, int(limit))]

    def export_preview(
        self,
        preview: GenerationArtifactRetentionPreview,
        directory: Path,
    ) -> tuple[Path, Path]:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        safe = self._safe_name(preview.project_name or "all-projects")
        json_path = target / f"generation-artifact-retention-{safe}-{stamp}.json"
        csv_path = target / f"generation-artifact-retention-{safe}-{stamp}.csv"
        rows = [self._candidate_row(item) for item in preview.candidates]
        json_path.write_text(
            json.dumps(
                {
                    "created_at": self._now().isoformat(),
                    "preview_id": preview.preview_id,
                    "project_name": preview.project_name,
                    "policy": asdict(preview.policy),
                    "summary": {
                        "candidate_count": len(preview.candidates),
                        "actionable_count": preview.actionable_count,
                        "review_count": preview.review_count,
                        "total_bytes": preview.total_bytes,
                    },
                    "candidates": rows,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        fields = list(rows[0]) if rows else list(self._candidate_row(self._empty_candidate()))
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path

    def verify_archive(self, archive_path: Path, expected_sha256: str = "") -> tuple[bool, str]:
        path = Path(archive_path)
        if not path.is_file():
            return False, "Archive file is missing."
        digest = self._sha256(path)
        if expected_sha256 and digest != expected_sha256:
            return False, "Archive SHA-256 does not match the retention audit record."
        try:
            with zipfile.ZipFile(path, "r") as archive:
                corrupt = archive.testzip()
        except (OSError, zipfile.BadZipFile) as exc:
            return False, f"Archive could not be verified: {exc}"
        if corrupt:
            return False, f"Archive contains a corrupt entry: {corrupt}"
        return True, "Archive integrity verified."

    def _file_candidates(
        self,
        policy: GenerationArtifactRetentionPolicy,
        now: datetime,
    ) -> list[GenerationArtifactRetentionCandidate]:
        result: list[GenerationArtifactRetentionCandidate] = []
        protected_launch_ids, protected_launch_paths = self._protected_launch_receipts(now)
        active_run_ids = self._active_run_ids()
        active_resume_parent_ids = self._active_resume_parent_ids()
        for name, (artifact_type, timestamp_key, days_field) in self.PRIMARY_FILES.items():
            cutoff = now - timedelta(days=getattr(policy, days_field))
            for path in self.reports_dir.rglob(name):
                if self._excluded_path(path):
                    continue
                payload = self._read_json(path, {})
                project_name = self._payload_project(payload, path)
                if not self._project_name_matches(project_name, policy.project_name):
                    continue
                created = self._timestamp(payload.get(timestamp_key), path)
                if created > cutoff:
                    continue
                identifier = self._identifier(payload, path)
                if name == "generation-execution.json":
                    status = str(payload.get("status") or "").casefold()
                    if status not in self.TERMINAL_RUN_STATES:
                        continue
                if name == "generation-resume.json":
                    status = str(payload.get("status") or "planned").casefold()
                    if status not in self.TERMINAL_RECOVERY_STATES:
                        continue
                integrity = self._integrity_status(payload)
                action = "archive" if policy.archive_before_delete else "delete"
                dependency_reason = ""
                if name == "generation-launch.json":
                    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
                    run_id = str(execution.get("run_id") or "")
                    if identifier in protected_launch_ids or self._path_key(path) in protected_launch_paths:
                        dependency_reason = "Current baseline or active approval still references this launch receipt."
                    elif run_id and run_id in active_run_ids:
                        dependency_reason = "An active execution session still references this launch receipt."
                elif name == "generation-execution.json" and identifier in active_resume_parent_ids:
                    dependency_reason = "An active recovery receipt still references this parent run."
                protected = bool(dependency_reason) or (
                    integrity in {"mismatch", "unreadable"} and policy.keep_integrity_issues
                )
                if protected:
                    action = "review"
                related = tuple(
                    candidate
                    for candidate in (path.with_name(item) for item in self.COMPANIONS[name])
                    if candidate.is_file()
                )
                result.append(
                    self._candidate(
                        project_name=project_name,
                        artifact_type=artifact_type,
                        identifier=identifier,
                        path=path,
                        created=created,
                        now=now,
                        action=action,
                        reason=dependency_reason or f"Older than {getattr(policy, days_field)} retention day(s).",
                        integrity_status=integrity,
                        related_paths=related,
                        protected=protected,
                    )
                )
        return result

    def _protected_launch_receipts(self, now: datetime) -> tuple[set[str], set[str]]:
        identifiers: set[str] = set()
        paths: set[str] = set()
        baseline = self._read_json(
            self.reports_dir / "generation-launch-receipt-baselines.json",
            {},
        )
        projects = baseline.get("projects") if isinstance(baseline.get("projects"), dict) else {}
        for item in projects.values():
            if not isinstance(item, dict):
                continue
            receipt_id = str(item.get("receipt_id") or "")
            if receipt_id:
                identifiers.add(receipt_id)
            raw_path = str(item.get("receipt_path") or "")
            if raw_path:
                path = Path(raw_path)
                if not path.is_absolute():
                    path = self.reports_dir / path
                paths.add(self._path_key(path))
        approvals = self._read_json(
            self.reports_dir / "generation-launch-guard-approvals.json",
            {},
        )
        records = approvals.get("approvals") if isinstance(approvals.get("approvals"), list) else []
        for item in records:
            if not isinstance(item, dict) or self._approval_status(item, now) != "approved":
                continue
            receipt_id = str(item.get("baseline_receipt_id") or "")
            if receipt_id:
                identifiers.add(receipt_id)
        return identifiers, paths

    def _active_run_ids(self) -> set[str]:
        active: set[str] = set()
        for path in self.reports_dir.rglob("generation-execution.json"):
            if self._excluded_path(path):
                continue
            payload = self._read_json(path, {})
            status = str(payload.get("status") or "").casefold()
            run_id = str(payload.get("run_id") or "")
            if run_id and status not in self.TERMINAL_RUN_STATES:
                active.add(run_id)
        return active

    def _active_resume_parent_ids(self) -> set[str]:
        active: set[str] = set()
        for path in self.reports_dir.rglob("generation-resume.json"):
            if self._excluded_path(path):
                continue
            payload = self._read_json(path, {})
            status = str(payload.get("status") or "planned").casefold()
            if status in self.TERMINAL_RECOVERY_STATES:
                continue
            parent = payload.get("parent") if isinstance(payload.get("parent"), dict) else {}
            run_id = str(parent.get("run_id") or "")
            if run_id:
                active.add(run_id)
        return active

    def _approval_candidates(
        self,
        policy: GenerationArtifactRetentionPolicy,
        now: datetime,
    ) -> list[GenerationArtifactRetentionCandidate]:
        path = self.reports_dir / "generation-launch-guard-approvals.json"
        payload = self._read_json(path, {})
        records = payload.get("approvals") if isinstance(payload.get("approvals"), list) else []
        cutoff = now - timedelta(days=policy.approval_record_days)
        result: list[GenerationArtifactRetentionCandidate] = []
        for item in records:
            if not isinstance(item, dict):
                continue
            project = str(item.get("project_name") or "")
            if policy.project_name and project.casefold() != policy.project_name.casefold():
                continue
            status = self._approval_status(item, now)
            created = self._timestamp(item.get("created_at"), path)
            if status not in self.TERMINAL_APPROVAL_STATES or created > cutoff:
                continue
            identifier = str(item.get("approval_id") or "unknown")
            result.append(
                self._candidate(
                    project_name=project,
                    artifact_type="guard_approval",
                    identifier=identifier,
                    path=path,
                    created=created,
                    now=now,
                    action="archive" if policy.archive_before_delete else "delete",
                    reason=f"Terminal approval older than {policy.approval_record_days} day(s).",
                    virtual_record=True,
                )
            )
        return result

    def _budget_candidates(
        self,
        policy: GenerationArtifactRetentionPolicy,
        now: datetime,
    ) -> list[GenerationArtifactRetentionCandidate]:
        path = self.reports_dir / "generation-budget-guard.json"
        payload = self._read_json(path, {})
        cutoff = now - timedelta(days=policy.budget_record_days)
        result: list[GenerationArtifactRetentionCandidate] = []
        for collection, artifact_type, id_key in (
            ("reservations", "budget_reservation", "reservation_id"),
            ("approvals", "budget_approval", "approval_id"),
        ):
            records = payload.get(collection) if isinstance(payload.get(collection), list) else []
            for item in records:
                if not isinstance(item, dict):
                    continue
                project = str(item.get("project_name") or "")
                if policy.project_name and project.casefold() != policy.project_name.casefold():
                    continue
                status = self._budget_status(item, now)
                created = self._timestamp(item.get("created_at"), path)
                if status not in self.TERMINAL_BUDGET_STATES or created > cutoff:
                    continue
                identifier = str(item.get(id_key) or "unknown")
                result.append(
                    self._candidate(
                        project_name=project,
                        artifact_type=artifact_type,
                        identifier=identifier,
                        path=path,
                        created=created,
                        now=now,
                        action="archive" if policy.archive_before_delete else "delete",
                        reason=f"Terminal budget record older than {policy.budget_record_days} day(s).",
                        virtual_record=True,
                    )
                )
        return result

    def _orphan_candidates(
        self,
        policy: GenerationArtifactRetentionPolicy,
        now: datetime,
    ) -> list[GenerationArtifactRetentionCandidate]:
        cutoff = now - timedelta(days=policy.orphan_grace_days)
        result: list[GenerationArtifactRetentionCandidate] = []
        reverse = {
            companion: primary
            for primary, companions in self.COMPANIONS.items()
            for companion in companions
        }
        for name in self.KNOWN_COMPANIONS:
            for path in self.reports_dir.rglob(name):
                if self._excluded_path(path) or not self._project_matches(path, policy.project_name):
                    continue
                primary = path.with_name(reverse[name])
                created = self._timestamp(None, path)
                if primary.exists() or created > cutoff:
                    continue
                result.append(
                    self._candidate(
                        project_name=self._project_from_path(path),
                        artifact_type="orphan",
                        identifier=path.parent.name,
                        path=path,
                        created=created,
                        now=now,
                        action="archive" if policy.archive_before_delete else "delete",
                        reason=f"Companion file has no primary JSON after {policy.orphan_grace_days} day(s).",
                    )
                )
        return result

    def _create_archive(
        self,
        run_id: str,
        preview: GenerationArtifactRetentionPreview,
        candidates: list[GenerationArtifactRetentionCandidate],
    ) -> tuple[Path, Path, str, int]:
        folder = self.reports_dir / self.ARCHIVE_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        safe = self._safe_name(preview.project_name or "all-projects")
        archive_path = folder / f"{run_id}-{safe}.zip"
        manifest_path = folder / f"{run_id}-{safe}.manifest.json"
        rows = [self._candidate_row(item) for item in candidates]
        virtual_records = self._virtual_record_snapshots(candidates)
        manifest = {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": run_id,
            "preview_id": preview.preview_id,
            "created_at": self._now().isoformat(),
            "project_name": preview.project_name,
            "candidate_count": len(candidates),
            "candidates": rows,
            "virtual_records": virtual_records,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        added: set[str] = set()
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("_retention_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
            for item in candidates:
                if item.virtual_record:
                    continue
                for path in (item.path, *item.related_paths):
                    if not path.is_file():
                        continue
                    relative = self._relative(path)
                    if relative in added:
                        continue
                    archive.write(path, relative)
                    added.add(relative)
        return archive_path, manifest_path, self._sha256(archive_path), len(candidates)

    def _remove_virtual_records(self, candidate_ids: set[str]) -> tuple[int, list[str]]:
        deleted = 0
        errors: list[str] = []
        approval_path = self.reports_dir / "generation-launch-guard-approvals.json"
        budget_path = self.reports_dir / "generation-budget-guard.json"
        for path, collections, id_keys in (
            (approval_path, ("approvals",), {"approvals": "approval_id"}),
            (budget_path, ("reservations", "approvals"), {"reservations": "reservation_id", "approvals": "approval_id"}),
        ):
            if not path.exists():
                continue
            payload = self._read_json(path, {})
            changed = False
            for collection in collections:
                records = payload.get(collection)
                if not isinstance(records, list):
                    continue
                key = id_keys[collection]
                kept = []
                for item in records:
                    identifier = str(item.get(key) or "") if isinstance(item, dict) else ""
                    artifact_type = (
                        "guard_approval"
                        if path == approval_path
                        else "budget_reservation" if collection == "reservations" else "budget_approval"
                    )
                    candidate_id = self._candidate_id(artifact_type, identifier, path)
                    if candidate_id in candidate_ids:
                        deleted += 1
                        changed = True
                    else:
                        kept.append(item)
                payload[collection] = kept
            if changed:
                payload["updated_at"] = self._now().isoformat()
                try:
                    self._atomic_json(path, payload)
                except OSError as exc:
                    errors.append(f"{path.name}: {self._sanitize(exc)}")
        return deleted, errors

    def _delete_candidate_files(self, candidate: GenerationArtifactRetentionCandidate) -> int:
        reclaimed = 0
        for path in (candidate.path, *candidate.related_paths):
            if path.is_file():
                reclaimed += path.stat().st_size
                path.unlink()
        parent = candidate.path.parent
        if parent != self.reports_dir and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                pass
        return reclaimed

    def _virtual_record_snapshots(
        self, candidates: Iterable[GenerationArtifactRetentionCandidate]
    ) -> list[dict[str, object]]:
        requested = {item.candidate_id for item in candidates if item.virtual_record}
        if not requested:
            return []
        snapshots: list[dict[str, object]] = []
        for path, collections, keys in (
            (self.reports_dir / "generation-launch-guard-approvals.json", ("approvals",), {"approvals": "approval_id"}),
            (self.reports_dir / "generation-budget-guard.json", ("reservations", "approvals"), {"reservations": "reservation_id", "approvals": "approval_id"}),
        ):
            payload = self._read_json(path, {})
            for collection in collections:
                records = payload.get(collection) if isinstance(payload.get(collection), list) else []
                artifact_type = (
                    "guard_approval"
                    if path.name.startswith("generation-launch")
                    else "budget_reservation" if collection == "reservations" else "budget_approval"
                )
                for item in records:
                    if not isinstance(item, dict):
                        continue
                    identifier = str(item.get(keys[collection]) or "")
                    if self._candidate_id(artifact_type, identifier, path) in requested:
                        snapshots.append(
                            {
                                "artifact_type": artifact_type,
                                "identifier": identifier,
                                "record": self._sanitize_structure(item),
                            }
                        )
        return snapshots

    def _record_run(self, run: GenerationArtifactRetentionRun) -> None:
        path = self._run_index_path()
        payload = self._read_json(path, {"schema_version": 1, "runs": []})
        records = payload.setdefault("runs", [])
        if not isinstance(records, list):
            records = []
            payload["runs"] = records
        record = asdict(run)
        record["archive_path"] = str(run.archive_path or "")
        record["manifest_path"] = str(run.manifest_path or "")
        records.append(record)
        payload["runs"] = records[-200:]
        payload["updated_at"] = self._now().isoformat()
        self._atomic_json(path, payload)

    def _candidate(
        self,
        *,
        project_name: str,
        artifact_type: str,
        identifier: str,
        path: Path,
        created: datetime,
        now: datetime,
        action: str,
        reason: str,
        integrity_status: str = "unknown",
        related_paths: tuple[Path, ...] = (),
        virtual_record: bool = False,
        protected: bool = False,
    ) -> GenerationArtifactRetentionCandidate:
        size = 0 if virtual_record else sum(
            item.stat().st_size for item in (path, *related_paths) if item.is_file()
        )
        return GenerationArtifactRetentionCandidate(
            candidate_id=self._candidate_id(artifact_type, identifier, path),
            project_name=project_name,
            artifact_type=artifact_type,
            identifier=identifier,
            path=path,
            created_at=created.isoformat(),
            age_days=max(0, int((now - created).total_seconds() // 86400)),
            size_bytes=size,
            action=action,
            reason=reason,
            integrity_status=integrity_status,
            related_paths=related_paths,
            virtual_record=virtual_record,
            protected=protected,
        )

    @staticmethod
    def _candidate_id(artifact_type: str, identifier: str, path: Path) -> str:
        raw = f"{artifact_type}|{identifier}|{path.as_posix()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _identifier(payload: dict[str, object], path: Path) -> str:
        for key in ("receipt_id", "run_id", "resume_id"):
            value = str(payload.get(key) or "")
            if value:
                return value
        return path.parent.name

    @staticmethod
    def _integrity_status(payload: dict[str, object]) -> str:
        if not payload:
            return "unreadable"
        integrity = payload.get("integrity")
        if not isinstance(integrity, dict):
            return "legacy"
        expected = str(integrity.get("digest") or "")
        if not expected:
            return "mismatch"
        clean = dict(payload)
        clean.pop("integrity", None)
        serialized = json.dumps(clean, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
        actual = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return "verified" if actual == expected else "mismatch"

    @staticmethod
    def _budget_status(item: dict[str, object], now: datetime) -> str:
        status = str(item.get("status") or "").casefold()
        if status in {"active", "approved"}:
            expires = GenerationArtifactRetentionService._parse(item.get("expires_at"))
            if expires != datetime.min.replace(tzinfo=timezone.utc) and expires <= now:
                return "expired"
            used = GenerationArtifactRetentionService._integer(item.get("used_count"))
            maximum = max(1, GenerationArtifactRetentionService._integer(item.get("max_uses"), 1))
            if status == "approved" and used >= maximum:
                return "consumed"
        return status

    @staticmethod
    def _approval_status(item: dict[str, object], now: datetime) -> str:
        status = str(item.get("status") or "approved").casefold()
        if status == "approved":
            expires = GenerationArtifactRetentionService._parse(item.get("expires_at"))
            used = GenerationArtifactRetentionService._integer(item.get("used_count"))
            maximum = max(1, GenerationArtifactRetentionService._integer(item.get("max_uses"), 1))
            if expires <= now:
                return "expired"
            if used >= maximum:
                return "consumed"
        return status

    def _preview_digest(
        self,
        policy: GenerationArtifactRetentionPolicy,
        candidates: list[GenerationArtifactRetentionCandidate],
        now: datetime,
    ) -> str:
        payload = {
            "policy": asdict(policy),
            "day": now.date().isoformat(),
            "candidates": [
                {
                    "candidate_id": item.candidate_id,
                    "action": item.action,
                    "size_bytes": item.size_bytes,
                    "created_at": item.created_at,
                    "integrity_status": item.integrity_status,
                    "path_state": self._path_state(item.path),
                    "related_state": [self._path_state(path) for path in item.related_paths],
                }
                for item in candidates
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _deduplicate(
        candidates: Iterable[GenerationArtifactRetentionCandidate],
    ) -> list[GenerationArtifactRetentionCandidate]:
        unique: dict[str, GenerationArtifactRetentionCandidate] = {}
        for item in candidates:
            unique[item.candidate_id] = item
        return list(unique.values())

    def _excluded_path(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.reports_dir)
        except ValueError:
            return True
        return bool(relative.parts and relative.parts[0] in {self.ARCHIVE_FOLDER, self.AUDIT_FOLDER})

    def _project_matches(self, path: Path, project_name: str) -> bool:
        return self._project_name_matches(self._project_from_path(path), project_name)

    @classmethod
    def _project_name_matches(cls, candidate: str, requested: str) -> bool:
        if not requested:
            return True
        return candidate.casefold() == requested.casefold() or cls._safe_name(candidate).casefold() == cls._safe_name(requested).casefold()

    def _payload_project(self, payload: dict[str, object], path: Path) -> str:
        direct = str(payload.get("project_name") or "")
        if direct:
            return direct
        project = payload.get("project")
        if isinstance(project, dict) and str(project.get("name") or ""):
            return str(project.get("name") or "")
        return self._project_from_path(path)

    def _project_from_path(self, path: Path) -> str:
        try:
            relative = path.relative_to(self.reports_dir)
        except ValueError:
            return ""
        return relative.parts[0] if relative.parts else ""

    @staticmethod
    def _path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except OSError:
            return str(path).casefold()

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.reports_dir).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _path_state(path: Path) -> dict[str, object]:
        try:
            stat = path.stat()
        except OSError:
            return {"exists": False, "size": 0, "mtime_ns": 0}
        return {"exists": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    @staticmethod
    def _candidate_row(item: GenerationArtifactRetentionCandidate) -> dict[str, object]:
        return {
            "candidate_id": item.candidate_id,
            "project_name": item.project_name,
            "artifact_type": item.artifact_type,
            "identifier": item.identifier,
            "created_at": item.created_at,
            "age_days": item.age_days,
            "size_bytes": item.size_bytes,
            "action": item.action,
            "reason": item.reason,
            "integrity_status": item.integrity_status,
            "path": str(item.path),
            "related_paths": ";".join(str(path) for path in item.related_paths),
            "virtual_record": item.virtual_record,
            "protected": item.protected,
        }

    @staticmethod
    def _empty_candidate() -> GenerationArtifactRetentionCandidate:
        return GenerationArtifactRetentionCandidate("", "", "", "", Path(""), "", 0, 0, "", "")

    def _policy_path(self) -> Path:
        return self.reports_dir / self.AUDIT_FOLDER / self.POLICY_NAME

    def _run_index_path(self) -> Path:
        return self.reports_dir / self.AUDIT_FOLDER / self.RUN_INDEX_NAME

    @staticmethod
    def _read_json(path: Path, default: dict[str, object]) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return dict(default)
        return payload if isinstance(payload, dict) else dict(default)

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _timestamp(self, value: object, path: Path) -> datetime:
        parsed = self._parse(value)
        if parsed != datetime.min.replace(tzinfo=timezone.utc):
            return parsed
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return self._now()

    @staticmethod
    def _parse(value: object) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _project_key(value: str) -> str:
        return str(value or "all-projects").strip().casefold() or "all-projects"

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._") or "unknown"

    @staticmethod
    def _days(value: object, default: int) -> int:
        return min(3650, max(1, GenerationArtifactRetentionService._integer(value, default)))

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _boolean(value: object, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    @classmethod
    def _sanitize(cls, value: object) -> str:
        return cls.SECRET_VALUE.sub("[REDACTED]", str(value or ""))[:2000]

    @classmethod
    def _sanitize_structure(cls, value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): cls._sanitize_structure(item)
                for key, item in value.items()
                if str(key).casefold() not in {"api_key", "token", "secret", "password"}
            }
        if isinstance(value, list):
            return [cls._sanitize_structure(item) for item in value]
        if isinstance(value, str):
            return cls._sanitize(value)
        return value

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
