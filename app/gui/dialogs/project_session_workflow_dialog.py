from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.project_session_workflow import ProjectContinuationSummary, ProjectRunSummary
from app.services.project_session_workflow_service import ProjectSessionWorkflowService


class ProjectSessionWorkflowDialog(QDialog):
    CONTINUE_SESSION = "continue_session"
    CONTINUE_PROJECT = "continue_project"
    OPEN_AUDIO = "open_audio"
    OPEN_RUN_OUTPUT = "open_run_output"
    OPEN_REPORT = "open_report"

    def __init__(self, service: ProjectSessionWorkflowService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.action: str | None = None
        self.selected_project: ProjectContinuationSummary | None = None
        self.selected_run: ProjectRunSummary | None = None
        self.selected_path: str | None = None
        self.setWindowTitle("Project Continuity")
        self.resize(920, 620)

        root = QVBoxLayout(self)
        title = QLabel("Continue where you left off")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        self.session_label = QLabel()
        self.session_label.setWordWrap(True)
        root.addWidget(self.session_label)
        session_row = QHBoxLayout()
        self.continue_session_button = QPushButton("Continue last session")
        self.continue_session_button.clicked.connect(self.continue_session)
        session_row.addWidget(self.continue_session_button)
        session_row.addStretch(1)
        root.addLayout(session_row)

        root.addWidget(QLabel("Recent projects"))
        self.projects_table = QTableWidget(0, 5)
        self.projects_table.setObjectName("projectContinuityProjects")
        self.projects_table.setHorizontalHeaderLabels(["Project", "Queue", "Failed", "Latest run", "Last opened"])
        self.projects_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.projects_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.projects_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.projects_table.itemSelectionChanged.connect(self.project_selection_changed)
        self.projects_table.itemDoubleClicked.connect(lambda _item: self.continue_project())
        root.addWidget(self.projects_table, 2)

        project_actions = QHBoxLayout()
        self.continue_project_button = QPushButton("Continue selected project")
        self.continue_project_button.clicked.connect(self.continue_project)
        self.open_audio_button = QPushButton("Open latest audio")
        self.open_audio_button.clicked.connect(self.open_audio)
        project_actions.addWidget(self.continue_project_button)
        project_actions.addWidget(self.open_audio_button)
        project_actions.addStretch(1)
        root.addLayout(project_actions)

        root.addWidget(QLabel("Recent runs for selected project"))
        self.runs_table = QTableWidget(0, 6)
        self.runs_table.setObjectName("projectContinuityRuns")
        self.runs_table.setHorizontalHeaderLabels(["Started", "Result", "Completed", "Failed", "Provider", "Duration"])
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.runs_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.runs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.runs_table.itemSelectionChanged.connect(self.run_selection_changed)
        root.addWidget(self.runs_table, 2)

        run_actions = QHBoxLayout()
        self.open_run_output_button = QPushButton("Open run output")
        self.open_run_output_button.clicked.connect(self.open_run_output)
        self.open_report_button = QPushButton("Open report")
        self.open_report_button.clicked.connect(self.open_report)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        run_actions.addWidget(self.open_run_output_button)
        run_actions.addWidget(self.open_report_button)
        run_actions.addStretch(1)
        run_actions.addWidget(close_button)
        root.addLayout(run_actions)

        self.refresh()

    def refresh(self) -> None:
        snapshot = self.service.snapshot(limit=12)
        session = snapshot.session
        if session.can_continue:
            self.session_label.setText(
                f"Last session: {session.project_name or Path(session.project_path or '').stem} · "
                f"filter {session.queue_filter} · selected row "
                f"{session.selected_row if session.selected_row is not None else '—'}"
            )
        elif session.project_path:
            self.session_label.setText(f"Last session project is unavailable: {session.project_path}")
        else:
            self.session_label.setText("No saved project session is available yet.")
        self.continue_session_button.setEnabled(session.can_continue)
        self._session = session
        self._projects = list(snapshot.projects)
        self.projects_table.setRowCount(len(self._projects))
        for row, project in enumerate(self._projects):
            latest = project.latest_run.result if project.latest_run else "—"
            values = [
                project.name + ("" if project.project_file_exists else " · missing"),
                project.queue_summary,
                str(project.failed_jobs),
                latest,
                project.last_opened_at,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, project.project_id)
                self.projects_table.setItem(row, column, item)
        if self._projects:
            self.projects_table.selectRow(0)
        else:
            self.project_selection_changed()

    def project_selection_changed(self) -> None:
        rows = self.projects_table.selectionModel().selectedRows() if self.projects_table.selectionModel() else []
        self.selected_project = self._projects[rows[0].row()] if rows else None
        project = self.selected_project
        self.continue_project_button.setEnabled(bool(project and project.can_continue))
        self.open_audio_button.setEnabled(bool(project and project.latest_audio_path and Path(project.latest_audio_path).is_file()))
        self._runs = list(self.service.recent_runs(project.project_id, limit=12)) if project else []
        self.runs_table.setRowCount(len(self._runs))
        for row, run in enumerate(self._runs):
            values = [
                run.started_at,
                run.result,
                f"{run.completed_jobs}/{run.total_jobs}",
                str(run.failed_jobs),
                run.provider,
                self._duration(run.elapsed_seconds),
            ]
            for column, value in enumerate(values):
                self.runs_table.setItem(row, column, QTableWidgetItem(value))
        if self._runs:
            self.runs_table.selectRow(0)
        else:
            self.run_selection_changed()

    def run_selection_changed(self) -> None:
        rows = self.runs_table.selectionModel().selectedRows() if self.runs_table.selectionModel() else []
        self.selected_run = self._runs[rows[0].row()] if rows else None
        run = self.selected_run
        self.open_run_output_button.setEnabled(bool(run and run.output_path and Path(run.output_path).exists()))
        self.open_report_button.setEnabled(bool(run and run.report_path and Path(run.report_path).exists()))

    def continue_session(self) -> None:
        if not self._session.can_continue:
            return
        self.action = self.CONTINUE_SESSION
        self.selected_path = self._session.project_path
        self.accept()

    def continue_project(self) -> None:
        if not self.selected_project or not self.selected_project.can_continue:
            return
        self.action = self.CONTINUE_PROJECT
        self.selected_path = self.selected_project.project_file
        self.accept()

    def open_audio(self) -> None:
        if not self.selected_project or not self.selected_project.latest_audio_path:
            return
        self.action = self.OPEN_AUDIO
        self.selected_path = self.selected_project.latest_audio_path
        self.accept()

    def open_run_output(self) -> None:
        if not self.selected_run or not self.selected_run.output_path:
            return
        self.action = self.OPEN_RUN_OUTPUT
        self.selected_path = self.selected_run.output_path
        self.accept()

    def open_report(self) -> None:
        if not self.selected_run or not self.selected_run.report_path:
            return
        self.action = self.OPEN_REPORT
        self.selected_path = self.selected_run.report_path
        self.accept()

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}h {minutes:02d}m"
        return f"{minutes:d}m {seconds:02d}s"
