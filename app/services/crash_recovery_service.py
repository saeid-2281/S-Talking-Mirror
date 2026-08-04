from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sqlite3
import sys
import threading
import traceback
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

import app
from app.config.runtime import RuntimeConfig
from app.models.crash_recovery import (
    CrashDiagnosticsBundle,
    CrashRecoveryGate,
    CrashRecoverySnapshot,
    CrashReportRecord,
)


class CrashRecoveryService:
    """Capture privacy-safe crash evidence and expose deterministic recovery state.

    The service never copies project sources, generated audio, databases, settings,
    API profiles or credential stores into support bundles. Exception tracebacks are
    represented as frame metadata without source-code lines or local variables.
    """

    REPORT_SCHEMA = 1
    SESSION_SCHEMA = 1
    BUNDLE_SCHEMA = 1
    MAX_REPORTS = 30
    MAX_LOG_FILES = 8
    MAX_LOG_BYTES = 192_000
    MAX_MESSAGE_CHARS = 600
    SENSITIVE_KEY_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|token|secret|password|passwd|cookie|credential|private[_-]?key)"
    )
    AUTHORIZATION_HEADER_RE = re.compile(
        r"(?i)\bauthorization\b\s*[:=]\s*"
        r"(?:(?:bearer|basic|token)\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    )
    SECRET_ASSIGNMENT_RE = re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|passwd|cookie|credential)\b"
        r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
    )
    BEARER_RE = re.compile(r"(?i)\bbearer\s+(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)")
    URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")
    LONG_QUOTED_RE = re.compile(r"(['\"])(?:(?!\1).){64,}\1")
    TOKEN_LIKE_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{16,}\b")

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.root = runtime.artifacts_dir / "crash-recovery"
        self.reports_dir = self.root / "reports"
        self.bundles_dir = self.root / "bundles"
        self.state_dir = runtime.cache_dir / "crash-recovery"
        self.session_marker = self.state_dir / "active-session.json"
        self.last_clean_shutdown = self.state_dir / "last-clean-shutdown.json"
        self.latest_pointer = self.root / "latest-crash.json"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._session_id = ""
        self._session_started_at = ""
        self._previous_unclean: dict[str, Any] | None = None
        self._safe_mode = False
        self._installed = False
        self._original_sys_hook = None
        self._original_thread_hook = None
        self._qt_previous_handler = None
        self._qt_handler_installed = False
        self._capture_guard = threading.local()
        self._ensure_directories()

    @property
    def safe_mode(self) -> bool:
        return self._safe_mode

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def previous_unclean_shutdown(self) -> bool:
        return bool(self._previous_unclean)

    def unacknowledged_report_count(self) -> int:
        return sum(not record.acknowledged for record in self.list_reports())

    def safe_mode_requested(self, argv: list[str] | None = None) -> bool:
        arguments = argv if argv is not None else list(sys.argv)
        env_value = os.environ.get("S_TALKING_SAFE_MODE", "")
        return "--safe-mode" in arguments or env_value.strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def begin_session(
        self,
        *,
        argv: list[str] | None = None,
        safe_mode: bool | None = None,
        pid: int | None = None,
    ) -> dict[str, object]:
        if self._session_id:
            return self._session_payload()
        previous = self._json(self.session_marker)
        if previous and str(previous.get("session_id") or ""):
            self._previous_unclean = previous
        self._safe_mode = self.safe_mode_requested(argv) if safe_mode is None else bool(safe_mode)
        self._session_started_at = self._now()
        session_stamp = re.sub(r"[^0-9A-Za-z]+", "", self._session_started_at)
        self._session_id = f"session-{session_stamp}-{uuid.uuid4().hex[:10]}"
        payload = self._session_payload(pid=pid)
        self._write_json(self.session_marker, payload)
        return payload

    def mark_clean_shutdown(self) -> Path:
        payload = {
            "schema_version": self.SESSION_SCHEMA,
            "session_id": self._session_id,
            "started_at": self._session_started_at,
            "closed_at": self._now(),
            "app_version": app.__version__,
            "status": "clean",
        }
        self._write_json(self.last_clean_shutdown, payload)
        current = self._json(self.session_marker)
        if not self._session_id or str(current.get("session_id") or "") == self._session_id:
            self.session_marker.unlink(missing_ok=True)
        return self.last_clean_shutdown

    def install_handlers(self, *, include_qt: bool = False) -> None:
        if not self._installed:
            self._original_sys_hook = sys.excepthook
            self._original_thread_hook = threading.excepthook
            sys.excepthook = self._sys_excepthook
            threading.excepthook = self._threading_excepthook
            self._installed = True
        if include_qt:
            self.install_qt_message_handler()

    def install_qt_message_handler(self) -> bool:
        if self._qt_handler_installed:
            return True
        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        except Exception:
            return False

        def handler(message_type, context, message) -> None:
            if message_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                self.capture_message(
                    str(message),
                    source="qt",
                    severity="fatal" if message_type == QtMsgType.QtFatalMsg else "error",
                    context={
                        "category": str(getattr(context, "category", "") or ""),
                        "file": str(getattr(context, "file", "") or ""),
                        "line": int(getattr(context, "line", 0) or 0),
                        "function": str(getattr(context, "function", "") or ""),
                    },
                )
            previous = self._qt_previous_handler
            if callable(previous):
                previous(message_type, context, message)
            else:
                category = str(getattr(context, "category", "") or "qt")
                sys.stderr.write(f"{category}: {message}\n")

        self._qt_previous_handler = qInstallMessageHandler(handler)
        self._qt_handler_installed = True
        return True

    def uninstall_handlers(self) -> None:
        if self._installed:
            if sys.excepthook == self._sys_excepthook and self._original_sys_hook is not None:
                sys.excepthook = self._original_sys_hook
            if threading.excepthook == self._threading_excepthook and self._original_thread_hook is not None:
                threading.excepthook = self._original_thread_hook
            self._installed = False
        if self._qt_handler_installed:
            try:
                from PySide6.QtCore import qInstallMessageHandler

                qInstallMessageHandler(self._qt_previous_handler)
            except Exception:
                pass
            self._qt_handler_installed = False

    def capture_exception(
        self,
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
        *,
        source: str = "sys",
        severity: str = "fatal",
        context: dict[str, Any] | None = None,
    ) -> CrashReportRecord | None:
        if getattr(self._capture_guard, "active", False):
            return None
        self._capture_guard.active = True
        try:
            frames = self._traceback_frames(tb)
            exception_type = getattr(exc_type, "__name__", str(exc_type))
            message = self._safe_exception_message(exc)
            created_at = self._now()
            fingerprint = self._fingerprint(exception_type, message, frames)
            report_stamp = re.sub(r"[^0-9A-Za-z]+", "", created_at)
            report_id = f"crash-{report_stamp}-{fingerprint[:10]}-{uuid.uuid4().hex[:6]}"
            body: dict[str, Any] = {
                "schema_version": self.REPORT_SCHEMA,
                "report_id": report_id,
                "created_at": created_at,
                "source": self._safe_label(source),
                "severity": self._safe_label(severity),
                "exception_type": self._safe_label(exception_type),
                "summary": self._sanitize_text(message),
                "thread_name": self._sanitize_text(threading.current_thread().name),
                "app_version": app.__version__,
                "fingerprint": fingerprint,
                "acknowledged": False,
                "safe_mode_recommended": severity.casefold() in {"fatal", "critical"},
                "session": {
                    "session_id": self._session_id,
                    "started_at": self._session_started_at,
                    "safe_mode": self._safe_mode,
                },
                "runtime": self._runtime_metadata(),
                "frames": frames,
                "context": self._sanitize_value(context or {}),
            }
            body["integrity_sha256"] = self._checksum(body)
            path = self.reports_dir / f"{report_id}.json"
            self._write_json(path, body)
            self._write_json(
                self.latest_pointer,
                {
                    "schema_version": 1,
                    "report_id": report_id,
                    "report_path": str(path),
                    "created_at": created_at,
                    "fingerprint": fingerprint,
                },
            )
            self._enforce_retention()
            return self._record_from_payload(path, body, integrity_status="verified")
        finally:
            self._capture_guard.active = False

    def capture_message(
        self,
        message: str,
        *,
        source: str = "runtime",
        severity: str = "error",
        context: dict[str, Any] | None = None,
    ) -> CrashReportRecord | None:
        try:
            raise RuntimeError(self._safe_exception_message(RuntimeError(message)))
        except RuntimeError as exc:
            return self.capture_exception(
                RuntimeError,
                exc,
                exc.__traceback__,
                source=source,
                severity=severity,
                context=context,
            )

    def list_reports(self) -> tuple[CrashReportRecord, ...]:
        records: list[CrashReportRecord] = []
        if not self.reports_dir.exists():
            return ()
        for path in sorted(
            self.reports_dir.glob("crash-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            payload = self._json(path)
            if not payload:
                records.append(self._unreadable_record(path))
                continue
            expected = str(payload.get("integrity_sha256") or "")
            integrity = "verified" if expected and expected == self._checksum(payload) else "mismatch"
            try:
                records.append(self._record_from_payload(path, payload, integrity_status=integrity))
            except (KeyError, TypeError, ValueError):
                records.append(self._unreadable_record(path))
        return tuple(records)

    def read_report(self, report_id: str) -> dict[str, Any]:
        path = self._report_path(report_id)
        payload = self._json(path)
        if not payload:
            raise ValueError("Crash report is unreadable.")
        if str(payload.get("integrity_sha256") or "") != self._checksum(payload):
            raise ValueError("Crash report integrity verification failed.")
        return self._sanitize_value(payload)

    def acknowledge(self, report_id: str) -> CrashReportRecord:
        path = self._report_path(report_id)
        payload = self._json(path)
        if not payload:
            raise ValueError("Crash report is unreadable.")
        if str(payload.get("integrity_sha256") or "") != self._checksum(payload):
            raise ValueError("Crash report integrity verification failed.")
        payload["acknowledged"] = True
        payload["acknowledged_at"] = self._now()
        payload["integrity_sha256"] = self._checksum(payload)
        self._write_json(path, payload)
        return self._record_from_payload(path, payload, integrity_status="verified")

    def snapshot(self) -> CrashRecoverySnapshot:
        reports = self.list_reports()
        integrity_failures = sum(record.integrity_status != "verified" for record in reports)
        unacknowledged = sum(not record.acknowledged for record in reports)
        queue_path = self.runtime.cache_dir / "generation-recovery.json"
        session_path = self.runtime.cache_dir / "session-restore.json"
        queue_available, queue_detail = self._validate_json_file(queue_path, expected_mapping=True)
        session_available, session_detail = self._validate_json_file(session_path, expected_mapping=True)
        database_status, database_detail = self._database_status()
        previous_unclean = bool(self._previous_unclean)
        gates = (
            CrashRecoveryGate(
                "unclean_shutdown",
                "Previous shutdown",
                "warning" if previous_unclean else "passed",
                "warning",
                (
                    "The previous session did not record a clean shutdown."
                    if previous_unclean
                    else "No unclean previous session is pending."
                ),
                "Review crash evidence and use safe mode when repeated startup failures occur.",
            ),
            CrashRecoveryGate(
                "report_integrity",
                "Crash report integrity",
                "failed" if integrity_failures else "passed",
                "blocker",
                (
                    f"{integrity_failures} report(s) failed integrity verification."
                    if integrity_failures
                    else "Structured crash reports are readable and integrity verified."
                ),
                "Do not share modified reports; export a fresh diagnostics bundle.",
            ),
            CrashRecoveryGate(
                "queue_recovery",
                "Generation recovery evidence",
                "passed" if queue_available or not queue_path.exists() else "warning",
                "warning",
                queue_detail,
                "Open the existing generation recovery workflow before discarding malformed evidence.",
            ),
            CrashRecoveryGate(
                "session_restore",
                "Session restore evidence",
                "passed" if session_available or not session_path.exists() else "warning",
                "warning",
                session_detail,
                "Start in safe mode to skip automatic project and session restoration.",
            ),
            CrashRecoveryGate(
                "database_health",
                "Database quick check",
                "passed" if database_status in {"healthy", "not_created"} else "failed",
                "blocker",
                database_detail,
                "Use Upgrade & Recovery before replacing or restoring the database.",
            ),
            CrashRecoveryGate(
                "safe_mode",
                "Safe-mode startup",
                "passed",
                "info",
                (
                    "Safe mode is active; project restore, generation recovery prompts and startup update checks are skipped."
                    if self._safe_mode
                    else "Normal startup mode is active. Safe mode remains available with --safe-mode."
                ),
            ),
        )
        blocker_count = sum(gate.severity == "blocker" and not gate.passed for gate in gates)
        warning_count = sum(gate.severity == "warning" and not gate.passed for gate in gates)
        if blocker_count:
            status = "blocked"
            summary = "Crash recovery evidence requires integrity or database attention."
        elif warning_count or unacknowledged:
            status = "attention"
            summary = "Recovery evidence is available for review."
        else:
            status = "healthy"
            summary = "No unresolved crash or recovery issue is currently detected."
        latest = reports[0].report_path if reports else None
        return CrashRecoverySnapshot(
            captured_at=self._now(),
            status=status,
            summary=summary,
            session_id=self._session_id,
            session_started_at=self._session_started_at,
            safe_mode=self._safe_mode,
            previous_unclean_shutdown=previous_unclean,
            crash_count=len(reports),
            unacknowledged_count=unacknowledged,
            integrity_failure_count=integrity_failures,
            queue_recovery_available=queue_available and queue_path.exists(),
            session_restore_available=session_available and session_path.exists(),
            database_status=database_status,
            latest_report_path=latest,
            gates=gates,
            reports=reports,
        )

    def export_bundle(
        self,
        *,
        report_ids: list[str] | tuple[str, ...] | None = None,
        include_logs: bool = True,
    ) -> CrashDiagnosticsBundle:
        snapshot = self.snapshot()
        selected = set(report_ids or [record.report_id for record in snapshot.reports[:10]])
        files: dict[str, bytes] = {}
        files["diagnostics/crash-recovery-snapshot.json"] = self._json_bytes(
            self._sanitize_value(snapshot.to_dict())
        )
        report_count = 0
        for record in snapshot.reports:
            if record.report_id not in selected or record.integrity_status != "verified":
                continue
            payload = self.read_report(record.report_id)
            files[f"diagnostics/crash-reports/{record.report_id}.json"] = self._json_bytes(payload)
            report_count += 1
        files["diagnostics/recovery-evidence.json"] = self._json_bytes(self._recovery_evidence())
        files["diagnostics/environment.json"] = self._json_bytes(self._runtime_metadata())
        log_count = 0
        if include_logs:
            for path in self._recent_logs():
                safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.name)
                files[f"diagnostics/logs/{safe_name}"] = self._sanitize_text(
                    self._read_text_capped(path, self.MAX_LOG_BYTES)
                ).encode("utf-8")
                log_count += 1
        files["diagnostics/README.md"] = self._bundle_readme(snapshot, report_count, log_count).encode("utf-8")
        manifest = {
            name: {
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in sorted(files.items())
        }
        files["diagnostics/manifest.json"] = self._json_bytes(
            {
                "schema_version": self.BUNDLE_SCHEMA,
                "created_at": self._now(),
                "files": manifest,
            }
        )
        created_at = self._now()
        bundle_stamp = re.sub(r"[^0-9A-Za-z]+", "", created_at)
        bundle_id = f"crash-diagnostics-{bundle_stamp}-{uuid.uuid4().hex[:8]}"
        path = self.bundles_dir / f"S-Talking-{bundle_id}.zip"
        temporary = path.with_suffix(path.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(files.items()):
                archive.writestr(name, content)
        temporary.replace(path)
        ok, detail = self.verify_bundle(path)
        if not ok:
            path.unlink(missing_ok=True)
            raise ValueError(detail)
        return CrashDiagnosticsBundle(
            bundle_id=bundle_id,
            created_at=created_at,
            path=path,
            report_count=report_count,
            log_count=log_count,
            size_bytes=path.stat().st_size,
            sha256=self._sha256(path),
            status="verified",
        )

    def verify_bundle(self, path: Path) -> tuple[bool, str]:
        candidate = Path(path)
        if not candidate.is_file():
            return False, "Diagnostics bundle does not exist."
        try:
            with zipfile.ZipFile(candidate) as archive:
                names = archive.namelist()
                if any(self._unsafe_archive_name(name) for name in names):
                    return False, "Diagnostics bundle contains an unsafe archive path."
                manifest_name = "diagnostics/manifest.json"
                if manifest_name not in names:
                    return False, "Diagnostics bundle manifest is missing."
                manifest = json.loads(archive.read(manifest_name).decode("utf-8-sig"))
                entries = dict(manifest.get("files") or {})
                expected_names = set(entries) | {manifest_name}
                if set(names) != expected_names:
                    return False, "Diagnostics bundle contains an unmanifested artifact."
                for name, evidence in entries.items():
                    if name not in names:
                        return False, f"Diagnostics artifact is missing: {name}"
                    data = archive.read(name)
                    if len(data) != int(evidence.get("size_bytes") or -1):
                        return False, f"Diagnostics artifact size mismatch: {name}"
                    if hashlib.sha256(data).hexdigest() != str(evidence.get("sha256") or ""):
                        return False, f"Diagnostics artifact integrity mismatch: {name}"
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            return False, f"Diagnostics bundle verification failed: {self._sanitize_text(str(exc))}"
        return True, "Diagnostics bundle is structurally safe and integrity verified."

    def safe_mode_command(self) -> str:
        executable = Path(sys.executable)
        if getattr(sys, "frozen", False):
            return f'"{executable}" --safe-mode'
        return f'"{executable}" -m app.frozen_main --safe-mode'

    def _sys_excepthook(self, exc_type, exc, tb) -> None:
        self.capture_exception(exc_type, exc, tb, source="sys", severity="fatal")
        original = self._original_sys_hook
        if callable(original) and original is not self._sys_excepthook:
            original(exc_type, exc, tb)

    def _threading_excepthook(self, args) -> None:
        self.capture_exception(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            source="thread",
            severity="error",
            context={"thread_name": getattr(args.thread, "name", "")},
        )
        original = self._original_thread_hook
        if callable(original) and original is not self._threading_excepthook:
            original(args)

    def _session_payload(self, *, pid: int | None = None) -> dict[str, object]:
        return {
            "schema_version": self.SESSION_SCHEMA,
            "session_id": self._session_id,
            "started_at": self._session_started_at,
            "pid": int(pid if pid is not None else os.getpid()),
            "app_version": app.__version__,
            "safe_mode": self._safe_mode,
            "frozen": bool(getattr(sys, "frozen", False)),
            "status": "active",
        }

    def _runtime_metadata(self) -> dict[str, object]:
        return {
            "application_version": app.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "safe_mode": self._safe_mode,
            "session_id": self._session_id,
            "paths": {
                "application": self._display_path(self.runtime.app_root),
                "data": self._display_path(self.runtime.data_dir),
                "logs": self._display_path(self.runtime.log_dir),
                "reports": self._display_path(self.runtime.reports_dir),
                "artifacts": self._display_path(self.runtime.artifacts_dir),
            },
        }

    def _traceback_frames(self, tb: TracebackType | None) -> list[dict[str, object]]:
        frames: list[dict[str, object]] = []
        for frame in traceback.extract_tb(tb) if tb is not None else []:
            frames.append(
                {
                    "file": self._display_path(Path(frame.filename)),
                    "line": int(frame.lineno),
                    "function": self._safe_label(frame.name),
                }
            )
        return frames[-80:]

    def _safe_exception_message(self, exc: BaseException) -> str:
        text = str(exc).replace("\r", " ").replace("\n", " ").strip()
        text = self.LONG_QUOTED_RE.sub("[REDACTED-LONG-VALUE]", text)
        text = self._sanitize_text(text)
        if len(text) > self.MAX_MESSAGE_CHARS:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            text = f"{text[:240]} … [truncated; message-sha256={digest}]"
        return text or exc.__class__.__name__

    def _sanitize_value(self, value: Any, *, key: str = "") -> Any:
        if key and self.SENSITIVE_KEY_RE.search(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {
                self._safe_label(str(item_key)): self._sanitize_value(item_value, key=str(item_key))
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._sanitize_value(item, key=key) for item in value]
        if isinstance(value, Path):
            return self._display_path(value)
        if isinstance(value, str):
            return self._sanitize_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self._sanitize_text(str(value))

    def _sanitize_text(self, text: str) -> str:
        value = str(text)
        value = self.AUTHORIZATION_HEADER_RE.sub("Authorization=[REDACTED]", value)
        value = self.SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
        value = self.BEARER_RE.sub("Bearer [REDACTED]", value)
        value = self.TOKEN_LIKE_RE.sub("[REDACTED-TOKEN]", value)
        value = self.URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", value)
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
                value = value.replace(raw, marker).replace(raw.replace("\\", "/"), marker)
        return value

    def _display_path(self, path: Path) -> str:
        try:
            resolved = Path(path).resolve(strict=False)
        except OSError:
            resolved = Path(path)
        return self._sanitize_text(str(resolved))

    def _recovery_evidence(self) -> dict[str, object]:
        paths = {
            "generation_recovery": self.runtime.cache_dir / "generation-recovery.json",
            "session_restore": self.runtime.cache_dir / "session-restore.json",
            "database": self.runtime.database_path,
            "last_clean_shutdown": self.last_clean_shutdown,
            "active_session": self.session_marker,
        }
        evidence: dict[str, object] = {}
        for role, path in paths.items():
            item: dict[str, object] = {
                "exists": path.exists(),
                "path": self._display_path(path),
            }
            if path.is_file():
                try:
                    item["size_bytes"] = path.stat().st_size
                    item["sha256"] = self._sha256(path)
                except OSError:
                    item["status"] = "unreadable"
            evidence[role] = item
        return evidence

    def _database_status(self) -> tuple[str, str]:
        path = self.runtime.database_path
        if not path.exists():
            return "not_created", "Database has not been created yet; no corruption evidence is present."
        try:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
            try:
                row = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return "unhealthy", f"Database quick check could not complete: {self._sanitize_text(str(exc))}"
        detail = str(row[0] if row else "unknown")
        if detail.casefold() == "ok":
            return "healthy", "SQLite quick check completed successfully."
        return "unhealthy", f"SQLite quick check reported: {self._sanitize_text(detail)}"

    def _validate_json_file(self, path: Path, *, expected_mapping: bool) -> tuple[bool, str]:
        if not path.exists():
            return False, f"No {path.name} evidence is present."
        payload = self._json(path)
        if not payload and expected_mapping:
            return False, f"{path.name} is malformed or unreadable."
        return True, f"{path.name} is readable and available for the existing recovery workflow."

    def _record_from_payload(
        self,
        path: Path,
        payload: dict[str, Any],
        *,
        integrity_status: str,
    ) -> CrashReportRecord:
        return CrashReportRecord(
            report_id=str(payload["report_id"]),
            created_at=str(payload["created_at"]),
            source=str(payload.get("source") or "runtime"),
            severity=str(payload.get("severity") or "error"),
            exception_type=str(payload.get("exception_type") or "Exception"),
            summary=str(payload.get("summary") or "Crash captured"),
            thread_name=str(payload.get("thread_name") or ""),
            app_version=str(payload.get("app_version") or ""),
            fingerprint=str(payload.get("fingerprint") or ""),
            report_path=path,
            acknowledged=bool(payload.get("acknowledged", False)),
            integrity_status=integrity_status,
            safe_mode_recommended=bool(payload.get("safe_mode_recommended", False)),
        )

    def _unreadable_record(self, path: Path) -> CrashReportRecord:
        return CrashReportRecord(
            report_id=path.stem,
            created_at="",
            source="unknown",
            severity="error",
            exception_type="UnreadableReport",
            summary="Crash report is malformed or unreadable.",
            thread_name="",
            app_version="",
            fingerprint="",
            report_path=path,
            acknowledged=False,
            integrity_status="unreadable",
            safe_mode_recommended=True,
        )

    def _report_path(self, report_id: str) -> Path:
        safe = self._safe_label(report_id)
        if safe != report_id or not safe.startswith("crash-"):
            raise ValueError("Invalid crash report identifier.")
        path = self.reports_dir / f"{safe}.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def _enforce_retention(self) -> None:
        paths = sorted(
            self.reports_dir.glob("crash-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if len(paths) <= self.MAX_REPORTS:
            return
        acknowledged: list[Path] = []
        unacknowledged: list[Path] = []
        for path in paths[self.MAX_REPORTS :]:
            payload = self._json(path)
            (acknowledged if payload.get("acknowledged") else unacknowledged).append(path)
        for path in acknowledged + unacknowledged:
            path.unlink(missing_ok=True)

    def _recent_logs(self) -> list[Path]:
        if not self.runtime.log_dir.exists():
            return []
        candidates = [path for path in self.runtime.log_dir.rglob("*.log") if path.is_file()]
        return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[: self.MAX_LOG_FILES]

    def _bundle_readme(
        self,
        snapshot: CrashRecoverySnapshot,
        report_count: int,
        log_count: int,
    ) -> str:
        return (
            "# S Talking Crash Diagnostics\n\n"
            f"- App version: {app.__version__}\n"
            f"- Recovery status: {snapshot.status}\n"
            f"- Structured crash reports: {report_count}\n"
            f"- Sanitized log files: {log_count}\n"
            f"- Safe mode command: `{self._sanitize_text(self.safe_mode_command())}`\n\n"
            "This bundle excludes databases, settings, API profiles, credentials, project sources, "
            "generated audio, output folders and cached provider content.\n"
        )

    def _fingerprint(
        self,
        exception_type: str,
        message: str,
        frames: list[dict[str, object]],
    ) -> str:
        canonical = json.dumps(
            {
                "type": exception_type,
                "message": message,
                "frames": frames[-12:],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _checksum(self, payload: dict[str, Any]) -> str:
        clean = {key: value for key, value in payload.items() if key != "integrity_sha256"}
        canonical = json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _json_bytes(payload: Any) -> bytes:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _unsafe_archive_name(name: str) -> bool:
        candidate = Path(name.replace("\\", "/"))
        return name.startswith(("/", "\\")) or candidate.is_absolute() or ".." in candidate.parts

    @staticmethod
    def _safe_label(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-")[:160] or "unknown"

    @staticmethod
    def _read_text_capped(path: Path, limit: int) -> str:
        try:
            data = path.read_bytes()[:limit]
        except OSError:
            return "<unreadable log file>"
        return data.decode("utf-8", errors="replace")

    def _now(self) -> str:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    def _ensure_directories(self) -> None:
        for path in (self.root, self.reports_dir, self.bundles_dir, self.state_dir):
            path.mkdir(parents=True, exist_ok=True)
