from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.incident_support import (
    IncidentSupportArtifact,
    IncidentSupportBundle,
    IncidentSupportGate,
    IncidentSupportSnapshot,
)
from app.services.crash_recovery_service import CrashRecoveryService
from app.services.post_ga_maintenance_service import PostGaMaintenanceService


class IncidentSupportService:
    """Prepare privacy-safe, integrity-verifiable production support bundles.

    The service never uploads, sends, publishes, installs, restarts, deletes or
    modifies operational evidence. Databases, settings, API profiles, credential
    stores, generated audio and project sources are excluded by design.
    """

    SCHEMA_VERSION = 1
    MAX_REPORTS = 10
    MAX_LOG_FILES = 8
    MAX_LOG_BYTES = 192_000
    MIN_SUMMARY_CHARS = 12
    MAX_SUMMARY_CHARS = 600
    _STABLE_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    _SECRET_KEY_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|cookie|private[_-]?key)"
    )
    _TOKEN_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{12,}\b")
    _AUTHORIZATION_RE = re.compile(
        r"(?i)\bauthorization\b\s*[:=]\s*"
        r"(?:(?:bearer|basic|token)\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    )
    _SECRET_ASSIGNMENT_RE = re.compile(
        r"(?i)[\"']?\b(api[_-]?key|authorization|token|secret|password|passwd|cookie|credential)\b[\"']?"
        r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    )
    _BEARER_RE = re.compile(r"(?i)\bbearer\s+(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)")
    _URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")
    _WINDOWS_USER_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/](?:Users|Documents and Settings)[\\/][^\\/\s]+")
    _POSIX_HOME_RE = re.compile(r"/(?:home|Users)/[^/\s]+")
    _FORBIDDEN_NAME_RE = re.compile(
        r"(?i)(api-profiles|workspace-profiles|settings(?:\.|$)|credential|secret|database|\.sqlite|\.db$|\.mp3$|\.wav$|\.flac$)"
    )
    _SEVERITIES = {"low", "medium", "high", "critical"}

    def __init__(
        self,
        runtime: RuntimeConfig,
        crash_service: CrashRecoveryService | None = None,
        post_ga_service: PostGaMaintenanceService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
        disk_usage: Callable[[str | os.PathLike[str]], Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.crash_service = crash_service or CrashRecoveryService(runtime)
        self.post_ga_service = post_ga_service or PostGaMaintenanceService(runtime)
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "incident-support"
        self.bundles_dir = self.root / "bundles"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._disk_usage = disk_usage or shutil.disk_usage
        self.root.mkdir(parents=True, exist_ok=True)
        self.bundles_dir.mkdir(parents=True, exist_ok=True)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

    def default_baseline_path(self) -> Path:
        return self.post_ga_service.default_baseline_path()

    def snapshot(
        self,
        *,
        summary: str,
        severity: str = "medium",
        baseline_path: Path | None = None,
        include_logs: bool = True,
        max_log_age_days: int = 14,
        max_bundle_mb: int = 16,
    ) -> IncidentSupportSnapshot:
        raw_summary = str(summary or "").strip()
        safe_summary = self._sanitize_text(raw_summary)[: self.MAX_SUMMARY_CHARS]
        normalized_severity = str(severity or "medium").strip().casefold()
        baseline = Path(baseline_path or self.default_baseline_path())
        max_age = max(1, min(365, int(max_log_age_days)))
        max_bundle_bytes = max(1, min(128, int(max_bundle_mb))) * 1024 * 1024
        generated_at = self._now_iso()
        incident_id = self._incident_id(generated_at)

        gates: list[IncidentSupportGate] = []
        artifacts: list[IncidentSupportArtifact] = []

        summary_has_secret = self._contains_secret_text(raw_summary)
        summary_valid = (
            self.MIN_SUMMARY_CHARS <= len(raw_summary) <= self.MAX_SUMMARY_CHARS
            and not summary_has_secret
        )
        if summary_has_secret:
            summary_detail = "Incident summary contains a credential-like value or secret assignment."
        elif len(raw_summary) < self.MIN_SUMMARY_CHARS:
            summary_detail = (
                f"Incident summary requires at least {self.MIN_SUMMARY_CHARS} characters."
            )
        elif len(raw_summary) > self.MAX_SUMMARY_CHARS:
            summary_detail = (
                f"Incident summary exceeds the {self.MAX_SUMMARY_CHARS}-character limit."
            )
        else:
            summary_detail = "Incident summary is concise and privacy-safe."
        gates.append(
            self._gate(
                "incident_summary",
                "Incident summary",
                "pass" if summary_valid else "block",
                "blocker",
                summary_detail,
                "Remove credentials and provide a concise symptom, impact and reproduction summary.",
            )
        )

        severity_valid = normalized_severity in self._SEVERITIES
        gates.append(
            self._gate(
                "incident_severity",
                "Incident severity",
                "pass" if severity_valid else "block",
                "blocker",
                (
                    f"Incident severity is {normalized_severity}."
                    if severity_valid
                    else "Incident severity must be low, medium, high or critical."
                ),
                "Select one supported operational severity.",
            )
        )

        identity_ok = bool(self._STABLE_VERSION_RE.fullmatch(self.version)) and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Stable production identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Application identity is {self.version}/{self.channel}."
                    if identity_ok
                    else f"Production support requires stable X.Y.Z/stable, not {self.version}/{self.channel}."
                ),
                "Use a verified stable installation before preparing a production support bundle.",
            )
        )

        baseline_ok, baseline_detail = self.post_ga_service.verify_baseline(baseline)
        gates.append(
            self._gate(
                "post_ga_baseline",
                "Post-GA maintenance baseline",
                "pass" if baseline_ok else "block",
                "blocker",
                baseline_detail,
                "Create and verify a fresh Phase 62 post-GA maintenance baseline.",
            )
        )
        if baseline_ok:
            artifacts.append(self._artifact("post_ga_baseline", baseline))

        crash_snapshot = self.crash_service.snapshot()
        if crash_snapshot.integrity_failure_count:
            crash_status = "block"
            crash_detail = (
                f"{crash_snapshot.integrity_failure_count} crash report(s) failed integrity verification."
            )
        elif crash_snapshot.unacknowledged_count:
            crash_status = "warn"
            crash_detail = (
                f"{crash_snapshot.unacknowledged_count} unreviewed crash report(s) will be included when verified."
            )
        elif crash_snapshot.crash_count:
            crash_status = "pass"
            crash_detail = f"{crash_snapshot.crash_count} verified crash report(s) are available."
        else:
            crash_status = "warn"
            crash_detail = "No structured crash report is available; runtime and log evidence can still be prepared."
        gates.append(
            self._gate(
                "crash_evidence",
                "Crash evidence integrity",
                crash_status,
                "blocker" if crash_status == "block" else "warning",
                crash_detail,
                "Export fresh crash evidence and resolve integrity failures before sharing a bundle.",
            )
        )

        eligible_logs = self._eligible_logs(max_age) if include_logs else ()
        if not include_logs:
            log_status = "pass"
            log_detail = "Log collection was disabled by the operator."
        elif eligible_logs:
            log_status = "pass"
            log_detail = f"{len(eligible_logs)} recent text log file(s) are eligible for redacted collection."
        else:
            log_status = "warn"
            log_detail = f"No readable text log newer than {max_age} day(s) is available."
        gates.append(
            self._gate(
                "log_inventory",
                "Recent support logs",
                log_status,
                "warning",
                log_detail,
                "Reproduce the issue once, then refresh the support snapshot.",
            )
        )

        estimated_size = self._estimated_size(crash_snapshot, eligible_logs)
        if estimated_size <= max_bundle_bytes:
            budget_status = "pass"
            budget_detail = (
                f"Estimated evidence size is {self._format_bytes(estimated_size)} within the "
                f"{self._format_bytes(max_bundle_bytes)} bundle cap."
            )
        else:
            budget_status = "warn"
            budget_detail = (
                f"Estimated evidence size is {self._format_bytes(estimated_size)}; optional logs and reports "
                f"will be capped at {self._format_bytes(max_bundle_bytes)}."
            )
        gates.append(
            self._gate(
                "bundle_budget",
                "Support bundle size budget",
                budget_status,
                "warning",
                budget_detail,
                "Reduce optional logs or increase the reviewed bundle limit.",
            )
        )

        free_space = self._free_space_bytes()
        minimum_free = max_bundle_bytes * 2 + 32 * 1024 * 1024
        disk_ok = free_space >= minimum_free
        gates.append(
            self._gate(
                "support_storage",
                "Support evidence storage",
                "pass" if disk_ok else "block",
                "blocker",
                (
                    f"Available artifact storage is {self._format_bytes(free_space)}."
                    if disk_ok
                    else f"Only {self._format_bytes(free_space)} is free; at least {self._format_bytes(minimum_free)} is required."
                ),
                "Free artifact storage before preparing the support bundle.",
            )
        )

        gates.append(
            self._gate(
                "privacy_policy",
                "Privacy exclusion policy",
                "pass",
                "blocker",
                "Databases, settings, API profiles, credentials, generated audio and project sources are excluded.",
                "Do not manually add private files to the verified bundle.",
            )
        )
        gates.append(
            self._gate(
                "manual_transport",
                "Manual support transport",
                "pass",
                "blocker",
                "Bundle creation is local. Upload, email and publication remain explicit manual actions.",
                "Review the verified receipt before manually sharing the bundle.",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            status_summary = f"Incident support is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_warnings"
            status_summary = f"Incident support is ready with {warning_count} warning(s)."
        else:
            status = "ready"
            status_summary = "Incident support evidence is ready for acknowledged local preparation."

        return IncidentSupportSnapshot(
            incident_id=incident_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            severity=normalized_severity,
            summary=safe_summary,
            status=status,
            status_summary=status_summary,
            support_allowed=blocker_count == 0,
            baseline_verified=baseline_ok,
            crash_count=crash_snapshot.crash_count,
            unacknowledged_count=crash_snapshot.unacknowledged_count,
            integrity_failure_count=crash_snapshot.integrity_failure_count,
            eligible_log_count=len(eligible_logs),
            estimated_size_bytes=estimated_size,
            max_bundle_bytes=max_bundle_bytes,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )

    def create_bundle(
        self,
        snapshot: IncidentSupportSnapshot,
        *,
        baseline_path: Path | None = None,
        include_logs: bool = True,
        max_log_age_days: int = 14,
        acknowledge: bool = False,
    ) -> IncidentSupportBundle | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review and acknowledge the privacy and manual-transport gates before creating a support bundle.",
                "path": "",
            }

        baseline = Path(baseline_path or self.default_baseline_path())
        baseline_ok, baseline_detail = self.post_ga_service.verify_baseline(baseline)
        if not baseline_ok:
            return {"status": "blocked", "detail": baseline_detail, "path": ""}

        files: dict[str, bytes] = {}
        files["incident/summary.json"] = self._json_bytes(
            {
                "schema_version": self.SCHEMA_VERSION,
                "incident_id": snapshot.incident_id,
                "created_at": self._now_iso(),
                "version": snapshot.version,
                "channel": snapshot.channel,
                "severity": snapshot.severity,
                "summary": snapshot.summary,
                "manual_review_required": True,
                "automatic_upload": False,
                "automatic_send": False,
                "automatic_publish": False,
                "private_data_included": False,
            }
        )
        files["incident/post-ga-baseline-reference.json"] = self._json_bytes(
            {
                "role": "post_ga_baseline",
                "filename": baseline.name,
                "size_bytes": baseline.stat().st_size,
                "sha256": self._sha256(baseline),
                "verification": "passed",
            }
        )

        crash_snapshot = self.crash_service.snapshot()
        files["diagnostics/crash-recovery-snapshot.json"] = self._json_bytes(
            self._sanitize_value(crash_snapshot.to_dict())
        )
        report_count = 0
        for record in crash_snapshot.reports:
            if report_count >= self.MAX_REPORTS:
                break
            if record.integrity_status != "verified":
                continue
            payload = self.crash_service.read_report(record.report_id)
            content = self._json_bytes(self._sanitize_value(payload))
            name = f"diagnostics/crash-reports/{self._safe_filename(record.report_id)}.json"
            if not self._fits_budget(files, name, content, snapshot.max_bundle_bytes):
                break
            files[name] = content
            report_count += 1

        log_count = 0
        if include_logs:
            for path in self._eligible_logs(max(1, int(max_log_age_days))):
                safe_name = self._safe_filename(path.name)
                content = self._sanitize_text(self._read_text_capped(path, self.MAX_LOG_BYTES)).encode(
                    "utf-8"
                )
                name = f"diagnostics/logs/{safe_name}"
                if not self._fits_budget(files, name, content, snapshot.max_bundle_bytes):
                    break
                files[name] = content
                log_count += 1

        files["diagnostics/environment.json"] = self._json_bytes(
            {
                "application_version": snapshot.version,
                "release_channel": snapshot.channel,
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "architecture": platform.machine(),
                "frozen": bool(getattr(sys, "frozen", False)),
                "safe_mode": self.crash_service.safe_mode,
                "local_paths_included": False,
            }
        )
        files["README.md"] = self._bundle_readme(snapshot, report_count, log_count).encode("utf-8")

        manifest_files = {
            name: {"size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(files.items())
        }
        manifest: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "incident_id": snapshot.incident_id,
            "created_at": self._now_iso(),
            "version": snapshot.version,
            "channel": snapshot.channel,
            "severity": snapshot.severity,
            "manual_review_required": True,
            "automatic_upload": False,
            "automatic_send": False,
            "automatic_publish": False,
            "private_data_included": False,
            "files": manifest_files,
        }
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        files["incident/manifest.json"] = self._json_bytes(manifest)

        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        bundle_id = f"incident-support-{stamp}-{uuid.uuid4().hex[:8]}"
        path = self.bundles_dir / f"S-Talking-{bundle_id}.zip"
        temporary = path.with_suffix(path.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(name, content)
        temporary.replace(path)

        ok, detail = self.verify_bundle(path)
        if not ok:
            path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}

        receipt_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "bundle_id": bundle_id,
            "incident_id": snapshot.incident_id,
            "created_at": self._now_iso(),
            "severity": snapshot.severity,
            "bundle": {
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": self._sha256(path),
            },
            "report_count": report_count,
            "log_count": log_count,
            "verification": "passed",
            "manual_review_required": True,
            "automatic_upload": False,
            "automatic_send": False,
            "private_data_included": False,
        }
        receipt_payload["receipt_sha256"] = self._payload_digest(receipt_payload)
        receipt_path = self.receipts_dir / f"{bundle_id}.json"
        self._write_json(receipt_path, receipt_payload)
        self._write_json(self.root / "latest-incident-support-receipt.json", receipt_payload)

        return IncidentSupportBundle(
            bundle_id=bundle_id,
            incident_id=snapshot.incident_id,
            created_at=str(receipt_payload["created_at"]),
            path=path,
            receipt_path=receipt_path,
            severity=snapshot.severity,
            report_count=report_count,
            log_count=log_count,
            size_bytes=path.stat().st_size,
            sha256=self._sha256(path),
        )

    def verify_bundle(self, path: Path) -> tuple[bool, str]:
        candidate = Path(path)
        if not candidate.is_file():
            return False, "Incident support bundle does not exist."
        try:
            with zipfile.ZipFile(candidate) as archive:
                names = archive.namelist()
                if any(self._unsafe_archive_name(name) for name in names):
                    return False, "Incident support bundle contains an unsafe archive path."
                if any(self._FORBIDDEN_NAME_RE.search(Path(name).name) for name in names):
                    return False, "Incident support bundle contains a forbidden private artifact."
                manifest_name = "incident/manifest.json"
                if manifest_name not in names:
                    return False, "Incident support manifest is missing."
                manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"))
                expected_digest = str(manifest.get("manifest_sha256") or "")
                unsigned = dict(manifest)
                unsigned.pop("manifest_sha256", None)
                if expected_digest != self._payload_digest(unsigned):
                    return False, "Incident support manifest SHA-256 does not match."
                if str(manifest.get("version") or "") != self.version or str(manifest.get("channel") or "") != "stable":
                    return False, "Incident support bundle identity does not match the application."
                if any(
                    manifest.get(name) is not False
                    for name in ("automatic_upload", "automatic_send", "automatic_publish")
                ):
                    return False, "Incident support bundle violates the manual-transport contract."
                if manifest.get("private_data_included") is not False:
                    return False, "Incident support bundle violates the privacy contract."
                entries = manifest.get("files")
                if not isinstance(entries, Mapping):
                    return False, "Incident support manifest file inventory is invalid."
                expected_names = set(entries) | {manifest_name}
                if set(names) != expected_names:
                    return False, "Incident support bundle contains an unmanifested artifact."
                for name, evidence in entries.items():
                    if not isinstance(evidence, Mapping):
                        return False, f"Incident support evidence is invalid: {name}"
                    data = archive.read(name)
                    if len(data) != int(evidence.get("size_bytes") or -1):
                        return False, f"Incident support artifact size mismatch: {name}"
                    if hashlib.sha256(data).hexdigest() != str(evidence.get("sha256") or ""):
                        return False, f"Incident support artifact integrity mismatch: {name}"
                    if self._is_text_artifact(name):
                        text = data.decode("utf-8", errors="replace")
                        if self._contains_secret_text(text):
                            return False, f"Incident support artifact contains secret-like content: {name}"
                        if self._contains_local_path(text):
                            return False, f"Incident support artifact contains a local user path: {name}"
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            return False, f"Incident support bundle verification failed: {self._sanitize_text(str(exc))}"
        return True, "Incident support bundle is privacy-safe and integrity verified."

    def verify_receipt(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident support receipt is unreadable."
        expected = str(payload.get("receipt_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident support receipt SHA-256 does not match."
        bundle = payload.get("bundle")
        if not isinstance(bundle, Mapping):
            return False, "Incident support receipt is missing bundle evidence."
        filename = str(bundle.get("filename") or "")
        if Path(filename).name != filename:
            return False, "Incident support receipt contains an unsafe bundle filename."
        candidate = self.bundles_dir / filename
        if not candidate.is_file():
            return False, "Incident support bundle referenced by the receipt is missing."
        if candidate.stat().st_size != int(bundle.get("size_bytes") or -1):
            return False, "Incident support receipt bundle size does not match."
        if self._sha256(candidate) != str(bundle.get("sha256") or ""):
            return False, "Incident support receipt bundle SHA-256 does not match."
        return self.verify_bundle(candidate)

    def _eligible_logs(self, max_age_days: int) -> tuple[Path, ...]:
        if not self.runtime.log_dir.exists():
            return ()
        now = self._now().timestamp()
        max_age_seconds = max(1, max_age_days) * 86400
        candidates: list[Path] = []
        for path in self.runtime.log_dir.iterdir():
            if not path.is_file() or path.suffix.casefold() not in {".log", ".txt", ".jsonl"}:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 0 or now - stat.st_mtime > max_age_seconds:
                continue
            candidates.append(path)
        candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return tuple(candidates[: self.MAX_LOG_FILES])

    def _estimated_size(self, crash_snapshot: Any, logs: tuple[Path, ...]) -> int:
        report_bytes = sum(
            min(record.report_path.stat().st_size, self.MAX_LOG_BYTES)
            for record in crash_snapshot.reports[: self.MAX_REPORTS]
            if record.integrity_status == "verified" and record.report_path.is_file()
        )
        log_bytes = sum(min(path.stat().st_size, self.MAX_LOG_BYTES) for path in logs)
        return 64 * 1024 + report_bytes + log_bytes

    def _artifact(self, role: str, path: Path) -> IncidentSupportArtifact:
        return IncidentSupportArtifact(
            role=role,
            path=Path(path),
            size_bytes=Path(path).stat().st_size,
            sha256=self._sha256(Path(path)),
        )

    def _free_space_bytes(self) -> int:
        try:
            return int(self._disk_usage(self.runtime.artifacts_dir).free)
        except (OSError, ValueError):
            return 0

    def _sanitize_text(self, value: str) -> str:
        text = str(value)
        text = self._AUTHORIZATION_RE.sub("Authorization=[REDACTED]", text)
        text = self._SECRET_ASSIGNMENT_RE.sub(
            lambda match: f"{match.group(1)}=[REDACTED]", text
        )
        text = self._BEARER_RE.sub("Bearer [REDACTED]", text)
        text = self._TOKEN_RE.sub("[REDACTED-TOKEN]", text)
        text = self._URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
        replacements = [
            (Path.home(), "%USERPROFILE%"),
            (self.runtime.settings_path.parent, "<SETTINGS_DIR>"),
            (self.runtime.data_dir, "<DATA_DIR>"),
            (self.runtime.cache_dir, "<CACHE_DIR>"),
            (self.runtime.default_output_dir, "<OUTPUT_DIR>"),
            (self.runtime.reports_dir, "<REPORTS_DIR>"),
            (self.runtime.artifacts_dir, "<ARTIFACTS_DIR>"),
            (self.runtime.app_root, "<APP_ROOT>"),
        ]
        for path, marker in sorted(replacements, key=lambda item: len(str(item[0])), reverse=True):
            raw = str(path)
            if raw:
                text = text.replace(raw, marker).replace(raw.replace("\\", "/"), marker)
        text = self._WINDOWS_USER_PATH_RE.sub(r"%USERPROFILE%", text)
        text = self._POSIX_HOME_RE.sub("%USERPROFILE%", text)
        return text

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): (
                    "[REDACTED]"
                    if self._SECRET_KEY_RE.search(str(key))
                    else self._sanitize_value(child)
                )
                for key, child in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, Path):
            return self._sanitize_text(str(value))
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    def _contains_secret_text(self, value: str) -> bool:
        text = str(value)
        text = re.sub(
            r"(?i)[\"']?\b(api[_-]?key|authorization|token|secret|password|passwd|cookie|credential)\b[\"']?"
            r"\s*[:=]\s*(?:\"?\[REDACTED[^\]]*\]\"?)",
            "",
            text,
        )
        text = re.sub(r"(?i)\bbearer\s+\[REDACTED[^\]]*\]", "", text)
        text = re.sub(r"\[REDACTED[^\]]*\]", "", text)
        return bool(
            self._TOKEN_RE.search(text)
            or self._AUTHORIZATION_RE.search(text)
            or self._SECRET_ASSIGNMENT_RE.search(text)
            or self._BEARER_RE.search(text)
            or self._URL_CREDENTIAL_RE.search(text)
        )

    def _contains_local_path(self, value: str) -> bool:
        text = str(value)
        return bool(
            self._WINDOWS_USER_PATH_RE.search(text)
            or self._POSIX_HOME_RE.search(text)
            or any(
                raw and (raw in text or raw.replace("\\", "/") in text)
                for raw in (
                    str(self.runtime.app_root),
                    str(self.runtime.data_dir),
                    str(self.runtime.settings_path.parent),
                    str(self.runtime.default_output_dir),
                )
            )
        )

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> IncidentSupportGate:
        return IncidentSupportGate(code, label, status, severity, detail, remediation)

    @staticmethod
    def _safe_filename(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")[:180] or "evidence"

    @staticmethod
    def _is_text_artifact(name: str) -> bool:
        return Path(name).suffix.casefold() in {".json", ".log", ".txt", ".md", ".jsonl"}

    @staticmethod
    def _unsafe_archive_name(name: str) -> bool:
        candidate = Path(name.replace("\\", "/"))
        return name.startswith(("/", "\\")) or candidate.is_absolute() or ".." in candidate.parts

    @staticmethod
    def _json_bytes(payload: Any) -> bytes:
        return (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

    @staticmethod
    def _read_text_capped(path: Path, limit: int) -> str:
        try:
            return path.read_bytes()[:limit].decode("utf-8", errors="replace")
        except OSError:
            return "<unreadable log file>"

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _format_bytes(value: int) -> str:
        number = float(max(0, value))
        for suffix in ("B", "KB", "MB", "GB", "TB"):
            if number < 1024 or suffix == "TB":
                return f"{number:.1f} {suffix}" if suffix != "B" else f"{int(number)} B"
            number /= 1024
        return f"{int(value)} B"

    @staticmethod
    def _fits_budget(
        files: Mapping[str, bytes],
        name: str,
        content: bytes,
        maximum: int,
    ) -> bool:
        current = sum(len(value) for value in files.values())
        manifest_reserve = 64 * 1024 + len(name.encode("utf-8"))
        return current + len(content) + manifest_reserve <= maximum

    def _bundle_readme(
        self,
        snapshot: IncidentSupportSnapshot,
        report_count: int,
        log_count: int,
    ) -> str:
        return "\n".join(
            [
                "# S Talking incident support bundle",
                "",
                f"Incident: {snapshot.incident_id}",
                f"Severity: {snapshot.severity}",
                f"Application: {snapshot.version}/{snapshot.channel}",
                f"Crash reports: {report_count}",
                f"Redacted logs: {log_count}",
                "",
                "This bundle excludes databases, settings, API profiles, credentials, generated audio and project sources.",
                "It is created locally and is never uploaded, emailed or published automatically.",
                "Review the manifest and receipt before manually sharing it with an authorized support recipient.",
                "",
            ]
        )

    def _incident_id(self, generated_at: str) -> str:
        stamp = re.sub(r"[^0-9A-Za-z]+", "", generated_at)
        return f"incident-{stamp}-{uuid.uuid4().hex[:8]}"

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
