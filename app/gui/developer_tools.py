from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QObject, QProcess, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

import app
from app.bootstrap import ApplicationContext
from app.models import DevCheckResult


class DevCheckRunner(QObject):
    output = Signal(str)
    finished = Signal(object)

    def __init__(self, repo_root: Path, artifact_root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.repo_root = repo_root
        self.artifact_root = artifact_root
        self.process: QProcess | None = None
        self.started_at = ""
        self.started_seconds = 0.0
        self.stdout = ""
        self.stderr = ""
        self.artifact_dir: Path | None = None

    @property
    def is_active(self) -> bool:
        return self.process is not None and self.process.state() != QProcess.NotRunning

    def start(self, script: Path) -> bool:
        if self.is_active:
            return False
        if not script.exists():
            raise FileNotFoundError(f"Check script not found: {script}")
        run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.artifact_dir = self.artifact_root / run_id
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.started_at = datetime.now().isoformat()
        self.started_seconds = perf_counter()
        self.stdout = ""
        self.stderr = ""
        self.process = QProcess(self)
        self.process.setProgram("powershell")
        self.process.setArguments(["-ExecutionPolicy", "Bypass", "-File", str(script)])
        self.process.setWorkingDirectory(str(self.repo_root))
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._finished)
        self.process.start()
        return True

    def cancel(self) -> None:
        if self.is_active and self.process:
            self.process.terminate()
            if not self.process.waitForFinished(1500):
                self.process.kill()

    def _read_stdout(self) -> None:
        if not self.process:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self.stdout += text
        self.output.emit(text)

    def _read_stderr(self) -> None:
        if not self.process:
            return
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self.stderr += text
        self.output.emit(text)

    def _finished(self, exit_code: int, _status: QProcess.ExitStatus) -> None:
        finished_at = datetime.now().isoformat()
        artifact_dir = self.artifact_dir or self.artifact_root / "unknown"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = artifact_dir / "stdout.txt"
        stderr_path = artifact_dir / "stderr.txt"
        stdout_path.write_text(self.stdout, encoding="utf-8")
        stderr_path.write_text(self.stderr, encoding="utf-8")
        stage = self._stage(exit_code)
        result = DevCheckResult(
            started_at=self.started_at,
            finished_at=finished_at,
            elapsed_seconds=perf_counter() - self.started_seconds,
            success=exit_code == 0,
            exit_code=exit_code,
            stage=stage,
            summary="All checks passed" if exit_code == 0 else f"Checks failed at {stage}",
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            artifact_directory=artifact_dir,
        )
        (artifact_dir / "result.json").write_text(
            json.dumps(
                {
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                    "elapsed_seconds": result.elapsed_seconds,
                    "success": result.success,
                    "exit_code": result.exit_code,
                    "stage": result.stage,
                    "summary": result.summary,
                    "stdout_path": str(result.stdout_path),
                    "stderr_path": str(result.stderr_path),
                    "artifact_directory": str(result.artifact_directory),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        latest = self.artifact_root / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        (latest / "runner-result.json").write_text((artifact_dir / "result.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.finished.emit(result)

    def _stage(self, exit_code: int) -> str:
        if exit_code == 0:
            return "complete"
        combined = f"{self.stdout}\n{self.stderr}"
        for marker in ["FAILED: compileall", "FAILED: pytest", "FAILED: ruff"]:
            if marker in combined:
                return marker.removeprefix("FAILED: ")
        return "unknown"


class DevCheckDialog(QDialog):
    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Run all checks")
        self.setModal(False)
        self.resize(760, 520)
        self.runner = DevCheckRunner(
            context.container.runtime.app_root,
            context.container.runtime.artifacts_dir / "dev-check",
            self,
        )
        root = QVBoxLayout(self)
        self.status = QLabel("Ready")
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        root.addWidget(self.status)
        root.addWidget(self.output, 1)
        row = QHBoxLayout()
        self.run_button = QPushButton("Run all checks")
        self.cancel_button = QPushButton("Cancel checks")
        self.open_button = QPushButton("Open artifact folder")
        self.export_button = QPushButton("Export diagnostics")
        self.copy_button = QPushButton("Copy output")
        self.cancel_button.setEnabled(False)
        for button, callback in [
            (self.run_button, self.run),
            (self.cancel_button, self.cancel),
            (self.open_button, self.open_latest),
            (self.export_button, self.export_diagnostics),
            (self.copy_button, self.copy_output),
        ]:
            button.clicked.connect(callback)
            row.addWidget(button)
        root.addLayout(row)
        self.runner.output.connect(self.output.insertPlainText)
        self.runner.finished.connect(self.finished_result)

    def run(self) -> bool:
        script = self.context.container.runtime.app_root / "scripts" / "dev-check.ps1"
        if not self.runner.start(script):
            self.status.setText("A check is already running.")
            return False
        self.status.setText("Running checks...")
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        return True

    def cancel(self) -> None:
        self.runner.cancel()
        self.status.setText("Cancelling...")

    def finished_result(self, result: DevCheckResult) -> None:
        self.status.setText(result.summary)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def open_latest(self) -> None:
        path = self.context.container.runtime.artifacts_dir / "dev-check" / "latest"
        self.context.desktop_service.open_path(path)

    def export_diagnostics(self) -> None:
        bundle = self.context.diagnostics_service.export_bundle(
            project=self.context.project_controller.current_project,
            dashboard=None,
            queue_state={
                "active": self.context.generation_controller.is_active,
                "paused": self.context.generation_controller.is_paused,
            },
        )
        self.context.desktop_service.open_path(bundle.parent)

    def copy_output(self) -> None:
        self.context.desktop_service.copy_to_clipboard(self.output.toPlainText())

    def closeEvent(self, event) -> None:
        self.runner.cancel()
        super().closeEvent(event)


class RuntimeInformationDialog(QDialog):
    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Runtime information")
        self.setModal(False)
        root = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(self._text())
        root.addWidget(self.text)
        row = QHBoxLayout()
        for label, callback in [
            ("Copy all", lambda: context.desktop_service.copy_to_clipboard(self.text.toPlainText())),
            ("Open repository", lambda: context.desktop_service.open_path(context.container.runtime.app_root)),
            ("Open data folder", lambda: context.desktop_service.open_path(context.container.runtime.data_dir)),
            ("Close", self.close),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        root.addLayout(row)

    def _text(self) -> str:
        runtime = self.context.container.runtime
        env = self.context.diagnostics_service.environment()
        values = {
            "application_version": app.__version__,
            "repository_root": runtime.app_root,
            "data_directory": runtime.data_dir,
            "reports_directory": runtime.reports_dir,
            "logs_directory": runtime.log_dir,
            "diagnostics_directory": runtime.artifacts_dir / "diagnostics",
            "database_path": runtime.database_path,
            "settings_path": runtime.settings_path,
            "current_branch": self.context.git_service.current_branch(),
            "python_executable": env["executable_path"],
            "python_version": env["python_version"],
            "qt_version": env["qt_version"],
            "pyside_version": env["pyside_version"],
        }
        return "\n".join(f"{key}: {value}" for key, value in values.items())


class DeveloperTools:
    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        self.parent = parent
        self.context = context
        self.check_dialog: DevCheckDialog | None = None
        self.tools_dialog: DevelopmentAssistantDialog | None = None
        self.runtime_dialog: RuntimeInformationDialog | None = None
        self.actions: dict[str, object] = {}

    def populate_menu(self, menu: QMenu) -> dict[str, object]:
        specs = [
            ("Development Assistant", self.show_assistant),
            ("Run all checks", self.show_checks),
            ("Export diagnostics", self.export_diagnostics),
            ("Open diagnostics folder", lambda: self.open_path(self.context.container.runtime.artifacts_dir / "diagnostics")),
            ("Open latest report", self.open_latest_report),
            ("Open reports folder", lambda: self.open_path(self.context.container.runtime.reports_dir)),
            ("Open logs folder", lambda: self.open_path(self.context.container.runtime.log_dir)),
            ("Open repository folder", lambda: self.open_path(self.context.container.runtime.app_root)),
            ("Open repository in VS Code", self.open_vscode),
            ("Show runtime information", self.show_runtime_information),
            ("Spinbox visual test", self.spinbox_visual_test),
            ("Command Palette", self.open_command_palette),
        ]
        for label, callback in specs:
            action = menu.addAction(label)
            action.triggered.connect(callback)
            self.actions[label] = action
        self.refresh_action_state()
        return self.actions

    def refresh_action_state(self) -> None:
        script = self.context.container.runtime.app_root / "scripts" / "dev-check.ps1"
        action = self.actions.get("Run all checks")
        if action:
            action.setEnabled(script.exists())
            action.setToolTip("" if script.exists() else "scripts/dev-check.ps1 is missing.")
        latest = self.context.report_service.latest_report_dir()
        report_action = self.actions.get("Open latest report")
        if report_action:
            report_action.setEnabled(bool(latest))
            report_action.setToolTip("" if latest else "No generation report has been created yet.")

    def show_checks(self) -> None:
        self.check_dialog = self.check_dialog or DevCheckDialog(self.parent, self.context)
        self.check_dialog.show()
        self.check_dialog.raise_()
        self.check_dialog.run()

    def show_assistant(self) -> None:
        self.tools_dialog = self.tools_dialog or DevelopmentAssistantDialog(self.parent, self.context, self)
        self.tools_dialog.refresh()
        self.tools_dialog.show()
        self.tools_dialog.raise_()

    def export_diagnostics(self) -> None:
        bundle = self.context.diagnostics_service.export_bundle(
            project=self.context.project_controller.current_project,
            dashboard=None,
            queue_state={
                "active": self.context.generation_controller.is_active,
                "paused": self.context.generation_controller.is_paused,
            },
        )
        self.context.desktop_service.copy_to_clipboard(str(bundle))
        self.open_path(bundle.parent)

    def open_latest_report(self) -> None:
        latest = self.context.report_service.latest_report_dir()
        if latest:
            self.context.desktop_service.open_file(latest / "report.html")

    def open_vscode(self) -> None:
        self.context.desktop_service.open_in_vscode(self.context.container.runtime.app_root)

    def show_runtime_information(self) -> None:
        self.runtime_dialog = RuntimeInformationDialog(self.parent, self.context)
        self.runtime_dialog.show()

    def spinbox_visual_test(self) -> None:
        script = self.context.container.runtime.app_root / "scripts" / "spinbox-demo.py"
        python = self.context.container.runtime.app_root / ".venv" / "Scripts" / "python.exe"
        QProcess.startDetached(str(python), [str(script)])

    def open_command_palette(self) -> None:
        parent = self.parent
        if hasattr(parent, "open_command_palette"):
            parent.open_command_palette()

    def open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.context.desktop_service.open_path(path)

    def close(self) -> None:
        if self.check_dialog:
            self.check_dialog.close()
        if self.tools_dialog:
            self.tools_dialog.close()
        if self.runtime_dialog:
            self.runtime_dialog.close()


class DevelopmentAssistantDialog(QDialog):
    def __init__(self, parent: QWidget, context: ApplicationContext, tools: DeveloperTools) -> None:
        super().__init__(parent)
        self.context = context
        self.tools = tools
        self.setWindowTitle("Development Assistant")
        self.setModal(False)
        self.resize(760, 420)
        root = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.summary)
        row = QHBoxLayout()
        for label, callback in [
            ("Run all checks", tools.show_checks),
            ("Cancel checks", self.cancel_checks),
            ("Export diagnostics", tools.export_diagnostics),
            ("Open latest check", lambda: tools.open_path(context.container.runtime.artifacts_dir / "dev-check" / "latest")),
            ("Open latest report", tools.open_latest_report),
            ("Open logs", lambda: tools.open_path(context.container.runtime.log_dir)),
            ("Open repository", lambda: tools.open_path(context.container.runtime.app_root)),
            ("Open in VS Code", tools.open_vscode),
            ("Copy diagnostics path", self.copy_diagnostics_path),
            ("Close", self.close),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        root.addLayout(row)

    def refresh(self) -> None:
        git = self.context.git_service.status()
        latest_check = self.context.container.runtime.artifacts_dir / "dev-check" / "latest"
        latest_report = self.context.report_service.latest_report_dir()
        latest_diag = self.context.diagnostics_service.latest_bundle
        env = self.context.diagnostics_service.environment()
        self.summary.setText(
            "\n".join(
                [
                    f"Application version: {app.__version__}",
                    f"Python version: {env['python_version'].split()[0]}",
                    f"Qt/PySide version: {env['qt_version']} / {env['pyside_version']}",
                    f"Current branch: {git.branch}",
                    f"Working tree state: {'clean' if git.clean else 'dirty'}",
                    f"Latest check result: {latest_check if latest_check.exists() else 'No check yet'}",
                    f"Latest report path: {latest_report or 'No report yet'}",
                    f"Latest diagnostics path: {latest_diag or 'No diagnostics yet'}",
                ]
            )
        )

    def cancel_checks(self) -> None:
        if self.tools.check_dialog:
            self.tools.check_dialog.cancel()

    def copy_diagnostics_path(self) -> None:
        latest = self.context.diagnostics_service.latest_bundle
        self.context.desktop_service.copy_to_clipboard(str(latest or ""))
