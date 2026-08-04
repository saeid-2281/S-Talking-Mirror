from __future__ import annotations

import hashlib
import os
import re
import sys
import traceback
from pathlib import Path

import app
from app.config.runtime import RuntimeConfig


def _crash_log_path() -> Path:
    try:
        runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
        runtime.ensure_directories()
        return runtime.log_dir / "startup-crash.log"
    except Exception:
        executable = Path(sys.executable).resolve()
        fallback = executable.parent / "S-Talking-Data" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "startup-crash.log"


def _runtime_diagnostics() -> str:
    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    return "\n".join(
        [
            f"app_version: {app.__version__}",
            f"executable: {sys.executable}",
            f"frozen: {getattr(sys, 'frozen', False)}",
            f"_MEIPASS: {getattr(sys, '_MEIPASS', '')}",
            f"app_root: {runtime.app_root}",
            f"bundled_root: {runtime.bundled_root}",
            f"data_dir: {runtime.data_dir}",
            f"settings_path: {runtime.settings_path}",
            f"log_dir: {runtime.log_dir}",
            f"reports_dir: {runtime.reports_dir}",
            f"artifacts_dir: {runtime.artifacts_dir}",
            f"QT_PLUGIN_PATH: {os.environ.get('QT_PLUGIN_PATH', '')}",
        ]
    )


_STARTUP_AUTHORIZATION_RE = re.compile(
    r"(?i)\bauthorization\b\s*[:=]\s*"
    r"(?:(?:bearer|basic|token)\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_STARTUP_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|cookie|credential)\b"
    r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_STARTUP_BEARER_RE = re.compile(
    r"(?i)\bbearer\s+(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_STARTUP_TOKEN_LIKE_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{16,}\b")
_STARTUP_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")
_STARTUP_LONG_QUOTED_RE = re.compile(r"(['\"])(?:(?!\1).){64,}\1")
_STARTUP_MESSAGE_LIMIT = 600


def _safe_startup_exception_message(exc: BaseException) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    text = _STARTUP_LONG_QUOTED_RE.sub("[REDACTED-LONG-VALUE]", text)
    text = _STARTUP_AUTHORIZATION_RE.sub("Authorization=[REDACTED]", text)
    text = _STARTUP_SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )
    text = _STARTUP_BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _STARTUP_TOKEN_LIKE_RE.sub("[REDACTED-TOKEN]", text)
    text = _STARTUP_URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
    if len(text) > _STARTUP_MESSAGE_LIMIT:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        text = f"{text[:240]} … [truncated; message-sha256={digest}]"
    return text or exc.__class__.__name__


def _write_crash(exc_type: type[BaseException], exc: BaseException, tb) -> None:
    path = _crash_log_path()
    frames = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(tb)
    ]
    text = (
        "S Talking startup crash\n\n"
        + _runtime_diagnostics()
        + f"\n\nException type: {getattr(exc_type, '__name__', 'Exception')}"
        + f"\nException message: {_safe_startup_exception_message(exc)}"
        + "\nTraceback frames (source lines and local variables omitted):\n"
        + "\n".join(frames)
    )
    path.write_text(text, encoding="utf-8")


def excepthook(exc_type: type[BaseException], exc: BaseException, tb) -> None:
    try:
        _write_crash(exc_type, exc, tb)
    finally:
        sys.__excepthook__(exc_type, exc, tb)



def _handle_recovery_command(argv: list[str]) -> int | None:
    recovery_flags = {
        "--upgrade-snapshot",
        "--create-upgrade-backup",
        "--validate-upgrade-migration",
        "--verify-backup",
        "--restore-backup",
    }
    if not any(flag in argv for flag in recovery_flags):
        return None

    import argparse

    from app.database.connection import Database
    from app.services.upgrade_recovery_service import UpgradeRecoveryService

    parser = argparse.ArgumentParser(prog="S-Talking.exe", description="S Talking upgrade and recovery tool")
    parser.add_argument("--upgrade-snapshot", action="store_true")
    parser.add_argument("--create-upgrade-backup", action="store_true")
    parser.add_argument("--validate-upgrade-migration", action="store_true")
    parser.add_argument("--verify-backup", type=Path)
    parser.add_argument("--restore-backup", type=Path)
    parser.add_argument("--acknowledge-restore", action="store_true")
    parser.add_argument("--source-version", default="")
    parser.add_argument(
        "--upgrade-mode",
        choices=("auto", "in_place", "portable_to_installed", "installed_to_portable", "rollback"),
        default="auto",
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = UpgradeRecoveryService(runtime, Database(runtime.database_path))
    snapshot = service.snapshot(
        source_version=args.source_version or None,
        mode=args.upgrade_mode,
        source_root=args.source_root,
    )
    print(f"Status:   {snapshot.status}")
    print(f"Versions: {snapshot.source_version} -> {snapshot.target_version}")
    print(f"Mode:     {snapshot.mode}")
    print(f"Schema:   {snapshot.current_schema}/{snapshot.target_schema}")
    for gate in snapshot.gates:
        if not gate.passed:
            print(f" - {gate.label} [{gate.severity}]: {gate.detail}")
    if snapshot.blocker_count and not (args.verify_backup or args.restore_backup):
        return 1
    if args.create_upgrade_backup:
        created = service.create_backup(
            source_version=args.source_version or None,
            mode=args.upgrade_mode,
            source_root=args.source_root,
        )
        print(f"Backup:   {created.backup_dir}")
    if args.validate_upgrade_migration:
        result = service.validate_migration(
            source_root=args.source_root,
            source_version=args.source_version or None,
        )
        print(f"Migration: {result.get('status')} — {result.get('detail')}")
        if result.get("status") != "ready":
            return 1
    if args.verify_backup:
        ok, detail = service.verify_backup(args.verify_backup)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        if not ok:
            return 1
    if args.restore_backup:
        result = service.restore_backup(
            args.restore_backup,
            dry_run=not args.acknowledge_restore,
            acknowledge=args.acknowledge_restore,
        )
        print(f"Restore: {result.get('status')} — {result.get('detail')}")
        if not args.acknowledge_restore:
            print("Dry run only. Re-run with --acknowledge-restore after closing the GUI.")
    return 0



def _handle_crash_recovery_command(argv: list[str]) -> int | None:
    flags = {
        "--crash-recovery-snapshot",
        "--export-crash-diagnostics",
        "--acknowledge-crash",
        "--verify-crash-bundle",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.crash_recovery_service import CrashRecoveryService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking crash recovery and privacy-safe diagnostics tool",
    )
    parser.add_argument("--crash-recovery-snapshot", action="store_true")
    parser.add_argument("--export-crash-diagnostics", action="store_true")
    parser.add_argument("--acknowledge-crash", default="")
    parser.add_argument("--verify-crash-bundle", type=Path)
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = CrashRecoveryService(runtime)
    if args.crash_recovery_snapshot:
        snapshot = service.snapshot()
        print(f"Status:       {snapshot.status}")
        print(f"Reports:      {snapshot.crash_count}")
        print(f"Unreviewed:   {snapshot.unacknowledged_count}")
        print(f"Integrity:    {snapshot.integrity_failure_count} failure(s)")
        print(f"Database:     {snapshot.database_status}")
        print(f"Safe command: {service.safe_mode_command()}")
    if args.acknowledge_crash:
        record = service.acknowledge(args.acknowledge_crash)
        print(f"Acknowledged: {record.report_id}")
    if args.export_crash_diagnostics:
        receipt = service.export_bundle()
        print(f"Bundle:       {receipt.path}")
        print(f"SHA-256:      {receipt.sha256}")
        print(f"Status:       {receipt.status}")
    if args.verify_crash_bundle:
        ok, detail = service.verify_bundle(args.verify_crash_bundle)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        if not ok:
            return 1
    return 0

def main() -> int:
    crash_service = None
    try:
        recovery_exit = _handle_recovery_command(sys.argv)
        if recovery_exit is not None:
            return recovery_exit
        crash_exit = _handle_crash_recovery_command(sys.argv)
        if crash_exit is not None:
            return crash_exit

        from PySide6.QtWidgets import QApplication
        from app.bootstrap import create_application_context
        from app.container import create_service_container
        from app.gui.main import MainWindow
        from app.services.crash_recovery_service import CrashRecoveryService

        runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
        runtime.ensure_directories()
        crash_service = CrashRecoveryService(runtime)
        safe_mode = crash_service.safe_mode_requested(sys.argv)
        crash_service.begin_session(argv=sys.argv, safe_mode=safe_mode)
        crash_service.install_handlers()
        qt_argv = [argument for argument in sys.argv if argument != "--safe-mode"]
        qt_app = QApplication(qt_argv)
        crash_service.install_qt_message_handler()
        container = create_service_container(runtime, crash_recovery_service=crash_service)
        window = MainWindow(create_application_context(container))
        window.show()
        smoke_ms = int(os.environ.get("S_TALKING_SMOKE_EXIT_MS") or "0")
        if smoke_ms > 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(smoke_ms, window.close)
            QTimer.singleShot(smoke_ms + 250, qt_app.quit)
        return int(qt_app.exec())
    except Exception as exc:
        report_path = None
        if crash_service is not None:
            try:
                record = crash_service.capture_exception(
                    type(exc),
                    exc,
                    exc.__traceback__,
                    source="startup",
                    severity="fatal",
                )
                report_path = record.report_path if record else None
            except Exception:
                report_path = None
        if report_path is None:
            _write_crash(type(exc), exc, exc.__traceback__)
            report_path = _crash_log_path()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            qt_app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "S Talking could not start",
                "S Talking could not start.\n\n"
                f"Privacy-safe crash evidence was written to:\n{report_path}\n\n"
                "Start with --safe-mode to skip automatic project and update restoration.",
            )
            qt_app.quit()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
