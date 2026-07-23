from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

from app.bootstrap import ApplicationContext


class DeveloperTools:
    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        self.parent = parent
        self.context = context
        self.process: QProcess | None = None

    def populate_menu(self, menu: QMenu) -> None:
        actions = [
            ("Run self-check", self.run_self_check),
            ("Export latest development check", self.export_latest_dev_check),
            ("Export diagnostics", self.export_diagnostics),
            ("Open logs", lambda: self.open_path(self.context.container.runtime.log_dir)),
            ("Open reports", lambda: self.open_path(self.context.container.runtime.reports_dir)),
            ("Open data folder", lambda: self.open_path(self.context.container.runtime.data_dir)),
            ("Show runtime paths", self.show_runtime_paths),
            ("Spinbox visual test", self.spinbox_visual_test),
            ("Prepare Commit", self.prepare_commit),
        ]
        for label, callback in actions:
            action = menu.addAction(label)
            action.triggered.connect(callback)

    def run_self_check(self) -> None:
        script = self.context.container.runtime.app_root / "scripts" / "dev-check.ps1"
        self.process = QProcess(self.parent)
        self.process.setProgram("powershell")
        self.process.setArguments(["-ExecutionPolicy", "Bypass", "-File", str(script)])
        self.process.finished.connect(lambda code, _status: self._self_check_finished(code))
        self.process.start()
        QMessageBox.information(self.parent, "Self-check", "Self-check started. Results will be saved to artifacts.")

    def export_latest_dev_check(self) -> None:
        latest = self.context.container.runtime.artifacts_dir / "dev-check" / "latest"
        self.open_path(latest)

    def export_diagnostics(self) -> None:
        bundle = self.context.report_service.export_diagnostics_bundle()
        self.open_path(bundle.parent)
        QApplication.clipboard().setText(str(bundle))
        QMessageBox.information(self.parent, "Diagnostics exported", f"Created:\n{bundle}")

    def show_runtime_paths(self) -> None:
        runtime = self.context.container.runtime
        lines = [f"{name}: {value}" for name, value in runtime.__dict__.items()]
        QMessageBox.information(self.parent, "Runtime paths", "\n".join(lines))

    def spinbox_visual_test(self) -> None:
        script = self.context.container.runtime.app_root / "scripts" / "spinbox-demo.py"
        subprocess.Popen([str(self.context.container.runtime.app_root / ".venv" / "Scripts" / "python.exe"), str(script)])

    def prepare_commit(self) -> None:
        script = self.context.container.runtime.app_root / "scripts" / "prepare-commit.ps1"
        self.process = QProcess(self.parent)
        self.process.setProgram("powershell")
        self.process.setArguments(["-ExecutionPolicy", "Bypass", "-File", str(script)])
        self.process.finished.connect(lambda _code, _status: self.open_path(self.context.container.runtime.artifacts_dir))
        self.process.start()
        QMessageBox.information(self.parent, "Prepare Commit", "Dry-run commit preparation started.")

    def open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True) if path.suffix == "" else path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _self_check_finished(self, code: int) -> None:
        latest = self.context.container.runtime.artifacts_dir / "dev-check" / "latest"
        self.open_path(latest)
        QMessageBox.information(self.parent, "Self-check finished", f"Exit code: {code}\n{latest}")
