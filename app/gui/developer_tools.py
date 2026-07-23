from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

import app
from app.bootstrap import ApplicationContext
from app.services.task_prompt_service import TASK_STATUSES


class DeveloperTools:
    def __init__(self, parent: QWidget, context: ApplicationContext) -> None:
        self.parent = parent
        self.context = context
        self.process: QProcess | None = None
        self.assistant_dialog: DevelopmentAssistantDialog | None = None

    def populate_menu(self, menu: QMenu) -> None:
        assistant = menu.addAction("Development Assistant")
        assistant.triggered.connect(self.show_assistant)
        menu.addSeparator()
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
            ("Push current branch", self.push_current_branch),
        ]
        for label, callback in actions:
            action = menu.addAction(label)
            action.triggered.connect(callback)

    def show_assistant(self) -> None:
        self.assistant_dialog = DevelopmentAssistantDialog(self.parent, self.context, self)
        self.assistant_dialog.show()

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
        bundle = self.context.diagnostics_service.export_bundle(
            project=self.context.project_controller.current_project,
            dashboard=None,
            queue_state={
                "active": self.context.generation_controller.is_active,
                "paused": self.context.generation_controller.is_paused,
            },
        )
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

    def push_current_branch(self) -> None:
        branch = self.context.git_service.current_branch()
        if branch == "main":
            QMessageBox.warning(self.parent, "Push blocked", "Refusing to push main.")
            return
        if QMessageBox.question(self.parent, "Push branch", f"Push {branch} to origin?") != QMessageBox.Yes:
            return
        self.process = QProcess(self.parent)
        self.process.setProgram("git")
        self.process.setArguments(["push", "origin", branch])
        self.process.setWorkingDirectory(str(self.context.container.runtime.app_root))
        self.process.finished.connect(lambda code, _status: QMessageBox.information(self.parent, "Push finished", f"Exit code: {code}"))
        self.process.start()

    def open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True) if path.suffix == "" else path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _self_check_finished(self, code: int) -> None:
        latest = self.context.container.runtime.artifacts_dir / "dev-check" / "latest"
        self.open_path(latest)
        QMessageBox.information(self.parent, "Self-check finished", f"Exit code: {code}\n{latest}")


class DevelopmentAssistantDialog(QDialog):
    def __init__(self, parent: QWidget, context: ApplicationContext, tools: DeveloperTools) -> None:
        super().__init__(parent)
        self.context = context
        self.tools = tools
        self.setWindowTitle("Development Assistant")
        self.setModal(False)
        self.resize(860, 620)
        root = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.summary)
        buttons = QHBoxLayout()
        for label, callback in [
            ("Run all checks", self.tools.run_self_check),
            ("Launch application smoke test", self.launch_smoke_test),
            ("Export diagnostics", self.tools.export_diagnostics),
            ("Open diagnostics folder", lambda: self.tools.open_path(self.context.container.runtime.artifacts_dir / "diagnostics")),
            ("Open latest report", self.open_latest_report),
            ("Open repository folder", lambda: self.tools.open_path(self.context.container.runtime.app_root)),
            ("Open repository in VS Code", self.open_vscode),
            ("Copy current task prompt", self.copy_task_prompt),
            ("Prepare commit", self.tools.prepare_commit),
            ("Push current branch", self.tools.push_current_branch),
            ("Copy PR description", self.copy_pr_description),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        root.addLayout(buttons)
        task_row = QHBoxLayout()
        self.tasks = QListWidget()
        self.task_text = QPlainTextEdit()
        self.status = QComboBox()
        self.status.addItems(TASK_STATUSES)
        status_button = QPushButton("Update status")
        status_button.clicked.connect(self.update_task_status)
        open_button = QPushButton("Open task")
        open_button.clicked.connect(self.open_task)
        task_row.addWidget(self.tasks, 1)
        task_row.addWidget(self.task_text, 2)
        side = QVBoxLayout()
        side.addWidget(self.status)
        side.addWidget(status_button)
        side.addWidget(open_button)
        task_row.addLayout(side)
        root.addLayout(task_row, 1)
        self.tasks.currentRowChanged.connect(self.load_selected_task)
        self.refresh()
        self.load_tasks()

    def refresh(self) -> None:
        git = self.context.git_service.status()
        latest_check = self.context.container.runtime.artifacts_dir / "dev-check" / "latest" / "summary.txt"
        latest_report = self.context.report_service.latest_report_dir()
        latest_diag = self.context.diagnostics_service.latest_bundle
        self.summary.setText(
            "\n".join(
                [
                    f"Branch: {git.branch}",
                    f"Working tree: {'clean' if git.clean else 'dirty'}",
                    f"Latest test result: {latest_check if latest_check.exists() else 'No check yet'}",
                    f"Latest report: {latest_report or 'No report yet'}",
                    f"Latest diagnostics: {latest_diag or 'No diagnostics yet'}",
                    f"Application version: {app.__version__}",
                    f"Python: {self.context.diagnostics_service.environment()['python_version'].split()[0]}",
                    f"Qt: {self.context.diagnostics_service.environment()['qt_version']}",
                ]
            )
        )

    def load_tasks(self) -> None:
        self.tasks.clear()
        for path in self.context.task_prompt_service.list_tasks():
            self.tasks.addItem(path.name)
        if self.tasks.count():
            self.tasks.setCurrentRow(0)

    def selected_task_path(self) -> Path | None:
        item = self.tasks.currentItem()
        return self.context.task_prompt_service.tasks_dir / item.text() if item else None

    def load_selected_task(self, *_args) -> None:
        path = self.selected_task_path()
        if not path:
            return
        task = self.context.task_prompt_service.load(path)
        self.task_text.setPlainText(path.read_text(encoding="utf-8"))
        self.status.setCurrentText(task.status)

    def copy_task_prompt(self) -> None:
        path = self.selected_task_path()
        if path:
            QApplication.clipboard().setText(self.context.task_prompt_service.load(path).codex_prompt)

    def update_task_status(self) -> None:
        path = self.selected_task_path()
        if path:
            self.context.task_prompt_service.update_status(path, self.status.currentText())
            self.load_selected_task()

    def open_task(self) -> None:
        path = self.selected_task_path()
        if path:
            self.tools.open_path(path)

    def open_latest_report(self) -> None:
        path = self.context.report_service.latest_report_dir()
        if path:
            self.tools.open_path(path / "report.html")

    def launch_smoke_test(self) -> None:
        self.tools.process = QProcess(self)
        self.tools.process.setProgram(str(self.context.container.runtime.app_root / ".venv" / "Scripts" / "python.exe"))
        self.tools.process.setArguments(["-m", "pytest", "tests/test_dashboard_reports.py::test_offscreen_app_smoke_creates_dashboard_and_report"])
        self.tools.process.setWorkingDirectory(str(self.context.container.runtime.app_root))
        self.tools.process.finished.connect(lambda code, _status: QMessageBox.information(self, "Smoke test finished", f"Exit code: {code}"))
        self.tools.process.start()

    def open_vscode(self) -> None:
        subprocess.Popen(["code", str(self.context.container.runtime.app_root)])

    def copy_pr_description(self) -> None:
        QApplication.clipboard().setText(self.context.git_service.generate_pr_description())
    def show_assistant(self) -> None:
        dialog = DevelopmentAssistantDialog(self.parent, self.context, self)
        dialog.show()
