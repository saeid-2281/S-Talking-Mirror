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
from app.gui.health_center import HealthCenterDialog
from app.gui.task_center import TaskCenterDialog
from app.models import DevCheckResult
from app.release import build_metadata


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
        result = self._read_authoritative_result(exit_code)
        self.finished.emit(result)

    def _read_authoritative_result(self, exit_code: int) -> DevCheckResult:
        latest = self.artifact_root / "latest"
        result_path = latest / "result.json"
        if not result_path.exists():
            return self._unknown_result(exit_code, "Check status unknown: latest/result.json is missing.")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._unknown_result(exit_code, "Check status unknown: latest/result.json is malformed.")
        return DevCheckResult(
            started_at=str(payload.get("started_at") or self.started_at),
            finished_at=str(payload.get("finished_at") or datetime.now().isoformat()),
            elapsed_seconds=float(payload.get("elapsed_seconds") or max(0, perf_counter() - self.started_seconds)),
            success=bool(payload.get("success", False)),
            exit_code=int(payload.get("exit_code") if payload.get("exit_code") is not None else exit_code),
            stage=str(payload.get("stage") or "unknown"),
            summary=str(payload.get("summary") or "Check completed with no summary."),
            stdout_path=latest / "stdout.txt",
            stderr_path=latest / "stderr.txt",
            artifact_directory=Path(payload.get("artifact_directory") or latest),
        )

    def _unknown_result(self, exit_code: int, summary: str) -> DevCheckResult:
        latest = self.artifact_root / "latest"
        return DevCheckResult(
            started_at=self.started_at,
            finished_at=datetime.now().isoformat(),
            elapsed_seconds=max(0, perf_counter() - self.started_seconds),
            success=False,
            exit_code=exit_code,
            stage="unknown",
            summary=summary,
            stdout_path=latest / "stdout.txt",
            stderr_path=latest / "stderr.txt",
            artifact_directory=latest,
        )


class ReleaseCheckRunner(DevCheckRunner):
    def _read_authoritative_result(self, exit_code: int) -> DevCheckResult:
        latest = self.artifact_root / "latest"
        result_path = latest / "result.json"
        if not result_path.exists():
            return self._unknown_result(exit_code, "Release check status unknown: latest/result.json is missing.")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._unknown_result(exit_code, "Release check status unknown: latest/result.json is malformed.")
        return DevCheckResult(
            started_at=str(payload.get("started_at") or self.started_at),
            finished_at=str(payload.get("finished_at") or datetime.now().isoformat()),
            elapsed_seconds=float(payload.get("elapsed_seconds") or max(0, perf_counter() - self.started_seconds)),
            success=bool(payload.get("success", False)),
            exit_code=int(payload.get("exit_code") if payload.get("exit_code") is not None else exit_code),
            stage=str(payload.get("stage") or "unknown"),
            summary=str(payload.get("summary") or "Release check completed with no summary."),
            stdout_path=latest / "stdout.txt",
            stderr_path=latest / "stderr.txt",
            artifact_directory=Path(payload.get("artifact_directory") or latest),
        )


class ReleaseReadinessDialog(QDialog):
    def __init__(self, parent: QWidget, context: ApplicationContext, tools: "DeveloperTools") -> None:
        super().__init__(parent)
        self.context = context
        self.tools = tools
        self.setWindowTitle("Release readiness")
        self.setModal(False)
        self.resize(820, 560)
        self.runner = ReleaseCheckRunner(
            context.container.runtime.app_root,
            context.container.runtime.artifacts_dir / "release-check",
            self,
        )
        root = QVBoxLayout(self)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        root.addWidget(self.summary, 1)
        row = QHBoxLayout()
        for label, callback in [
            ("Run release checks", self.run),
            ("Export release diagnostics", self.export_release_diagnostics),
            ("Copy release summary", self.copy_summary),
            ("Open artifact folder", self.open_artifact_folder),
            ("Close", self.close),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
            if label == "Run release checks":
                self.run_button = button
        root.addLayout(row)
        self.runner.output.connect(self.summary.insertPlainText)
        self.runner.finished.connect(self.finished_result)
        self.refresh()

    def current_state(self):
        parent = self.parent()
        csv_path = Path(parent.csv.text()) if hasattr(parent, "csv") and parent.csv.text().strip() else None
        output_dir = Path(parent.out.text()) if hasattr(parent, "out") and parent.out.text().strip() else None
        settings = parent.settings() if hasattr(parent, "settings") else None
        return self.context.release_readiness_service.snapshot(
            csv_path=csv_path,
            jobs=list(self.context.generation_controller.jobs),
            settings=settings,
            output_dir=output_dir,
            preflight_status=getattr(self.context.preflight_service.latest, "status", None),
        )

    def refresh(self) -> None:
        state = self.current_state()
        self.summary.setPlainText(self.context.release_readiness_service.copy_summary_text(state))

    def run(self) -> None:
        script = self.context.container.runtime.app_root / "scripts" / "release-check.ps1"
        self.summary.clear()
        if self.runner.start(script):
            self.run_button.setEnabled(False)

    def finished_result(self, result: DevCheckResult) -> None:
        self.run_button.setEnabled(True)
        self.context.health_service.invalidate()
        self.summary.appendPlainText("\n" + result.summary)
        self.refresh()

    def export_release_diagnostics(self) -> None:
        path = self.context.release_readiness_service.export(self.current_state())
        self.context.desktop_service.copy_to_clipboard(str(path))
        self.context.desktop_service.open_path(path.parent)

    def copy_summary(self) -> None:
        self.context.desktop_service.copy_to_clipboard(self.context.release_readiness_service.copy_summary_text(self.current_state()))

    def open_artifact_folder(self) -> None:
        self.context.desktop_service.open_path(self.context.container.runtime.artifacts_dir / "release-check" / "latest")


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
        self.copy_summary_button = QPushButton("Copy summary")
        self.copy_chatgpt_button = QPushButton("Copy for ChatGPT")
        self.copy_button = QPushButton("Copy detailed output")
        self.cancel_button.setEnabled(False)
        for button, callback in [
            (self.run_button, self.run),
            (self.cancel_button, self.cancel),
            (self.open_button, self.open_latest),
            (self.export_button, self.export_diagnostics),
            (self.copy_summary_button, self.copy_summary),
            (self.copy_chatgpt_button, self.copy_for_chatgpt),
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
        self.context.health_service.invalidate()
        self.status.setText(result.summary)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        tools = getattr(self.parent(), "developer_tools", None)
        if tools:
            tools.refresh_after_checks()

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
        self.context.health_service.invalidate()
        self.context.desktop_service.open_path(bundle.parent)

    def copy_output(self) -> None:
        self.context.desktop_service.copy_to_clipboard(self.output.toPlainText())

    def copy_summary(self) -> None:
        state = self.context.health_service.snapshot(
            project=self.context.project_controller.current_project,
            dashboard=None,
        )
        self.context.desktop_service.copy_to_clipboard(
            self.context.health_service.compact_summary(state)
        )

    def copy_for_chatgpt(self) -> None:
        state = self.context.health_service.snapshot(
            project=self.context.project_controller.current_project,
            dashboard=None,
        )
        self.context.desktop_service.copy_to_clipboard(
            self.context.health_service.markdown_summary(state)
        )

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
            "release_channel": getattr(app, "__release_channel__", "dev"),
            "build_metadata": build_metadata(),
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
        self.health_dialog: HealthCenterDialog | None = None
        self.task_dialog: TaskCenterDialog | None = None
        self.release_dialog: ReleaseReadinessDialog | None = None
        self.actions: dict[str, object] = {}

    def populate_menu(self, menu: QMenu) -> dict[str, object]:
        specs = [
            ("Health Center", self.show_health_center),
            ("Task Center", self.show_task_center),
            ("Development Assistant", self.show_assistant),
            ("Release readiness", self.show_release_readiness),
            ("Run all checks", self.show_checks),
            ("Clear saved API key", self.clear_saved_api_key),
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

    def show_health_center(self) -> None:
        self.health_dialog = self.health_dialog or HealthCenterDialog(self.parent, self.context)
        parent = self.parent
        dashboard_method = getattr(parent, "current_dashboard_state", None)
        if callable(dashboard_method):
            self.health_dialog.set_dashboard(dashboard_method())
        else:
            self.health_dialog.refresh()
        self.health_dialog.show()
        self.health_dialog.raise_()

    def show_task_center(self) -> None:
        self.task_dialog = self.task_dialog or TaskCenterDialog(self.parent, self.context)
        self.task_dialog.refresh()
        self.task_dialog.show()
        self.task_dialog.raise_()

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
        self.context.health_service.invalidate()
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
        if self.health_dialog:
            self.health_dialog.close()
        if self.task_dialog:
            self.task_dialog.close()
        if self.release_dialog:
            self.release_dialog.close()

    def refresh_after_checks(self) -> None:
        self.context.health_service.invalidate()
        parent = self.parent
        if hasattr(parent, "update_status_bar"):
            parent.update_status_bar()
        if self.health_dialog and self.health_dialog.isVisible():
            dashboard_method = getattr(parent, "current_dashboard_state", None)
            if callable(dashboard_method):
                self.health_dialog.set_dashboard(dashboard_method())
            else:
                self.health_dialog.refresh()
        if self.tools_dialog and self.tools_dialog.isVisible():
            self.tools_dialog.refresh()

    def show_release_readiness(self) -> None:
        self.release_dialog = self.release_dialog or ReleaseReadinessDialog(self.parent, self.context, self)
        self.release_dialog.refresh()
        self.release_dialog.show()
        self.release_dialog.raise_()

    def clear_saved_api_key(self) -> None:
        parent = self.parent
        if hasattr(parent, "key"):
            parent.key.clear()
        settings = self.context.settings_controller.load_global_settings()
        if settings:
            self.context.settings_controller.save_global_settings(settings.model_copy(update={"api_key": ""}))
        self.context.voice_service.invalidate_provider_cache()


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
            ("Health Center", tools.show_health_center),
            ("Task Center", tools.show_task_center),
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
