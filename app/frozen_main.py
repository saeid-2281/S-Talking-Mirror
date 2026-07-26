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


def main() -> int:
    sys.excepthook = excepthook
    try:
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
