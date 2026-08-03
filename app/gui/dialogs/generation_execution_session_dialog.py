from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_execution_session import GenerationExecutionSession
from app.services.generation_execution_session_service import GenerationExecutionSessionService


class GenerationExecutionSessionDialog(QDialog):
    """Searchable run-identity center for real generation execution sessions."""

    def __init__(
        self,
        service: GenerationExecutionSessionService,
        parent: QWidget | None = None,
        *,
        project_name: str = "all-projects",
        export_dir: Path | None = None,
        open_path: Callable[[Path], None] | None = None,
        copy_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = project_name
        self.export_dir = Path(export_dir or service.reports_dir / "execution-sessions")
        self.open_path_callback = open_path
        self.copy_path_callback = copy_path
        self.all_sessions: list[GenerationExecutionSession] = []
        self.filtered_sessions: list[GenerationExecutionSession] = []
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationExecutionSessionDialog")
        self.setWindowTitle("Generation execution sessions")
        self.resize(1220, 760)
        self.setMinimumSize(760, 520)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Generation execution sessions",
            "Trace each real run from launch receipt to queue jobs, outputs and the final report.",
            icon_name="history",
            parent=self,
        )
        root.addWidget(self.workspace)

        filters_section = DialogSection(
            "Find execution sessions",
            "Filter by project and lifecycle state, or search run IDs, receipts, providers, outputs and job filenames.",
        )
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        self.current_project_only = QCheckBox("Current project only")
        has_project = self.project_name not in {"", "all-projects"}
        self.current_project_only.setEnabled(has_project)
        self.current_project_only.setChecked(has_project)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All states", "")
        for label, value in (
            ("Starting", "starting"),
            ("Running", "running"),
            ("Completed", "completed"),
            ("Partial", "partial"),
            ("Failed", "failed"),
            ("Cancelled", "cancelled"),
        ):
            self.status_filter.addItem(label, value)
        self.search = QLineEdit()
        self.search.setObjectName("executionSessionSearch")
        self.search.setPlaceholderText("Search run, receipt, trace, provider, output or filename…")
        self.search.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(action_icon("general.refresh"))
        filters.addWidget(self.current_project_only, 0, 0)
        filters.addWidget(self.status_filter, 0, 1)
        filters.addWidget(self.search, 1, 0, 1, 2)
        filters.addWidget(self.refresh_button, 1, 2)
        filters.setColumnStretch(1, 1)
        filters_section.add_layout(filters)
        self.workspace.add_body_widget(filters_section)

        self.summary_card = DialogStatusCard(
            "No execution sessions loaded",
            "Run metrics update after filters are applied.",
            tone="info",
        )
        self.summary_card.setObjectName("executionSessionSummaryCard")
        self.workspace.add_body_widget(self.summary_card)

        records_section = DialogSection(
            "Run archive",
            "A run ID is created before execution and remains linked to its launch receipt, queue snapshot, outputs and final report.",
        )
        self.table = QTableWidget(0, 11)
        self.table.setObjectName("generationExecutionSessionTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Started",
                "Project",
                "Status",
                "Progress",
                "Provider",
                "Model",
                "Jobs",
                "Failed",
                "Receipt",
                "Integrity",
                "Run ID",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(300)
        self.table.horizontalHeader().setStretchLastSection(True)
        records_section.add_widget(self.table, 1)
        self.workspace.add_body_widget(records_section, 1)

        details_section = DialogSection(
            "Selected run",
            "Inspect lifecycle state, launch identity, queue outcomes and linked artifacts.",
        )
        self.details = QPlainTextEdit()
        self.details.setObjectName("generationExecutionSessionDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(140)
        self.details.setMaximumHeight(210)
        self.details.setPlaceholderText("Select an execution session to inspect it.")
        details_section.add_widget(self.details)
        self.workspace.add_body_widget(details_section)

        actions_section = DialogSection(
            "Run actions",
            "Open linked artifacts or export a secret-free catalog of the filtered sessions.",
        )
        actions = QGridLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_session_button = QPushButton("Open session JSON")
        self.open_receipt_button = QPushButton("Open launch receipt")
        self.open_report_button = QPushButton("Open final report")
        self.open_output_button = QPushButton("Open output folder")
        self.copy_run_id_button = QPushButton("Copy run ID")
        self.copy_session_path_button = QPushButton("Copy session path")
        self.export_button = QPushButton("Export filtered catalog")
        for index, (button, icon_name) in enumerate(
            (
                (self.open_session_button, "report"),
                (self.open_receipt_button, "report"),
                (self.open_report_button, "report"),
                (self.open_output_button, "project.output_folder"),
                (self.copy_run_id_button, "general.copy"),
                (self.copy_session_path_button, "general.copy"),
                (self.export_button, "save"),
            )
        ):
            button.setObjectName("historyToolAction")
            button.setIcon(action_icon(icon_name))
            button.setMinimumHeight(34)
            actions.addWidget(button, index // 3, index % 3)
        for column in range(3):
            actions.setColumnStretch(column, 1)
        actions_section.add_layout(actions)
        self.workspace.add_body_widget(actions_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        close_button = QPushButton("Close")
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(close_button)

        self.refresh_button.clicked.connect(self.refresh)
        self.current_project_only.toggled.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.update_details)
        self.open_session_button.clicked.connect(self.open_session)
        self.open_receipt_button.clicked.connect(self.open_receipt)
        self.open_report_button.clicked.connect(self.open_report)
        self.open_output_button.clicked.connect(self.open_output)
        self.copy_run_id_button.clicked.connect(self.copy_run_id)
        self.copy_session_path_button.clicked.connect(self.copy_session_path)
        self.export_button.clicked.connect(self.export_filtered)
        close_button.clicked.connect(self.close)
        self._update_action_state()

    def refresh(self) -> None:
        self.all_sessions = self.service.list_sessions(limit=1000)
        self.apply_filters()

    def apply_filters(self) -> None:
        project_name = self.project_name if self.current_project_only.isChecked() else None
        status = str(self.status_filter.currentData() or "")
        search = self.search.text().strip()
        records = self.all_sessions
        if project_name:
            records = [item for item in records if item.project_name == project_name]
        if status:
            records = [item for item in records if item.status == status]
        if search:
            key = search.casefold()
            records = [item for item in records if key in self.service._search_text(item)]
        self.filtered_sessions = records
        self._populate()

    def _populate(self) -> None:
        self.table.setRowCount(len(self.filtered_sessions))
        for row, session in enumerate(self.filtered_sessions):
            values = (
                session.started_at.replace("T", " ")[:19],
                session.project_name,
                session.status.title(),
                f"{session.progress_percent:.0f}%",
                session.provider,
                session.model_id,
                str(session.total_jobs),
                str(session.failed_jobs),
                session.launch_receipt_id,
                session.integrity_status.title(),
                session.run_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, session.run_id)
                self.table.setItem(row, column, item)
        summary = self.service.summary(self.filtered_sessions)
        tone = "warning" if summary.integrity_issue_count or summary.failed_count or summary.partial_count else "success"
        self.summary_card.update_status(
            f"{summary.total_count:,} execution session(s) · {summary.running_count:,} active",
            f"Completed {summary.completed_count:,} · Partial {summary.partial_count:,} · "
            f"Failed {summary.failed_count:,} · Cancelled {summary.cancelled_count:,} · "
            f"Jobs {summary.completed_jobs:,} completed / {summary.failed_jobs:,} failed / {summary.skipped_jobs:,} skipped",
            tone=tone,
        )
        self.status_label.setText(f"Showing {len(self.filtered_sessions):,} of {len(self.all_sessions):,} sessions")
        if self.filtered_sessions:
            self.table.selectRow(0)
        else:
            self.details.clear()
            self._update_action_state()

    def selected_session(self) -> GenerationExecutionSession | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered_sessions):
            return None
        return self.filtered_sessions[row]

    def update_details(self) -> None:
        session = self.selected_session()
        if session is None:
            self.details.clear()
            self._update_action_state()
            return
        lines = [
            f"Run ID: {session.run_id}",
            f"Status: {session.status}",
            f"Integrity: {session.integrity_status} — {session.integrity_message}",
            f"Project: {session.project_name} · ID {session.project_id or '—'}",
            f"Launch receipt: {session.launch_receipt_id or '—'}",
            f"Decision trace: {session.decision_trace_id or '—'}",
            f"Approval: {session.guard_approval_id or 'None'}",
            f"Provider / model / voice: {session.provider} / {session.model_id or '—'} / {session.voice_id or '—'}",
            f"Scope / order: {session.generation_scope or '—'} / {session.execution_order or '—'}",
            f"Started: {session.started_at}",
            f"Finished: {session.finished_at or 'In progress'}",
            f"Jobs: {session.total_jobs} total · {session.completed_jobs} completed · {session.failed_jobs} failed · {session.skipped_jobs} skipped",
            f"Characters: {session.processed_characters:,} processed / {session.total_characters:,} total",
            f"Retries: {session.retry_events} · Elapsed: {session.elapsed_seconds:.1f}s",
            f"Output: {session.output_directory}",
            f"Report: {session.report_path or 'Not available'}",
        ]
        self.details.setPlainText("\n".join(lines))
        self._update_action_state()

    def _update_action_state(self) -> None:
        session = self.selected_session()
        has_session = session is not None and session.path.exists()
        has_receipt = bool(session and session.launch_receipt_path and Path(session.launch_receipt_path).exists())
        has_report = bool(session and session.report_path and Path(session.report_path).exists())
        has_output = bool(session and session.output_directory and Path(session.output_directory).exists())
        self.open_session_button.setEnabled(has_session)
        self.open_receipt_button.setEnabled(has_receipt)
        self.open_report_button.setEnabled(has_report)
        self.open_output_button.setEnabled(has_output)
        self.copy_run_id_button.setEnabled(session is not None)
        self.copy_session_path_button.setEnabled(has_session)
        self.export_button.setEnabled(bool(self.filtered_sessions))

    def _open(self, path: Path) -> None:
        if self.open_path_callback is not None:
            self.open_path_callback(path)

    def _copy(self, path: Path) -> None:
        if self.copy_path_callback is not None:
            self.copy_path_callback(path)

    def open_session(self) -> None:
        session = self.selected_session()
        if session:
            self._open(session.path)

    def open_receipt(self) -> None:
        session = self.selected_session()
        if session and session.launch_receipt_path:
            self._open(Path(session.launch_receipt_path))

    def open_report(self) -> None:
        session = self.selected_session()
        if session and session.report_path:
            self._open(Path(session.report_path))

    def open_output(self) -> None:
        session = self.selected_session()
        if session and session.output_directory:
            self._open(Path(session.output_directory))

    def copy_run_id(self) -> None:
        session = self.selected_session()
        if session:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(session.run_id)
            self.status_label.setText("Run ID copied.")

    def copy_session_path(self) -> None:
        session = self.selected_session()
        if session:
            self._copy(session.path)
            self.status_label.setText("Session path copied.")

    def export_filtered(self) -> None:
        json_path, csv_path = self.service.export(
            self.filtered_sessions,
            self.export_dir,
            project_name=self.project_name,
        )
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}")
        self._open(json_path.parent)
