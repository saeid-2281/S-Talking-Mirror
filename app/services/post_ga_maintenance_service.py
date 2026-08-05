from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.post_ga_maintenance import (
    PostGaMaintenanceArtifact,
    PostGaMaintenanceGate,
    PostGaMaintenanceSnapshot,
)
from app.services.stable_release_promotion_service import StableReleasePromotionService


class PostGaMaintenanceService:
    """Verify and record the post-GA maintenance baseline.

    The service is intentionally non-destructive. It never deletes artifacts,
    modifies an update feed, publishes a release, installs an update, restarts
    the application, or changes Git state. It verifies the stable promotion
    chain and writes privacy-safe, tamper-evident evidence for a separate
    human-controlled maintenance window.
    """

    SCHEMA_VERSION = 1
    BASELINE_NAME = "post-ga-maintenance-baseline.json"
    PLAN_NAME = "post-ga-maintenance-plan.json"
    _STABLE_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    _SECRET_KEY_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|cookie|private[_-]?key)"
    )
    _TOKEN_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{12,}\b")

    def __init__(
        self,
        runtime: RuntimeConfig,
        stable_service: StableReleasePromotionService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
        disk_usage: Callable[[str | os.PathLike[str]], Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.stable_service = stable_service or StableReleasePromotionService(runtime)
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "post-ga-maintenance"
        self.baseline_root = self.root / "baselines"
        self.plan_root = self.root / "plans"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._disk_usage = disk_usage or shutil.disk_usage
        self.root.mkdir(parents=True, exist_ok=True)
        self.baseline_root.mkdir(parents=True, exist_ok=True)
        self.plan_root.mkdir(parents=True, exist_ok=True)

    def default_promotion_receipt_path(self) -> Path:
        return (
            self.runtime.artifacts_dir
            / "stable-promotion"
            / StableReleasePromotionService.RECEIPT_NAME
        )

    def default_stable_feed_path(self) -> Path:
        return self.runtime.artifacts_dir / "update-channel" / "stable" / "latest.json"

    def default_baseline_path(self) -> Path:
        return self.root / self.BASELINE_NAME

    def snapshot(
        self,
        *,
        promotion_receipt_path: Path | None = None,
        stable_feed_path: Path | None = None,
        rollback_manifest_path: Path | None = None,
        max_evidence_age_days: int = 30,
        minimum_free_space_mb: int = 512,
        expected_rollout_percentage: int = 100,
    ) -> PostGaMaintenanceSnapshot:
        receipt = Path(promotion_receipt_path or self.default_promotion_receipt_path())
        feed = Path(stable_feed_path or self.default_stable_feed_path())
        max_age = max(1, int(max_evidence_age_days))
        minimum_free_bytes = max(1, int(minimum_free_space_mb)) * 1024 * 1024
        expected_rollout = max(1, min(100, int(expected_rollout_percentage)))

        gates: list[PostGaMaintenanceGate] = []
        artifacts: list[PostGaMaintenanceArtifact] = []

        identity_ok = bool(self._STABLE_VERSION_RE.fullmatch(self.version)) and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Installed stable identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Application identity is {self.version}/{self.channel}."
                    if identity_ok
                    else f"Post-GA maintenance requires stable X.Y.Z/stable, not {self.version}/{self.channel}."
                ),
                "Use a verified stable installation before recording a maintenance baseline.",
            )
        )

        receipt_ok, receipt_detail = self.stable_service.verify_promotion_receipt(receipt)
        receipt_payload = self._read_json(receipt) or {}
        gates.append(
            self._gate(
                "promotion_receipt",
                "Stable promotion receipt",
                "pass" if receipt_ok else "block",
                "blocker",
                receipt_detail,
                "Restore or regenerate the verified stable promotion receipt and referenced artifacts.",
            )
        )
        if receipt_ok:
            artifacts.append(self._artifact("stable_promotion_receipt", receipt))

        evidence_age = self._evidence_age_days(receipt_payload.get("created_at"))
        if evidence_age < 0:
            age_status = "block"
            age_detail = "Stable promotion receipt timestamp is missing or invalid."
        elif evidence_age > max_age * 3:
            age_status = "block"
            age_detail = (
                f"Stable release evidence is {evidence_age} day(s) old, exceeding the "
                f"{max_age * 3}-day hard limit."
            )
        elif evidence_age > max_age:
            age_status = "warn"
            age_detail = (
                f"Stable release evidence is {evidence_age} day(s) old; refresh operational "
                f"evidence after {max_age} days."
            )
        else:
            age_status = "pass"
            age_detail = f"Stable release evidence is {evidence_age} day(s) old."
        gates.append(
            self._gate(
                "evidence_freshness",
                "Post-GA evidence freshness",
                age_status,
                "blocker" if age_status == "block" else "warning",
                age_detail,
                "Run the post-GA evidence refresh and record a new maintenance baseline.",
            )
        )

        feed_ok, feed_detail, rollout = self._verify_stable_feed(feed)
        gates.append(
            self._gate(
                "stable_update_feed",
                "Stable update feed integrity",
                "pass" if feed_ok else "block",
                "blocker",
                feed_detail,
                "Restore the stable feed, digest and downloadable artifacts from verified release evidence.",
            )
        )
        if feed_ok:
            artifacts.append(self._artifact("stable_update_feed", feed))

        if feed_ok and rollout == expected_rollout:
            rollout_status = "pass"
            rollout_detail = f"Stable rollout is complete at {rollout}%."
        elif feed_ok and 1 <= rollout < expected_rollout:
            rollout_status = "warn"
            rollout_detail = (
                f"Stable rollout is {rollout}%; the post-GA target is {expected_rollout}%."
            )
        else:
            rollout_status = "block"
            rollout_detail = "Stable rollout percentage is unavailable or invalid."
        gates.append(
            self._gate(
                "stable_rollout",
                "Stable rollout completion",
                rollout_status,
                "blocker" if rollout_status == "block" else "warning",
                rollout_detail,
                "Complete or explicitly review the stable rollout before routine maintenance.",
            )
        )

        rollback = Path(rollback_manifest_path) if rollback_manifest_path else self._receipt_artifact_path(
            receipt_payload, "rollback_manifest"
        )
        rollback_ok = False
        rollback_detail = "Stable rollback manifest is not referenced by the promotion receipt."
        if rollback is not None:
            rollback_ok, rollback_detail = self.stable_service.verify_rollback_manifest(rollback)
        gates.append(
            self._gate(
                "rollback_manifest",
                "Verified rollback point",
                "pass" if rollback_ok else "block",
                "blocker",
                rollback_detail,
                "Restore and verify the stable rollback point before maintenance operations.",
            )
        )
        if rollback_ok and rollback is not None:
            artifacts.append(self._artifact("stable_rollback_manifest", rollback))

        writable_paths = (
            self.runtime.data_dir,
            self.runtime.log_dir,
            self.runtime.cache_dir,
            self.runtime.default_output_dir,
            self.runtime.reports_dir,
            self.runtime.artifacts_dir,
            self.runtime.settings_path.parent,
        )
        unavailable = [path.name or str(path) for path in writable_paths if not self._writable_directory(path)]
        gates.append(
            self._gate(
                "writable_runtime",
                "Writable runtime directories",
                "pass" if not unavailable else "block",
                "blocker",
                (
                    "All runtime data, log, cache, output, report, artifact and settings directories are writable."
                    if not unavailable
                    else "Runtime directories are unavailable or read-only: " + ", ".join(unavailable)
                ),
                "Repair directory permissions or choose a writable portable-data location.",
            )
        )

        free_bytes = self._free_space_bytes()
        if free_bytes < minimum_free_bytes:
            disk_status = "block"
            disk_detail = (
                f"Only {self._format_bytes(free_bytes)} is free; at least "
                f"{self._format_bytes(minimum_free_bytes)} is required."
            )
        elif free_bytes < minimum_free_bytes * 2:
            disk_status = "warn"
            disk_detail = (
                f"Free space is {self._format_bytes(free_bytes)}, below the recommended "
                f"{self._format_bytes(minimum_free_bytes * 2)} reserve."
            )
        else:
            disk_status = "pass"
            disk_detail = f"Free space reserve is {self._format_bytes(free_bytes)}."
        gates.append(
            self._gate(
                "free_space",
                "Maintenance free-space reserve",
                disk_status,
                "blocker" if disk_status == "block" else "warning",
                disk_detail,
                "Free disk space before backups, diagnostics or release evidence refresh.",
            )
        )

        evidence_payloads = [payload for payload in (receipt_payload, self._read_json(feed)) if payload]
        privacy_ok = not any(self._contains_secret(payload) for payload in evidence_payloads)
        local_path_exposed = any(
            str(self.runtime.app_root) in json.dumps(payload, ensure_ascii=False)
            or str(self.runtime.settings_path.parent) in json.dumps(payload, ensure_ascii=False)
            for payload in evidence_payloads
        )
        privacy_ok = privacy_ok and not local_path_exposed
        gates.append(
            self._gate(
                "privacy_contract",
                "Privacy-safe maintenance evidence",
                "pass" if privacy_ok else "block",
                "blocker",
                (
                    "Stable evidence contains no credential-like fields, tokens or absolute local paths."
                    if privacy_ok
                    else "Stable evidence contains credential-like data or an absolute local path."
                ),
                "Remove private data and regenerate the affected evidence artifact.",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            summary = f"Post-GA maintenance is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_warnings"
            summary = f"Post-GA maintenance is ready with {warning_count} warning(s)."
        else:
            status = "ready"
            summary = "Post-GA maintenance baseline is ready."

        return PostGaMaintenanceSnapshot(
            baseline_id=f"post-ga-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            status=status,
            summary=summary,
            maintenance_allowed=blocker_count == 0,
            evidence_age_days=evidence_age,
            rollout_percentage=rollout,
            free_space_bytes=free_bytes,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )

    def write_baseline(
        self,
        snapshot: PostGaMaintenanceSnapshot,
        *,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        if snapshot.blocker_count:
            return {
                "status": "blocked",
                "detail": snapshot.summary,
                "path": "",
            }
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review and acknowledge the post-GA gates before writing the baseline.",
                "path": "",
            }

        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "baseline_id": snapshot.baseline_id,
            "created_at": self._now_iso(),
            "version": snapshot.version,
            "channel": snapshot.channel,
            "status": snapshot.status,
            "warning_count": snapshot.warning_count,
            "evidence_age_days": snapshot.evidence_age_days,
            "rollout_percentage": snapshot.rollout_percentage,
            "free_space_bytes": snapshot.free_space_bytes,
            "manual_maintenance_required": True,
            "automatic_cleanup": False,
            "automatic_publish": False,
            "automatic_update": False,
            "automatic_restart": False,
            "gates": [gate.to_dict() for gate in snapshot.gates],
            "artifacts": [self._artifact_record(artifact) for artifact in snapshot.artifacts],
            "private_data_included": False,
        }
        payload["baseline_sha256"] = self._payload_digest(payload)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        path = self.baseline_root / f"post-ga-maintenance-baseline-{stamp}.json"
        self._write_json(path, payload)
        ok, detail = self.verify_baseline(path)
        if not ok:
            path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        self._write_json(self.default_baseline_path(), payload)
        return {"status": "verified", "detail": detail, "path": str(path)}

    def verify_baseline(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Post-GA maintenance baseline is unreadable."
        expected = str(payload.get("baseline_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("baseline_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Post-GA maintenance baseline SHA-256 does not match."
        if str(payload.get("version") or "") != self.version or str(payload.get("channel") or "") != "stable":
            return False, "Post-GA maintenance baseline identity does not match the application."
        if (
            payload.get("automatic_cleanup") is not False
            or payload.get("automatic_publish") is not False
            or payload.get("automatic_update") is not False
            or payload.get("automatic_restart") is not False
        ):
            return False, "Post-GA maintenance baseline violates the manual-operation contract."
        if payload.get("private_data_included") is not False or self._contains_secret(payload):
            return False, "Post-GA maintenance baseline violates the privacy contract."
        records = payload.get("artifacts")
        if not isinstance(records, list) or len(records) < 3:
            return False, "Post-GA maintenance baseline is missing required evidence artifacts."
        for item in records:
            ok, detail = self._verify_artifact_record(item)
            if not ok:
                return False, detail
        return True, f"Post-GA maintenance baseline verified with {len(records)} artifact(s)."

    def prepare_maintenance_plan(
        self,
        snapshot: PostGaMaintenanceSnapshot,
        *,
        baseline_path: Path,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.summary, "path": ""}
        baseline_ok, baseline_detail = self.verify_baseline(Path(baseline_path))
        if not baseline_ok:
            return {"status": "blocked", "detail": baseline_detail, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Acknowledge the verified baseline before preparing a maintenance plan.",
                "path": "",
            }

        baseline_record = self._path_record(Path(baseline_path))
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": f"maintenance-{uuid.uuid4().hex[:12]}",
            "created_at": self._now_iso(),
            "version": snapshot.version,
            "channel": snapshot.channel,
            "baseline": baseline_record,
            "actions": [
                {
                    "order": 1,
                    "code": "backup_verify",
                    "label": "Verify database and configuration backups",
                    "automatic": False,
                },
                {
                    "order": 2,
                    "code": "diagnostics_refresh",
                    "label": "Refresh crash, performance and security evidence",
                    "automatic": False,
                },
                {
                    "order": 3,
                    "code": "quality_gate",
                    "label": "Run the full quality gate before maintenance publication",
                    "automatic": False,
                },
                {
                    "order": 4,
                    "code": "retention_preview",
                    "label": "Review retention candidates without deleting artifacts",
                    "automatic": False,
                },
                {
                    "order": 5,
                    "code": "post_check",
                    "label": "Record a fresh post-maintenance baseline",
                    "automatic": False,
                },
            ],
            "automatic_cleanup": False,
            "automatic_publish": False,
            "automatic_update": False,
            "automatic_restart": False,
            "private_data_included": False,
        }
        payload["plan_sha256"] = self._payload_digest(payload)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        path = self.plan_root / f"post-ga-maintenance-plan-{stamp}.json"
        self._write_json(path, payload)
        ok, detail = self.verify_maintenance_plan(path)
        if not ok:
            path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        self._write_json(self.root / self.PLAN_NAME, payload)
        return {"status": "prepared", "detail": detail, "path": str(path)}

    def verify_maintenance_plan(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Post-GA maintenance plan is unreadable."
        expected = str(payload.get("plan_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("plan_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Post-GA maintenance plan SHA-256 does not match."
        if str(payload.get("version") or "") != self.version or str(payload.get("channel") or "") != "stable":
            return False, "Post-GA maintenance plan identity does not match the application."
        if any(payload.get(name) is not False for name in (
            "automatic_cleanup",
            "automatic_publish",
            "automatic_update",
            "automatic_restart",
        )):
            return False, "Post-GA maintenance plan violates the manual-operation contract."
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) < 5:
            return False, "Post-GA maintenance plan is missing required actions."
        if any(not isinstance(item, Mapping) or item.get("automatic") is not False for item in actions):
            return False, "Post-GA maintenance plan contains an automatic action."
        baseline = payload.get("baseline")
        ok, detail = self._verify_artifact_record(baseline)
        if not ok:
            return False, detail
        return True, f"Post-GA maintenance plan verified with {len(actions)} manual action(s)."

    def export_snapshot(self, snapshot: PostGaMaintenanceSnapshot) -> Path:
        path = self.root / "post-ga-maintenance-summary.json"
        payload = snapshot.to_dict()
        payload["private_data_included"] = False
        payload["automatic_cleanup"] = False
        payload["automatic_update"] = False
        self._write_json(path, payload)
        return path

    def _verify_stable_feed(self, path: Path) -> tuple[bool, str, int]:
        payload = self._read_json(path)
        if not isinstance(payload, dict):
            return False, "Stable update feed is missing or unreadable.", 0
        try:
            rollout = int(payload.get("rollout_percentage") or 0)
        except (TypeError, ValueError):
            rollout = 0
        if str(payload.get("product") or "") != "S Talking":
            return False, "Stable update feed product identity is invalid.", rollout
        if str(payload.get("channel") or "") != "stable" or str(payload.get("version") or "") != self.version:
            return False, "Stable update feed version or channel is invalid.", rollout
        if not 1 <= rollout <= 100:
            return False, "Stable update feed rollout percentage is invalid.", rollout
        records = payload.get("artifacts")
        if not isinstance(records, list) or not records:
            return False, "Stable update feed contains no downloadable artifacts.", rollout
        for item in records:
            if not isinstance(item, Mapping):
                return False, "Stable update feed contains an invalid artifact record.", rollout
            filename = str(item.get("filename") or "")
            if not self._safe_filename(filename) or str(item.get("url") or "") != filename:
                return False, "Stable update feed contains an unsafe artifact URL.", rollout
            artifact = path.parent / filename
            if not artifact.exists() or not artifact.is_file():
                return False, f"Stable update artifact is missing: {filename}", rollout
            if artifact.stat().st_size != int(item.get("size_bytes") or -1):
                return False, f"Stable update artifact size mismatch: {filename}", rollout
            if self._sha256(artifact) != str(item.get("sha256") or ""):
                return False, f"Stable update artifact SHA-256 mismatch: {filename}", rollout
        digest = path.with_suffix(".sha256")
        if not digest.exists() or not digest.is_file():
            return False, "Stable update feed digest is missing.", rollout
        try:
            expected = digest.read_text(encoding="ascii").split()[0].casefold()
        except (OSError, IndexError):
            return False, "Stable update feed digest is unreadable.", rollout
        if expected != self._sha256(path):
            return False, "Stable update feed digest does not match.", rollout
        return True, f"Stable update feed verified with {len(records)} artifact(s).", rollout

    def _receipt_artifact_path(self, payload: Mapping[str, Any], role: str) -> Path | None:
        records = payload.get("artifacts")
        if not isinstance(records, list):
            return None
        for item in records:
            if not isinstance(item, Mapping) or str(item.get("role") or "") != role:
                continue
            raw_path = str(item.get("path") or "")
            pure = Path(raw_path)
            if pure.is_absolute() or ".." in pure.parts:
                return None
            candidate = (self.runtime.app_root / pure).resolve()
            try:
                candidate.relative_to(self.runtime.app_root.resolve())
            except ValueError:
                return None
            return candidate
        return None

    def _artifact(self, role: str, path: Path) -> PostGaMaintenanceArtifact:
        return PostGaMaintenanceArtifact(
            role=role,
            path=Path(path),
            size_bytes=path.stat().st_size,
            sha256=self._sha256(path),
            captured_at=self._timestamp(path),
        )

    def _artifact_record(self, artifact: PostGaMaintenanceArtifact) -> dict[str, object]:
        record = self._path_record(artifact.path)
        record["role"] = artifact.role
        record["captured_at"] = artifact.captured_at
        return record

    def _path_record(self, path: Path) -> dict[str, object]:
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(self.runtime.app_root.resolve())
        except ValueError as exc:
            raise ValueError("Maintenance evidence must remain under the application root.") from exc
        if ".." in relative.parts:
            raise ValueError("Maintenance evidence path is unsafe.")
        return {
            "path": relative.as_posix(),
            "size_bytes": resolved.stat().st_size,
            "sha256": self._sha256(resolved),
        }

    def _verify_artifact_record(self, item: object) -> tuple[bool, str]:
        if not isinstance(item, Mapping):
            return False, "Post-GA evidence contains an invalid artifact record."
        raw_path = str(item.get("path") or "")
        pure = Path(raw_path)
        if pure.is_absolute() or ".." in pure.parts:
            return False, "Post-GA evidence contains an unsafe artifact path."
        artifact = (self.runtime.app_root / pure).resolve()
        try:
            artifact.relative_to(self.runtime.app_root.resolve())
        except ValueError:
            return False, "Post-GA evidence artifact escapes the application root."
        if not artifact.exists() or not artifact.is_file():
            return False, f"Post-GA evidence artifact is missing: {artifact.name or raw_path}"
        if artifact.stat().st_size != int(item.get("size_bytes") or -1):
            return False, f"Post-GA evidence artifact size mismatch: {artifact.name}"
        if self._sha256(artifact) != str(item.get("sha256") or ""):
            return False, f"Post-GA evidence artifact SHA-256 mismatch: {artifact.name}"
        return True, f"Post-GA evidence artifact verified: {artifact.name}"

    def _writable_directory(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return path.is_dir() and os.access(path, os.W_OK)

    def _free_space_bytes(self) -> int:
        try:
            return int(self._disk_usage(self.runtime.artifacts_dir).free)
        except (OSError, ValueError):
            return 0

    def _evidence_age_days(self, value: object) -> int:
        try:
            observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return -1
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        delta = self._now() - observed.astimezone(timezone.utc)
        if delta.total_seconds() < -300:
            return -1
        return max(0, delta.days)

    def _contains_secret(self, value: object) -> bool:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if self._SECRET_KEY_RE.search(str(key)):
                    return True
                if self._contains_secret(child):
                    return True
            return False
        if isinstance(value, (list, tuple, set)):
            return any(self._contains_secret(item) for item in value)
        return isinstance(value, str) and bool(self._TOKEN_RE.search(value))

    @staticmethod
    def _safe_filename(value: str) -> bool:
        path = Path(value)
        return bool(value) and not path.is_absolute() and len(path.parts) == 1 and ".." not in path.parts

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> PostGaMaintenanceGate:
        return PostGaMaintenanceGate(code, label, status, severity, detail, remediation)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _timestamp(path: Path) -> str:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    @staticmethod
    def _format_bytes(value: int) -> str:
        number = float(max(0, value))
        for suffix in ("B", "KB", "MB", "GB", "TB"):
            if number < 1024 or suffix == "TB":
                return f"{number:.1f} {suffix}" if suffix != "B" else f"{int(number)} B"
            number /= 1024
        return f"{int(value)} B"

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
