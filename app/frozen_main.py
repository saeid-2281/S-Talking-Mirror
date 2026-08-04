from __future__ import annotations

import os
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


def _write_crash(exc_type: type[BaseException], exc: BaseException, tb) -> None:
    path = _crash_log_path()
    text = (
        "S Talking startup crash\n\n"
        + _runtime_diagnostics()
        + "\n\nTraceback:\n"
        + "".join(traceback.format_exception(exc_type, exc, tb))
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


def main() -> int:
    sys.excepthook = excepthook
    try:
        recovery_exit = _handle_recovery_command(sys.argv)
        if recovery_exit is not None:
            return recovery_exit
        from PySide6.QtWidgets import QApplication, QMessageBox
        from app.bootstrap import create_application_context
        from app.container import create_service_container
        from app.gui.main import MainWindow

        runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
        runtime.ensure_directories()
        qt_app = QApplication(sys.argv)
        window = MainWindow(create_application_context(create_service_container(runtime)))
        window.show()
        smoke_ms = int(os.environ.get("S_TALKING_SMOKE_EXIT_MS") or "0")
        if smoke_ms > 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(smoke_ms, window.close)
            QTimer.singleShot(smoke_ms + 250, qt_app.quit)
        return int(qt_app.exec())
    except Exception as exc:
        _write_crash(type(exc), exc, exc.__traceback__)
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            qt_app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "S Talking could not start",
                f"S Talking could not start.\n\nA crash log was written to:\n{_crash_log_path()}",
            )
            qt_app.quit()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
