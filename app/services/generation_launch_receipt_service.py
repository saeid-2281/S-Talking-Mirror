from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.models.generation_launch_receipt import (
    GenerationLaunchGuardApproval,
    GenerationLaunchGuardApprovalEvent,
    GenerationLaunchGuardApprovalSummary,
    GenerationLaunchGuardDecision,
    GenerationLaunchGuardPolicy,
    GenerationLaunchGuardPolicyHistoryEntry,
    GenerationLaunchGuardPolicyProfile,
    GenerationLaunchReceipt,
    GenerationLaunchReceiptChange,
    GenerationLaunchReceiptComparison,
    GenerationLaunchReceiptSummary,
)


class GenerationLaunchReceiptService:
    """Discover, verify, filter, summarize, and export launch receipts."""

    RECEIPT_NAME = "generation-launch.json"
    # Public filename contract shared with execution and recovery receipt services.
    FILE_NAME = RECEIPT_NAME
    MARKDOWN_NAME = "generation-launch.md"
    BASELINE_INDEX_NAME = "generation-launch-receipt-baselines.json"
    GUARD_POLICY_INDEX_NAME = "generation-launch-guard-policies.json"
    GUARD_PROFILE_INDEX_NAME = "generation-launch-guard-policy-profiles.json"
    GUARD_APPROVAL_INDEX_NAME = "generation-launch-guard-approvals.json"
    GUARD_MODES = {"off", "warn", "enforce"}
    GUARD_CATEGORIES = (
        "Provider",
        "Output format",
        "Output policy",
        "Execution",
        "Scope",
        "Risk and cost",
        "Integrity",
    )
    BUILTIN_GUARD_PROFILES = (
        {
            "profile_id": "strict-production",
            "name": "Strict production",
            "description": "Enforce all protected launch categories for production work.",
            "mode": "enforce",
            "protected_categories": GUARD_CATEGORIES,
        },
        {
            "profile_id": "balanced",
            "name": "Balanced",
            "description": "Warn on drift across all launch categories and require acknowledgement.",
            "mode": "warn",
            "protected_categories": GUARD_CATEGORIES,
        },
        {
            "profile_id": "experimental",
            "name": "Experimental",
            "description": "Warn only for output policy, risk and integrity while allowing rapid iteration.",
            "mode": "warn",
            "protected_categories": ("Output policy", "Risk and cost", "Integrity"),
        },
        {
            "profile_id": "provider-migration",
            "name": "Provider migration",
            "description": "Allow provider changes while protecting output, execution, scope, cost and integrity.",
            "mode": "warn",
            "protected_categories": (
                "Output format",
                "Output policy",
                "Execution",
                "Scope",
                "Risk and cost",
                "Integrity",
            ),
        },
    )

    def __init__(self, reports_dir: Path) -> None:
        self.reports_dir = Path(reports_dir)

    def list_receipts(
        self,
        *,
        project_name: str | None = None,
        provider: str | None = None,
        integrity_status: str | None = None,
        risk_level: str | None = None,
        search: str = "",
        limit: int = 500,
    ) -> list[GenerationLaunchReceipt]:
        receipts = [self.load(path) for path in self._receipt_paths()]
        project_key = str(project_name or "").strip().casefold()
        provider_key = str(provider or "").strip().casefold()
        integrity_key = str(integrity_status or "").strip().casefold()
        risk_key = str(risk_level or "").strip().casefold()
        search_key = str(search or "").strip().casefold()

        filtered: list[GenerationLaunchReceipt] = []
        for receipt in receipts:
            if project_key and receipt.project_name.casefold() != project_key:
                continue
            if provider_key and receipt.provider.casefold() != provider_key:
                continue
            if integrity_key and receipt.integrity_status.casefold() != integrity_key:
                continue
            if risk_key and receipt.risk_level.casefold() != risk_key:
                continue
            if search_key and search_key not in self._search_text(receipt):
                continue
            filtered.append(receipt)

        filtered.sort(key=lambda item: (item.created_at, str(item.path)), reverse=True)
        return filtered[: max(0, int(limit))]

    def latest(self, *, project_name: str | None = None) -> GenerationLaunchReceipt | None:
        records = self.list_receipts(project_name=project_name, limit=1)
        return records[0] if records else None

    def load(self, path: Path) -> GenerationLaunchReceipt:
        receipt_path = Path(path)
        markdown_path = receipt_path.with_name(self.MARKDOWN_NAME)
        try:
            payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Receipt root must be a JSON object.")
        except Exception as exc:
            return self._unreadable(receipt_path, markdown_path, str(exc))

        integrity_status, integrity_message = self.verify_payload(payload)
        scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        plan = payload.get("generation_plan") if isinstance(payload.get("generation_plan"), dict) else {}
        guard_policy = payload.get("guard_policy") if isinstance(payload.get("guard_policy"), dict) else {}
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        unified_decision = (
            payload.get("unified_decision")
            if isinstance(payload.get("unified_decision"), dict)
            else {}
        )
        return GenerationLaunchReceipt(
            path=receipt_path,
            markdown_path=markdown_path,
            schema_version=self._integer(payload.get("schema_version"), 1),
            receipt_id=str(payload.get("receipt_id") or ""),
            created_at=str(payload.get("created_at") or self._mtime(receipt_path)),
            project_name=str(payload.get("project_name") or receipt_path.parents[2].name),
            launch_fingerprint=str(payload.get("launch_fingerprint") or ""),
            preflight_status=str(payload.get("preflight_status") or "unknown"),
            review_status=str(payload.get("review_status") or "unknown"),
            provider=str(settings.get("provider") or "unknown"),
            model_id=str(settings.get("model_id") or ""),
            voice_id=str(settings.get("voice_id") or ""),
            language_code=str(settings.get("language_code") or ""),
            file_extension=str(settings.get("file_extension") or ""),
            max_retries=self._integer(settings.get("max_retries")),
            delay_seconds=self._number(settings.get("delay_seconds")),
            skip_existing=self._boolean(settings.get("skip_existing")),
            overwrite_existing=self._boolean(settings.get("overwrite_existing")),
            generation_scope=str(settings.get("generation_scope") or ""),
            execution_order=str(settings.get("execution_order") or ""),
            output_directory=str(payload.get("output_directory") or ""),
            files=self._integer(scope.get("files")),
            characters=self._integer(scope.get("characters")),
            provider_requests=self._integer(scope.get("provider_requests")),
            existing_outputs=self._integer(scope.get("existing_outputs")),
            risk_level=str(plan.get("risk_level") or "unknown"),
            estimated_cost=self._number(plan.get("estimated_cost")),
            estimated_duration_seconds=self._number(plan.get("estimated_duration_seconds")),
            currency=str(plan.get("currency") or "USD").upper(),
            acknowledged_codes=self._strings(payload.get("acknowledged_codes")),
            required_acknowledgements=self._strings(
                payload.get("required_acknowledgements")
            ),
            integrity_status=integrity_status,
            integrity_message=integrity_message,
            guard_approval_id=str(
                (payload.get("guard_exception") or {}).get("approval_id")
                if isinstance(payload.get("guard_exception"), dict)
                else ""
            ),
            guard_policy_profile_id=str(guard_policy.get("profile_id") or ""),
            guard_policy_version=max(0, self._integer(guard_policy.get("version"))),
            guard_policy_locked=self._boolean(guard_policy.get("locked")),
            decision_status=str(unified_decision.get("status") or ""),
            decision_trace_id=str(unified_decision.get("trace_id") or ""),
            decision_summary=str(unified_decision.get("summary") or ""),
            run_id=str(execution.get("run_id") or ""),
            execution_session_path=str(execution.get("session_path") or ""),
        )

    @classmethod
    def canonical_digest(cls, payload: dict[str, object]) -> str:
        canonical = dict(payload)
        canonical.pop("integrity", None)
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def verify_payload(cls, payload: dict[str, object]) -> tuple[str, str]:
        schema_version = cls._integer(payload.get("schema_version"), 1)
        integrity = payload.get("integrity")
        if schema_version < 2 and not isinstance(integrity, dict):
            return "legacy", "Receipt predates integrity metadata."
        if not isinstance(integrity, dict):
            return "mismatch", "Integrity metadata is missing."
        algorithm = str(integrity.get("algorithm") or "").casefold()
        expected = str(integrity.get("digest") or "").casefold()
        if algorithm != "sha256" or not expected:
            return "mismatch", "Integrity metadata is incomplete or unsupported."
        actual = cls.canonical_digest(payload)
        if actual != expected:
            return "mismatch", "Receipt content no longer matches its SHA-256 digest."
        return "verified", "Receipt content matches its SHA-256 digest."

    @staticmethod
    def summary(records: Iterable[GenerationLaunchReceipt]) -> GenerationLaunchReceiptSummary:
        receipts = list(records)
        return GenerationLaunchReceiptSummary(
            receipt_count=len(receipts),
            verified_count=sum(item.integrity_status == "verified" for item in receipts),
            legacy_count=sum(item.integrity_status == "legacy" for item in receipts),
            mismatch_count=sum(item.integrity_status == "mismatch" for item in receipts),
            unreadable_count=sum(item.integrity_status == "unreadable" for item in receipts),
            high_risk_count=sum(item.risk_level == "high" for item in receipts),
            confirmation_required_count=sum(
                item.review_status == "confirmation_required" for item in receipts
            ),
            total_files=sum(max(0, item.files) for item in receipts),
            total_characters=sum(max(0, item.characters) for item in receipts),
        )

    @staticmethod
    def export(
        records: Iterable[GenerationLaunchReceipt],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        receipts = list(records)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "launches"
        json_path = target / f"generation-launch-receipts-{safe_name}-{stamp}.json"
        csv_path = target / f"generation-launch-receipts-{safe_name}-{stamp}.csv"
        summary = GenerationLaunchReceiptService.summary(receipts)
        rows = [GenerationLaunchReceiptService._export_row(item) for item in receipts]
        json_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "summary": summary.__dict__,
                    "receipts": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fieldnames = list(rows[0]) if rows else list(
            GenerationLaunchReceiptService._export_row(
                GenerationLaunchReceipt(Path(""), Path(""))
            )
        )
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path


    def set_baseline(self, receipt: GenerationLaunchReceipt) -> Path:
        """Persist a trusted receipt as the project comparison baseline."""

        if not receipt.integrity_ok:
            raise ValueError("Only verified or legacy receipts can become a baseline.")
        if not receipt.path.exists():
            raise FileNotFoundError(receipt.path)
        index = self._read_baseline_index()
        projects = index.setdefault("projects", {})
        if not isinstance(projects, dict):
            projects = {}
            index["projects"] = projects
        projects[self._project_key(receipt.project_name)] = {
            "project_name": receipt.project_name,
            "receipt_id": receipt.receipt_id,
            "receipt_path": self._stored_path(receipt.path),
            "set_at": datetime.now(timezone.utc).isoformat(),
        }
        index["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_baseline_index(index)
        return self._baseline_index_path

    def baseline(self, project_name: str) -> GenerationLaunchReceipt | None:
        index = self._read_baseline_index()
        projects = index.get("projects")
        if not isinstance(projects, dict):
            return None
        entry = projects.get(self._project_key(project_name))
        if not isinstance(entry, dict):
            return None
        raw_path = str(entry.get("receipt_path") or "")
        if not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.reports_dir / path
        return self.load(path) if path.exists() else None

    def clear_baseline(self, project_name: str) -> bool:
        index = self._read_baseline_index()
        projects = index.get("projects")
        if not isinstance(projects, dict):
            return False
        removed = projects.pop(self._project_key(project_name), None) is not None
        if removed:
            index["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_baseline_index(index)
        return removed

    def is_baseline(self, receipt: GenerationLaunchReceipt) -> bool:
        baseline = self.baseline(receipt.project_name)
        if baseline is None:
            return False
        try:
            return baseline.path.resolve() == receipt.path.resolve()
        except OSError:
            return str(baseline.path) == str(receipt.path)

    def list_guard_policy_profiles(self) -> list[GenerationLaunchGuardPolicyProfile]:
        """Return built-in and custom reusable guard-policy templates."""

        profiles = [self._profile_from_record(item, built_in=True) for item in self.BUILTIN_GUARD_PROFILES]
        payload = self._read_guard_profile_index()
        records = payload.get("profiles")
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            try:
                profile = self._profile_from_record(record, built_in=False)
            except ValueError:
                continue
            if any(item.profile_id == profile.profile_id for item in profiles):
                continue
            profiles.append(profile)
        profiles.sort(key=lambda item: (not item.built_in, item.name.casefold(), item.profile_id))
        return profiles

    def guard_policy_profile(self, profile_id: str) -> GenerationLaunchGuardPolicyProfile | None:
        key = str(profile_id or "").strip().casefold()
        return next((item for item in self.list_guard_policy_profiles() if item.profile_id.casefold() == key), None)

    def default_guard_policy_profile_id(self) -> str:
        payload = self._read_guard_profile_index()
        profile_id = str(payload.get("default_profile_id") or "balanced").strip()
        return profile_id if self.guard_policy_profile(profile_id) is not None else "balanced"

    def set_default_guard_policy_profile(self, profile_id: str) -> Path:
        profile = self.guard_policy_profile(profile_id)
        if profile is None:
            raise ValueError("Select an existing guard policy profile.")
        payload = self._read_guard_profile_index()
        payload["default_profile_id"] = profile.profile_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._write_guard_profile_index(payload)
        return self._guard_profile_index_path

    def save_guard_policy_profile(
        self,
        *,
        name: str,
        description: str,
        mode: str,
        protected_categories: Iterable[str],
        profile_id: str = "",
    ) -> GenerationLaunchGuardPolicyProfile:
        """Create or update a custom secret-free guard policy profile."""

        title = str(name or "").strip()
        if len(title) < 3:
            raise ValueError("Profile name must contain at least 3 characters.")
        normalized_mode = str(mode or "").strip().casefold()
        if normalized_mode not in self.GUARD_MODES:
            raise ValueError("Guard mode must be off, warn or enforce.")
        categories = tuple(
            dict.fromkeys(
                item
                for item in protected_categories
                if item in self.GUARD_CATEGORIES
            )
        )
        if normalized_mode != "off" and not categories:
            raise ValueError("Select at least one protected launch category.")
        requested_id = str(profile_id or "").strip().casefold()
        if requested_id and self.guard_policy_profile(requested_id) is not None:
            existing = self.guard_policy_profile(requested_id)
            if existing is not None and existing.built_in:
                raise ValueError("Built-in guard policy profiles cannot be overwritten.")
        safe_slug = re.sub(r"[^a-z0-9._-]+", "-", title.casefold()).strip("-._") or "profile"
        safe_id = requested_id or f"custom-{safe_slug}"
        if safe_id in {str(item["profile_id"]) for item in self.BUILTIN_GUARD_PROFILES}:
            raise ValueError("Built-in guard policy profile IDs are reserved.")
        now = datetime.now(timezone.utc).isoformat()
        payload = self._read_guard_profile_index()
        records = payload.setdefault("profiles", [])
        if not isinstance(records, list):
            records = []
            payload["profiles"] = records
        previous = next(
            (item for item in records if isinstance(item, dict) and str(item.get("profile_id") or "").casefold() == safe_id),
            None,
        )
        record = {
            "profile_id": safe_id,
            "name": title,
            "description": str(description or "").strip(),
            "mode": normalized_mode,
            "protected_categories": list(categories),
            "created_at": str(previous.get("created_at") or now) if isinstance(previous, dict) else now,
            "updated_at": now,
        }
        if isinstance(previous, dict):
            previous.clear()
            previous.update(record)
        else:
            records.append(record)
        payload["updated_at"] = now
        self._write_guard_profile_index(payload)
        return self._profile_from_record(record, built_in=False)

    def delete_guard_policy_profile(self, profile_id: str) -> bool:
        key = str(profile_id or "").strip().casefold()
        profile = self.guard_policy_profile(key)
        if profile is None:
            return False
        if profile.built_in:
            raise ValueError("Built-in guard policy profiles cannot be deleted.")
        if self.default_guard_policy_profile_id().casefold() == key:
            raise ValueError("Choose another default profile before deleting this one.")
        policy_payload = self._read_guard_policy_index()
        projects = policy_payload.get("projects")
        if isinstance(projects, dict) and any(
            isinstance(record, dict) and str(record.get("profile_id") or "").casefold() == key
            for record in projects.values()
        ):
            raise ValueError("This profile is still assigned to a project policy.")
        payload = self._read_guard_profile_index()
        records = payload.get("profiles")
        if not isinstance(records, list):
            return False
        before = len(records)
        payload["profiles"] = [
            record
            for record in records
            if not (
                isinstance(record, dict)
                and str(record.get("profile_id") or "").casefold() == key
            )
        ]
        removed = len(payload["profiles"]) != before
        if removed:
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_guard_profile_index(payload)
        return removed

    def export_guard_policy_profiles(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "default_profile_id": self.default_guard_policy_profile_id(),
            "profiles": [
                {
                    "profile_id": item.profile_id,
                    "name": item.name,
                    "description": item.description,
                    "mode": item.mode,
                    "protected_categories": list(item.protected_categories),
                    "built_in": item.built_in,
                }
                for item in self.list_guard_policy_profiles()
            ],
        }
        destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return destination

    def import_guard_policy_profiles(self, source: Path) -> tuple[GenerationLaunchGuardPolicyProfile, ...]:
        source = Path(source)
        payload = json.loads(source.read_text(encoding="utf-8"))
        records = payload.get("profiles") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ValueError("Guard policy profile import must contain a profiles list.")
        imported: list[GenerationLaunchGuardPolicyProfile] = []
        for record in records:
            if not isinstance(record, dict) or bool(record.get("built_in")):
                continue
            imported.append(
                self.save_guard_policy_profile(
                    profile_id=str(record.get("profile_id") or ""),
                    name=str(record.get("name") or ""),
                    description=str(record.get("description") or ""),
                    mode=str(record.get("mode") or "warn"),
                    protected_categories=self._strings(record.get("protected_categories")),
                )
            )
        return tuple(imported)

    def compare_guard_policy_to_profile(
        self,
        policy: GenerationLaunchGuardPolicy,
        profile: GenerationLaunchGuardPolicyProfile,
    ) -> tuple[str, ...]:
        differences: list[str] = []
        if policy.mode != profile.mode:
            differences.append(f"Mode: {policy.mode} → {profile.mode}")
        current = set(policy.protected_categories)
        target = set(profile.protected_categories)
        added = [item for item in self.GUARD_CATEGORIES if item in target - current]
        removed = [item for item in self.GUARD_CATEGORIES if item in current - target]
        if added:
            differences.append("Protect additionally: " + ", ".join(added))
        if removed:
            differences.append("Stop protecting: " + ", ".join(removed))
        return tuple(differences)

    def guard_policy(self, project_name: str) -> GenerationLaunchGuardPolicy:
        project = str(project_name or "").strip()
        default_profile = self.guard_policy_profile(self.default_guard_policy_profile_id())
        if not project:
            return GenerationLaunchGuardPolicy(
                project_name="",
                mode="off",
                protected_categories=self.GUARD_CATEGORIES,
                profile_id=default_profile.profile_id if default_profile else "balanced",
                profile_name=default_profile.name if default_profile else "Balanced",
            )
        payload = self._read_guard_policy_index()
        projects = payload.get("projects")
        record = (
            projects.get(self._project_key(project), {})
            if isinstance(projects, dict)
            else {}
        )
        if not isinstance(record, dict) or not record:
            profile = default_profile or self.guard_policy_profile("balanced")
            return GenerationLaunchGuardPolicy(
                project_name=project,
                mode=profile.mode if profile else "warn",
                protected_categories=profile.protected_categories if profile else self.GUARD_CATEGORIES,
                profile_id=profile.profile_id if profile else "balanced",
                profile_name=profile.name if profile else "Balanced",
            )
        mode = str(record.get("mode") or "warn").casefold()
        if mode not in self.GUARD_MODES:
            mode = "warn"
        categories = tuple(
            item
            for item in self._strings(record.get("protected_categories"))
            if item in self.GUARD_CATEGORIES
        )
        profile_id = str(record.get("profile_id") or "")
        profile = self.guard_policy_profile(profile_id) if profile_id else None
        history = record.get("history")
        return GenerationLaunchGuardPolicy(
            project_name=str(record.get("project_name") or project),
            mode=mode,
            protected_categories=categories or self.GUARD_CATEGORIES,
            updated_at=str(record.get("updated_at") or ""),
            profile_id=profile_id,
            profile_name=str(record.get("profile_name") or (profile.name if profile else "Custom")),
            locked=self._boolean(record.get("locked")),
            version=max(0, self._integer(record.get("version"))),
            updated_by=str(record.get("updated_by") or ""),
            history_count=len(history) if isinstance(history, list) else 0,
        )

    def guard_policy_history(self, project_name: str) -> tuple[GenerationLaunchGuardPolicyHistoryEntry, ...]:
        payload = self._read_guard_policy_index()
        projects = payload.get("projects")
        record = projects.get(self._project_key(project_name), {}) if isinstance(projects, dict) else {}
        history = record.get("history") if isinstance(record, dict) else None
        entries: list[GenerationLaunchGuardPolicyHistoryEntry] = []
        for item in history if isinstance(history, list) else []:
            if not isinstance(item, dict):
                continue
            entries.append(
                GenerationLaunchGuardPolicyHistoryEntry(
                    version=max(0, self._integer(item.get("version"))),
                    occurred_at=str(item.get("occurred_at") or ""),
                    action=str(item.get("action") or "updated"),
                    actor=str(item.get("actor") or ""),
                    profile_id=str(item.get("profile_id") or ""),
                    profile_name=str(item.get("profile_name") or ""),
                    mode=str(item.get("mode") or "warn"),
                    protected_categories=self._strings(item.get("protected_categories")),
                    locked=self._boolean(item.get("locked")),
                    note=str(item.get("note") or ""),
                )
            )
        entries.sort(key=lambda item: item.version, reverse=True)
        return tuple(entries)

    def set_guard_policy(
        self,
        project_name: str,
        *,
        mode: str,
        protected_categories: Iterable[str] | None = None,
        profile_id: str = "",
        locked: bool | None = None,
        updated_by: str = "Operator",
        note: str = "",
        override_lock: bool = False,
        action: str = "updated",
    ) -> Path:
        project = str(project_name or "").strip()
        if not project:
            raise ValueError("A project is required for baseline guard policy.")
        normalized_mode = str(mode or "").strip().casefold()
        if normalized_mode not in self.GUARD_MODES:
            raise ValueError("Guard mode must be off, warn or enforce.")
        source_categories = (
            self.GUARD_CATEGORIES
            if protected_categories is None
            else protected_categories
        )
        categories = tuple(
            dict.fromkeys(
                item
                for item in source_categories
                if item in self.GUARD_CATEGORIES
            )
        )
        if normalized_mode != "off" and not categories:
            raise ValueError("Select at least one protected launch category.")
        payload = self._read_guard_policy_index()
        projects = payload.setdefault("projects", {})
        if not isinstance(projects, dict):
            projects = {}
            payload["projects"] = projects
        key = self._project_key(project)
        previous = projects.get(key, {})
        if not isinstance(previous, dict):
            previous = {}
        previous_policy = self.guard_policy(project)
        requested_profile = self.guard_policy_profile(profile_id) if profile_id else None
        effective_profile_id = requested_profile.profile_id if requested_profile else str(profile_id or "")
        effective_profile_name = requested_profile.name if requested_profile else ("Custom" if effective_profile_id else "Custom")
        target_locked = previous_policy.locked if locked is None else bool(locked)
        changed = (
            previous_policy.mode != normalized_mode
            or tuple(previous_policy.protected_categories) != categories
            or previous_policy.profile_id != effective_profile_id
            or previous_policy.locked != target_locked
        )
        if previous_policy.locked and changed and not override_lock:
            raise ValueError("This project guard policy is locked. Unlock it before making changes.")
        now = datetime.now(timezone.utc).isoformat()
        version = max(0, self._integer(previous.get("version"))) + 1
        history = previous.get("history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "version": version,
                "occurred_at": now,
                "action": str(action or "updated"),
                "actor": str(updated_by or "Operator").strip(),
                "profile_id": effective_profile_id,
                "profile_name": effective_profile_name,
                "mode": normalized_mode,
                "protected_categories": list(categories),
                "locked": target_locked,
                "note": str(note or "").strip(),
            }
        )
        projects[key] = {
            "project_name": project,
            "mode": normalized_mode,
            "protected_categories": list(categories),
            "updated_at": now,
            "profile_id": effective_profile_id,
            "profile_name": effective_profile_name,
            "locked": target_locked,
            "version": version,
            "updated_by": str(updated_by or "Operator").strip(),
            "history": history[-100:],
        }
        payload["updated_at"] = now
        self._write_guard_policy_index(payload)
        return self._guard_policy_index_path

    def apply_guard_policy_profile(
        self,
        project_name: str,
        profile_id: str,
        *,
        locked: bool = False,
        updated_by: str = "Operator",
        note: str = "",
        override_lock: bool = False,
    ) -> GenerationLaunchGuardPolicy:
        profile = self.guard_policy_profile(profile_id)
        if profile is None:
            raise ValueError("Select an existing guard policy profile.")
        self.set_guard_policy(
            project_name,
            mode=profile.mode,
            protected_categories=profile.protected_categories,
            profile_id=profile.profile_id,
            locked=locked,
            updated_by=updated_by,
            note=note or f"Applied profile {profile.name}.",
            override_lock=override_lock,
            action="profile_applied",
        )
        return self.guard_policy(project_name)

    def set_guard_policy_lock(
        self,
        project_name: str,
        locked: bool,
        *,
        updated_by: str = "Operator",
        note: str = "",
    ) -> GenerationLaunchGuardPolicy:
        policy = self.guard_policy(project_name)
        self.set_guard_policy(
            project_name,
            mode=policy.mode,
            protected_categories=policy.protected_categories,
            profile_id=policy.profile_id,
            locked=bool(locked),
            updated_by=updated_by,
            note=note or ("Policy locked." if locked else "Policy unlocked."),
            override_lock=True,
            action="locked" if locked else "unlocked",
        )
        return self.guard_policy(project_name)

    def create_guard_approval(
        self,
        *,
        project_name: str,
        launch_fingerprint: str,
        baseline_receipt_id: str,
        protected_change_keys: Iterable[str],
        reason: str,
        approved_by: str,
        duration_minutes: int = 60,
        max_uses: int = 1,
        renewed_from_id: str = "",
    ) -> GenerationLaunchGuardApproval:
        """Create a secret-free, time-bound exception for one exact launch preview."""

        project = str(project_name or "").strip()
        fingerprint = str(launch_fingerprint or "").strip().casefold()
        baseline_id = str(baseline_receipt_id or "").strip()
        reason_text = str(reason or "").strip()
        approver = str(approved_by or "").strip()
        if not project:
            raise ValueError("A project is required for a guard exception approval.")
        if len(fingerprint) != 64 or any(ch not in "0123456789abcdef" for ch in fingerprint):
            raise ValueError("A valid SHA-256 launch fingerprint is required.")
        if not baseline_id:
            raise ValueError("A baseline receipt ID is required.")
        if len(reason_text) < 8:
            raise ValueError("Provide a specific approval reason of at least 8 characters.")
        if not approver:
            raise ValueError("Approved by is required.")
        minutes = max(5, min(24 * 60, int(duration_minutes)))
        uses = max(1, min(10, int(max_uses)))
        keys = tuple(sorted(dict.fromkeys(str(item) for item in protected_change_keys if str(item).strip())))
        if not keys:
            raise ValueError("At least one protected change is required.")
        baseline = self.baseline(project)
        if baseline is None or not baseline.integrity_ok:
            raise ValueError("A trusted project baseline is required before approval.")
        actual_baseline_id = baseline.receipt_id or baseline.launch_fingerprint or baseline.path.name
        if actual_baseline_id != baseline_id:
            raise ValueError("The project baseline changed. Recreate the approval request.")

        now = datetime.now(timezone.utc)
        approval_seed = "|".join(
            (project.casefold(), fingerprint, baseline_id, ",".join(keys), now.isoformat())
        )
        approval_id = f"guard-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{hashlib.sha256(approval_seed.encode('utf-8')).hexdigest()[:12]}"
        record = {
            "approval_id": approval_id,
            "project_name": project,
            "launch_fingerprint": fingerprint,
            "baseline_receipt_id": baseline_id,
            "protected_change_keys": list(keys),
            "reason": reason_text,
            "approved_by": approver,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=minutes)).isoformat(),
            "max_uses": uses,
            "used_count": 0,
            "status": "approved",
            "renewed_from_id": str(renewed_from_id or "").strip(),
            "audit_events": [
                {
                    "action": "renewed" if renewed_from_id else "created",
                    "occurred_at": now.isoformat(),
                    "actor": approver,
                    "note": reason_text,
                    "receipt_id": "",
                }
            ],
        }
        payload = self._read_guard_approval_index()
        approvals = payload.setdefault("approvals", [])
        if not isinstance(approvals, list):
            approvals = []
            payload["approvals"] = approvals
        approvals.append(record)
        payload["updated_at"] = now.isoformat()
        self._write_guard_approval_index(payload)
        return self._approval_from_record(record)

    def list_guard_approvals(
        self,
        *,
        project_name: str | None = None,
        include_expired: bool = True,
        status: str | None = None,
        search: str = "",
    ) -> list[GenerationLaunchGuardApproval]:
        payload = self._read_guard_approval_index()
        records = payload.get("approvals")
        project_key = str(project_name or "").strip().casefold()
        status_key = str(status or "").strip().casefold()
        search_key = str(search or "").strip().casefold()
        approvals: list[GenerationLaunchGuardApproval] = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            approval = self._approval_from_record(record)
            if project_key and approval.project_name.casefold() != project_key:
                continue
            if not include_expired and approval.status != "approved":
                continue
            if status_key and approval.status != status_key:
                continue
            if search_key and search_key not in self._approval_search_text(approval):
                continue
            approvals.append(approval)
        approvals.sort(key=lambda item: (item.created_at, item.approval_id), reverse=True)
        return approvals

    @staticmethod
    def guard_approval_summary(
        records: Iterable[GenerationLaunchGuardApproval],
    ) -> GenerationLaunchGuardApprovalSummary:
        approvals = list(records)
        return GenerationLaunchGuardApprovalSummary(
            total_count=len(approvals),
            active_count=sum(item.status == "approved" for item in approvals),
            expired_count=sum(item.status == "expired" for item in approvals),
            consumed_count=sum(item.status == "consumed" for item in approvals),
            revoked_count=sum(item.status == "revoked" for item in approvals),
            project_count=len({item.project_name.casefold() for item in approvals if item.project_name}),
            authorized_uses=sum(max(0, item.max_uses) for item in approvals),
            used_count=sum(max(0, item.used_count) for item in approvals),
        )

    def revoke_guard_approval(self, approval_id: str) -> bool:
        payload = self._read_guard_approval_index()
        records = payload.get("approvals")
        changed = False
        for record in records if isinstance(records, list) else []:
            if isinstance(record, dict) and str(record.get("approval_id") or "") == approval_id:
                if str(record.get("status") or "approved") != "revoked":
                    now = datetime.now(timezone.utc).isoformat()
                    record["status"] = "revoked"
                    record["revoked_at"] = now
                    self._append_approval_event(
                        record,
                        action="revoked",
                        occurred_at=now,
                        actor="operator",
                        note="Approval revoked from the operations center.",
                    )
                    changed = True
                break
        if changed:
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_guard_approval_index(payload)
        return changed

    def consume_guard_approval(
        self,
        approval_id: str,
        *,
        receipt_id: str = "",
    ) -> bool:
        payload = self._read_guard_approval_index()
        records = payload.get("approvals")
        changed = False
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict) or str(record.get("approval_id") or "") != approval_id:
                continue
            approval = self._approval_from_record(record)
            if approval.status != "approved":
                return False
            record["used_count"] = approval.used_count + 1
            if int(record["used_count"]) >= approval.max_uses:
                record["status"] = "consumed"
            now = datetime.now(timezone.utc).isoformat()
            record["last_used_at"] = now
            self._append_approval_event(
                record,
                action="consumed",
                occurred_at=now,
                actor="generation",
                note="Approval use recorded after a launch receipt was written.",
                receipt_id=receipt_id,
            )
            changed = True
            break
        if changed:
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_guard_approval_index(payload)
        return changed

    def renew_guard_approval(
        self,
        approval_id: str,
        *,
        approved_by: str,
        reason: str,
        duration_minutes: int = 60,
        max_uses: int | None = None,
    ) -> GenerationLaunchGuardApproval:
        source = next(
            (item for item in self.list_guard_approvals() if item.approval_id == approval_id),
            None,
        )
        if source is None:
            raise ValueError("The selected approval no longer exists.")
        uses = source.max_uses if max_uses is None else int(max_uses)
        return self.create_guard_approval(
            project_name=source.project_name,
            launch_fingerprint=source.launch_fingerprint,
            baseline_receipt_id=source.baseline_receipt_id,
            protected_change_keys=source.protected_change_keys,
            reason=reason,
            approved_by=approved_by,
            duration_minutes=duration_minutes,
            max_uses=uses,
            renewed_from_id=source.approval_id,
        )

    def receipts_for_guard_approval(
        self,
        approval_id: str,
        *,
        limit: int = 500,
    ) -> list[GenerationLaunchReceipt]:
        key = str(approval_id or "").strip()
        if not key:
            return []
        return [
            item
            for item in self.list_receipts(limit=max(0, int(limit)))
            if item.guard_approval_id == key
        ]

    @staticmethod
    def export_guard_approvals(
        records: Iterable[GenerationLaunchGuardApproval],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        approvals = list(records)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "approvals"
        json_path = target / f"generation-launch-approvals-{safe_name}-{stamp}.json"
        csv_path = target / f"generation-launch-approvals-{safe_name}-{stamp}.csv"
        summary = GenerationLaunchReceiptService.guard_approval_summary(approvals)
        rows = [GenerationLaunchReceiptService._approval_export_row(item) for item in approvals]
        json_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "summary": summary.__dict__,
                    "approvals": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fieldnames = list(rows[0]) if rows else list(
            GenerationLaunchReceiptService._approval_export_row(
                GenerationLaunchGuardApproval("", "", "", "")
            )
        )
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path

    def matching_guard_approval(
        self,
        candidate: GenerationLaunchReceipt,
        *,
        baseline: GenerationLaunchReceipt,
        protected_changes: Iterable[GenerationLaunchReceiptChange],
    ) -> GenerationLaunchGuardApproval | None:
        baseline_id = baseline.receipt_id or baseline.launch_fingerprint or baseline.path.name
        required_keys = tuple(sorted(item.key for item in protected_changes))
        for approval in self.list_guard_approvals(
            project_name=candidate.project_name,
            include_expired=False,
        ):
            if approval.launch_fingerprint != candidate.launch_fingerprint.casefold():
                continue
            if approval.baseline_receipt_id != baseline_id:
                continue
            if tuple(sorted(approval.protected_change_keys)) != required_keys:
                continue
            return approval
        return None

    def evaluate_guard(
        self,
        candidate: GenerationLaunchReceipt,
    ) -> GenerationLaunchGuardDecision:
        policy = self.guard_policy(candidate.project_name)
        if not policy.enabled:
            return GenerationLaunchGuardDecision(
                policy=policy,
                status="disabled",
                summary="Project baseline guard is disabled.",
            )
        baseline = self.baseline(candidate.project_name)
        if baseline is None:
            return GenerationLaunchGuardDecision(
                policy=policy,
                status="no_baseline",
                summary="No trusted project baseline is configured.",
            )
        comparison = self.compare(baseline, candidate)
        protected = tuple(
            item
            for item in comparison.changes
            if item.category in policy.protected_categories
        )
        critical = sum(item.severity == "critical" for item in protected)
        warnings = sum(item.severity == "warning" for item in protected)
        information = sum(item.severity == "info" for item in protected)
        if critical and policy.blocks_critical_drift:
            approval = self.matching_guard_approval(
                candidate,
                baseline=baseline,
                protected_changes=protected,
            )
            if approval is not None:
                return GenerationLaunchGuardDecision(
                    policy=policy,
                    status="approved_exception",
                    allowed=True,
                    requires_acknowledgement=True,
                    summary=(
                        f"One-time exception {approval.approval_id} authorizes "
                        f"{critical:,} critical protected launch change(s)."
                    ),
                    comparison=comparison,
                    protected_changes=protected,
                    approval=approval,
                )
            return GenerationLaunchGuardDecision(
                policy=policy,
                status="blocked",
                allowed=False,
                summary=(
                    f"Baseline guard blocked {critical:,} critical protected "
                    "launch change(s)."
                ),
                comparison=comparison,
                protected_changes=protected,
            )
        if critical or warnings:
            return GenerationLaunchGuardDecision(
                policy=policy,
                status="review_required",
                requires_acknowledgement=True,
                summary=(
                    f"Baseline guard detected {len(protected):,} protected change(s): "
                    f"{critical:,} critical and {warnings:,} warning."
                ),
                comparison=comparison,
                protected_changes=protected,
            )
        if information:
            return GenerationLaunchGuardDecision(
                policy=policy,
                status="informational_drift",
                summary=(
                    f"Baseline guard detected {information:,} informational "
                    "protected change(s)."
                ),
                comparison=comparison,
                protected_changes=protected,
            )
        return GenerationLaunchGuardDecision(
            policy=policy,
            status="matching",
            summary="Current launch matches the protected project baseline.",
            comparison=comparison,
        )

    def compare(
        self,
        baseline: GenerationLaunchReceipt,
        candidate: GenerationLaunchReceipt,
    ) -> GenerationLaunchReceiptComparison:
        """Compare two receipts and classify operational launch drift."""

        changes: list[GenerationLaunchReceiptChange] = []

        def add(
            key: str,
            label: str,
            category: str,
            before: object,
            after: object,
            severity: str,
            formatter=None,
        ) -> None:
            render = formatter or self._display_value
            before_text = render(before)
            after_text = render(after)
            if before_text == after_text:
                return
            changes.append(
                GenerationLaunchReceiptChange(
                    key=key,
                    label=label,
                    category=category,
                    baseline_value=before_text,
                    candidate_value=after_text,
                    severity=severity,
                )
            )

        add(
            "project_name",
            "Project",
            "Identity",
            baseline.project_name,
            candidate.project_name,
            "critical",
        )
        add("provider", "Provider", "Provider", baseline.provider, candidate.provider, "critical")
        add("model_id", "Model", "Provider", baseline.model_id, candidate.model_id, "warning")
        add("voice_id", "Voice", "Provider", baseline.voice_id, candidate.voice_id, "warning")
        add(
            "language_code",
            "Language",
            "Output format",
            baseline.language_code,
            candidate.language_code,
            "info",
        )
        add(
            "file_extension",
            "File extension",
            "Output format",
            baseline.file_extension,
            candidate.file_extension,
            "warning",
        )
        add(
            "output_directory",
            "Output directory",
            "Output policy",
            baseline.output_directory,
            candidate.output_directory,
            "critical",
        )
        add(
            "skip_existing",
            "Skip existing files",
            "Output policy",
            baseline.skip_existing,
            candidate.skip_existing,
            "warning",
            self._display_bool,
        )
        add(
            "overwrite_existing",
            "Overwrite existing files",
            "Output policy",
            baseline.overwrite_existing,
            candidate.overwrite_existing,
            "critical",
            self._display_bool,
        )
        add(
            "generation_scope",
            "Generation scope",
            "Execution",
            baseline.generation_scope,
            candidate.generation_scope,
            "warning",
        )
        add(
            "execution_order",
            "Execution order",
            "Execution",
            baseline.execution_order,
            candidate.execution_order,
            "info",
        )
        add(
            "max_retries",
            "Maximum retries",
            "Execution",
            baseline.max_retries,
            candidate.max_retries,
            "info",
            self._display_integer,
        )
        add(
            "delay_seconds",
            "Request delay",
            "Execution",
            baseline.delay_seconds,
            candidate.delay_seconds,
            "info",
            self._display_seconds,
        )
        for key, label, before, after in (
            ("files", "Planned files", baseline.files, candidate.files),
            ("characters", "Planned characters", baseline.characters, candidate.characters),
            (
                "provider_requests",
                "Provider requests",
                baseline.provider_requests,
                candidate.provider_requests,
            ),
            (
                "existing_outputs",
                "Existing outputs",
                baseline.existing_outputs,
                candidate.existing_outputs,
            ),
        ):
            add(key, label, "Scope", before, after, "warning", self._display_integer)
        add(
            "estimated_cost",
            "Estimated cost",
            "Risk and cost",
            (baseline.currency, baseline.estimated_cost),
            (candidate.currency, candidate.estimated_cost),
            "warning",
            self._display_cost,
        )
        add(
            "risk_level",
            "Planning risk",
            "Risk and cost",
            baseline.risk_level,
            candidate.risk_level,
            self._risk_change_severity(baseline.risk_level, candidate.risk_level),
        )
        add(
            "preflight_status",
            "Preflight status",
            "Review",
            baseline.preflight_status,
            candidate.preflight_status,
            "warning",
        )
        add(
            "review_status",
            "Review status",
            "Review",
            baseline.review_status,
            candidate.review_status,
            "info",
        )
        add(
            "required_acknowledgements",
            "Required acknowledgements",
            "Review",
            baseline.required_acknowledgements,
            candidate.required_acknowledgements,
            "warning",
            self._display_sequence,
        )
        add(
            "acknowledged_codes",
            "Acknowledged decisions",
            "Review",
            baseline.acknowledged_codes,
            candidate.acknowledged_codes,
            "info",
            self._display_sequence,
        )
        add(
            "guard_approval_id",
            "Guard exception approval",
            "Review",
            baseline.guard_approval_id,
            candidate.guard_approval_id,
            "info",
        )
        if baseline.integrity_status in {"mismatch", "unreadable"}:
            add(
                "baseline_integrity_status",
                "Baseline integrity",
                "Integrity",
                "trusted",
                baseline.integrity_status,
                "critical",
            )
        if candidate.integrity_status in {"mismatch", "unreadable"}:
            add(
                "candidate_integrity_status",
                "Candidate integrity",
                "Integrity",
                "trusted",
                candidate.integrity_status,
                "critical",
            )

        critical = sum(item.severity == "critical" for item in changes)
        warnings = sum(item.severity == "warning" for item in changes)
        if critical:
            status = "critical_drift"
            summary = (
                f"{len(changes):,} change(s) detected, including {critical:,} "
                "critical launch decision change(s)."
            )
        elif warnings:
            status = "drift"
            summary = (
                f"{len(changes):,} change(s) detected, including {warnings:,} "
                "operational warning(s)."
            )
        elif changes:
            status = "informational_drift"
            summary = f"{len(changes):,} informational launch change(s) detected."
        else:
            status = "matching"
            summary = "No launch configuration drift detected."
        return GenerationLaunchReceiptComparison(
            baseline=baseline,
            candidate=candidate,
            changes=tuple(changes),
            status=status,
            summary=summary,
        )

    @staticmethod
    def export_comparison(
        comparison: GenerationLaunchReceiptComparison,
        directory: Path,
    ) -> tuple[Path, Path]:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        safe_project = re.sub(
            r"[^A-Za-z0-9._-]+", "-", comparison.candidate.project_name
        ).strip("-") or "project"
        json_path = target / f"generation-launch-drift-{safe_project}-{stamp}.json"
        markdown_path = target / f"generation-launch-drift-{safe_project}-{stamp}.md"
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project_name": comparison.candidate.project_name,
            "status": comparison.status,
            "summary": comparison.summary,
            "baseline": GenerationLaunchReceiptService._comparison_identity(
                comparison.baseline
            ),
            "candidate": GenerationLaunchReceiptService._comparison_identity(
                comparison.candidate
            ),
            "metrics": {
                "changes": comparison.changed_count,
                "critical": comparison.critical_count,
                "warnings": comparison.warning_count,
                "information": comparison.information_count,
                "safe_to_reuse": comparison.safe_to_reuse,
            },
            "changes": [item.__dict__ for item in comparison.changes],
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = [
            "# S Talking Generation Launch Drift Report",
            "",
            f"- Created: {payload['created_at']}",
            f"- Project: {payload['project_name']}",
            f"- Status: {comparison.status}",
            f"- Baseline receipt: `{comparison.baseline.receipt_id or comparison.baseline.path.name}`",
            f"- Candidate receipt: `{comparison.candidate.receipt_id or comparison.candidate.path.name}`",
            f"- Safe to reuse: {'Yes' if comparison.safe_to_reuse else 'No'}",
            "",
            "## Summary",
            "",
            comparison.summary,
            "",
            "## Changes",
            "",
        ]
        if comparison.changes:
            lines.extend(
                f"- **{item.label}** ({item.severity}): "
                f"`{item.baseline_value}` → `{item.candidate_value}`"
                for item in comparison.changes
            )
        else:
            lines.append("- No launch configuration drift detected.")
        markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return json_path, markdown_path

    @property
    def _guard_approval_index_path(self) -> Path:
        return self.reports_dir / self.GUARD_APPROVAL_INDEX_NAME

    def _read_guard_approval_index(self) -> dict[str, object]:
        path = self._guard_approval_index_path
        if not path.exists():
            return {"schema_version": 1, "approvals": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"schema_version": 1, "approvals": []}
        if not isinstance(payload, dict):
            return {"schema_version": 1, "approvals": []}
        payload.setdefault("schema_version", 1)
        payload.setdefault("approvals", [])
        return payload

    def _write_guard_approval_index(self, payload: dict[str, object]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._guard_approval_index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._guard_approval_index_path)

    @staticmethod
    def _approval_from_record(record: dict[str, object]) -> GenerationLaunchGuardApproval:
        now = datetime.now(timezone.utc)
        status = str(record.get("status") or "approved").casefold()
        expires_at = str(record.get("expires_at") or "")
        used_count = GenerationLaunchReceiptService._integer(record.get("used_count"))
        max_uses = max(1, GenerationLaunchReceiptService._integer(record.get("max_uses"), 1))
        if status == "approved":
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    status = "expired"
            except (TypeError, ValueError):
                status = "expired"
            if used_count >= max_uses:
                status = "consumed"
        return GenerationLaunchGuardApproval(
            approval_id=str(record.get("approval_id") or ""),
            project_name=str(record.get("project_name") or ""),
            launch_fingerprint=str(record.get("launch_fingerprint") or "").casefold(),
            baseline_receipt_id=str(record.get("baseline_receipt_id") or ""),
            protected_change_keys=GenerationLaunchReceiptService._strings(
                record.get("protected_change_keys")
            ),
            reason=str(record.get("reason") or ""),
            approved_by=str(record.get("approved_by") or ""),
            created_at=str(record.get("created_at") or ""),
            expires_at=expires_at,
            max_uses=max_uses,
            used_count=used_count,
            status=status,
            revoked_at=str(record.get("revoked_at") or ""),
            last_used_at=str(record.get("last_used_at") or ""),
            renewed_from_id=str(record.get("renewed_from_id") or ""),
            audit_events=GenerationLaunchReceiptService._approval_events(
                record.get("audit_events")
            ),
        )

    @staticmethod
    def _append_approval_event(
        record: dict[str, object],
        *,
        action: str,
        occurred_at: str,
        actor: str = "",
        note: str = "",
        receipt_id: str = "",
    ) -> None:
        events = record.setdefault("audit_events", [])
        if not isinstance(events, list):
            events = []
            record["audit_events"] = events
        events.append(
            {
                "action": action,
                "occurred_at": occurred_at,
                "actor": actor,
                "note": note,
                "receipt_id": receipt_id,
            }
        )

    @staticmethod
    def _approval_events(value: object) -> tuple[GenerationLaunchGuardApprovalEvent, ...]:
        if not isinstance(value, list):
            return ()
        events: list[GenerationLaunchGuardApprovalEvent] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            events.append(
                GenerationLaunchGuardApprovalEvent(
                    action=str(item.get("action") or ""),
                    occurred_at=str(item.get("occurred_at") or ""),
                    actor=str(item.get("actor") or ""),
                    note=str(item.get("note") or ""),
                    receipt_id=str(item.get("receipt_id") or ""),
                )
            )
        return tuple(events)

    @staticmethod
    def _approval_search_text(approval: GenerationLaunchGuardApproval) -> str:
        return " ".join(
            (
                approval.approval_id,
                approval.project_name,
                approval.launch_fingerprint,
                approval.baseline_receipt_id,
                approval.reason,
                approval.approved_by,
                approval.status,
                approval.renewed_from_id,
                " ".join(approval.protected_change_keys),
            )
        ).casefold()

    @staticmethod
    def _approval_export_row(approval: GenerationLaunchGuardApproval) -> dict[str, object]:
        return {
            "approval_id": approval.approval_id,
            "project_name": approval.project_name,
            "status": approval.status,
            "approved_by": approval.approved_by,
            "reason": approval.reason,
            "created_at": approval.created_at,
            "expires_at": approval.expires_at,
            "revoked_at": approval.revoked_at,
            "last_used_at": approval.last_used_at,
            "max_uses": approval.max_uses,
            "used_count": approval.used_count,
            "remaining_uses": approval.remaining_uses,
            "baseline_receipt_id": approval.baseline_receipt_id,
            "launch_fingerprint": approval.launch_fingerprint,
            "protected_change_keys": ";".join(approval.protected_change_keys),
            "renewed_from_id": approval.renewed_from_id,
            "audit_event_count": len(approval.audit_events),
        }

    @property
    def _guard_profile_index_path(self) -> Path:
        return self.reports_dir / self.GUARD_PROFILE_INDEX_NAME

    def _read_guard_profile_index(self) -> dict[str, object]:
        path = self._guard_profile_index_path
        if not path.exists():
            return {"schema_version": 1, "default_profile_id": "balanced", "profiles": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"schema_version": 1, "default_profile_id": "balanced", "profiles": []}
        if not isinstance(payload, dict):
            return {"schema_version": 1, "default_profile_id": "balanced", "profiles": []}
        payload.setdefault("schema_version", 1)
        payload.setdefault("default_profile_id", "balanced")
        payload.setdefault("profiles", [])
        return payload

    def _write_guard_profile_index(self, payload: dict[str, object]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._guard_profile_index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._guard_profile_index_path)

    def _profile_from_record(
        self,
        record: dict[str, object],
        *,
        built_in: bool,
    ) -> GenerationLaunchGuardPolicyProfile:
        profile_id = str(record.get("profile_id") or "").strip().casefold()
        name = str(record.get("name") or "").strip()
        mode = str(record.get("mode") or "warn").strip().casefold()
        categories = tuple(
            item
            for item in self._strings(record.get("protected_categories"))
            if item in self.GUARD_CATEGORIES
        )
        if not profile_id or not name:
            raise ValueError("Guard policy profile requires an ID and name.")
        if mode not in self.GUARD_MODES:
            raise ValueError("Guard policy profile mode is invalid.")
        if mode != "off" and not categories:
            raise ValueError("Guard policy profile requires protected categories.")
        return GenerationLaunchGuardPolicyProfile(
            profile_id=profile_id,
            name=name,
            description=str(record.get("description") or "").strip(),
            mode=mode,
            protected_categories=categories,
            built_in=built_in,
            created_at=str(record.get("created_at") or ""),
            updated_at=str(record.get("updated_at") or ""),
        )

    @property
    def _guard_policy_index_path(self) -> Path:
        return self.reports_dir / self.GUARD_POLICY_INDEX_NAME

    def _read_guard_policy_index(self) -> dict[str, object]:
        path = self._guard_policy_index_path
        if not path.exists():
            return {"schema_version": 1, "projects": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"schema_version": 1, "projects": {}}
        if not isinstance(payload, dict):
            return {"schema_version": 1, "projects": {}}
        payload.setdefault("schema_version", 1)
        payload.setdefault("projects", {})
        return payload

    def _write_guard_policy_index(self, payload: dict[str, object]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._guard_policy_index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._guard_policy_index_path)

    @property
    def _baseline_index_path(self) -> Path:
        return self.reports_dir / self.BASELINE_INDEX_NAME

    def _read_baseline_index(self) -> dict[str, object]:
        path = self._baseline_index_path
        if not path.exists():
            return {"schema_version": 1, "projects": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Baseline index root must be an object.")
            if not isinstance(payload.get("projects"), dict):
                payload["projects"] = {}
            return payload
        except (OSError, ValueError, json.JSONDecodeError):
            return {"schema_version": 1, "projects": {}}

    def _write_baseline_index(self, payload: dict[str, object]) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._baseline_index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self._baseline_index_path)

    def _stored_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.reports_dir.resolve()))
        except (OSError, ValueError):
            return str(path)

    @staticmethod
    def _project_key(value: str) -> str:
        return str(value or "unknown").strip().casefold()

    @staticmethod
    def _comparison_identity(receipt: GenerationLaunchReceipt) -> dict[str, object]:
        return {
            "receipt_id": receipt.receipt_id,
            "created_at": receipt.created_at,
            "project_name": receipt.project_name,
            "launch_fingerprint": receipt.launch_fingerprint,
            "integrity_status": receipt.integrity_status,
            "receipt_path": str(receipt.path),
            "guard_policy_profile_id": receipt.guard_policy_profile_id,
            "guard_policy_version": receipt.guard_policy_version,
            "guard_policy_locked": receipt.guard_policy_locked,
        }

    @staticmethod
    def _display_value(value: object) -> str:
        text = str(value or "").strip()
        return text or "Default"

    @staticmethod
    def _display_bool(value: object) -> str:
        return "Yes" if bool(value) else "No"

    @staticmethod
    def _display_integer(value: object) -> str:
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "0"

    @staticmethod
    def _display_seconds(value: object) -> str:
        try:
            return f"{float(value):,.2f} s"
        except (TypeError, ValueError):
            return "0.00 s"

    @staticmethod
    def _display_cost(value: object) -> str:
        if isinstance(value, tuple) and len(value) == 2:
            currency, amount = value
            try:
                return f"{str(currency or 'USD').upper()} {float(amount):,.4f}"
            except (TypeError, ValueError):
                return "USD 0.0000"
        return "USD 0.0000"

    @staticmethod
    def _display_sequence(value: object) -> str:
        if not isinstance(value, (tuple, list)):
            return "None"
        items = sorted(str(item) for item in value if str(item).strip())
        return ", ".join(items) or "None"

    @staticmethod
    def _risk_change_severity(before: str, after: str) -> str:
        rank = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
        before_rank = rank.get(str(before).casefold(), 0)
        after_rank = rank.get(str(after).casefold(), 0)
        if after_rank >= 3 and after_rank > before_rank:
            return "critical"
        if after_rank > before_rank:
            return "warning"
        return "info"

    def _receipt_paths(self) -> list[Path]:
        if not self.reports_dir.exists():
            return []
        return [path for path in self.reports_dir.rglob(self.RECEIPT_NAME) if path.is_file()]

    @staticmethod
    def _search_text(receipt: GenerationLaunchReceipt) -> str:
        return " ".join(
            (
                receipt.receipt_id,
                receipt.project_name,
                receipt.launch_fingerprint,
                receipt.provider,
                receipt.model_id,
                receipt.voice_id,
                receipt.language_code,
                receipt.file_extension,
                receipt.generation_scope,
                receipt.execution_order,
                receipt.output_directory,
                receipt.preflight_status,
                receipt.review_status,
                receipt.risk_level,
                receipt.integrity_status,
                receipt.guard_approval_id,
                receipt.guard_policy_profile_id,
                str(receipt.guard_policy_version),
                receipt.decision_status,
                receipt.decision_trace_id,
                receipt.decision_summary,
                receipt.run_id,
                receipt.execution_session_path,
            )
        ).casefold()

    @staticmethod
    def _unreadable(path: Path, markdown_path: Path, message: str) -> GenerationLaunchReceipt:
        try:
            project_name = path.parents[2].name
        except IndexError:
            project_name = "unknown"
        return GenerationLaunchReceipt(
            path=path,
            markdown_path=markdown_path,
            created_at=GenerationLaunchReceiptService._mtime(path),
            project_name=project_name,
            integrity_status="unreadable",
            integrity_message=f"Receipt could not be read: {message}",
        )

    @staticmethod
    def _export_row(receipt: GenerationLaunchReceipt) -> dict[str, object]:
        return {
            "receipt_id": receipt.receipt_id,
            "created_at": receipt.created_at,
            "project_name": receipt.project_name,
            "launch_fingerprint": receipt.launch_fingerprint,
            "preflight_status": receipt.preflight_status,
            "review_status": receipt.review_status,
            "provider": receipt.provider,
            "model_id": receipt.model_id,
            "voice_id": receipt.voice_id,
            "language_code": receipt.language_code,
            "file_extension": receipt.file_extension,
            "max_retries": receipt.max_retries,
            "delay_seconds": receipt.delay_seconds,
            "skip_existing": receipt.skip_existing,
            "overwrite_existing": receipt.overwrite_existing,
            "generation_scope": receipt.generation_scope,
            "execution_order": receipt.execution_order,
            "files": receipt.files,
            "characters": receipt.characters,
            "provider_requests": receipt.provider_requests,
            "existing_outputs": receipt.existing_outputs,
            "risk_level": receipt.risk_level,
            "estimated_cost": receipt.estimated_cost,
            "estimated_duration_seconds": receipt.estimated_duration_seconds,
            "currency": receipt.currency,
            "acknowledged_codes": ";".join(receipt.acknowledged_codes),
            "required_acknowledgements": ";".join(receipt.required_acknowledgements),
            "integrity_status": receipt.integrity_status,
            "integrity_message": receipt.integrity_message,
            "guard_approval_id": receipt.guard_approval_id,
            "guard_policy_profile_id": receipt.guard_policy_profile_id,
            "guard_policy_version": receipt.guard_policy_version,
            "guard_policy_locked": receipt.guard_policy_locked,
            "decision_status": receipt.decision_status,
            "decision_trace_id": receipt.decision_trace_id,
            "decision_summary": receipt.decision_summary,
            "run_id": receipt.run_id,
            "execution_session_path": receipt.execution_session_path,
            "receipt_path": str(receipt.path),
            "markdown_path": str(receipt.markdown_path),
            "output_directory": receipt.output_directory,
        }

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(item) for item in value if str(item).strip())

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _boolean(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _mtime(path: Path) -> str:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        except OSError:
            return ""
