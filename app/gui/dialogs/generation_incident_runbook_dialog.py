from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.dialogs.incident_runbook_editor_dialog import (
    IncidentRunbookEditorDialog,
)
from app.gui.dialogs.remediation_automation_policy_dialog import (
    RemediationAutomationPolicyDialog,
)
from app.models.generation_automation import GenerationAutomatedRemediation
from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentRemediation,
    GenerationIncidentRunbook,
)
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_remediation_automation_service import (
    GenerationRemediationAutomationService,
)


class GenerationIncidentRunbookDialog(QDialog):
    """Manual runbooks plus fail-safe automated remediation controls."""

    def __init__(
        self,
        service: GenerationIncidentService,
        incident: GenerationIncident,
        parent: QWidget | None = None,
        *,
        project_name: str = "Current project",
        automation_service: GenerationRemediationAutomationService | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.automation_service = automation_service
        self.incident = incident
        self.project_name = project_name
        self.runbooks: list[GenerationIncidentRunbook] = []
        self.remediations: list[GenerationIncidentRemediation] = []
        self.automations: list[GenerationAutomatedRemediation] = []
        self.setWindowTitle("Incident Runbook")
        self.resize(1040, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel(f"Incident Runbook · {self.incident.incident_id}")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)
        root.addWidget(
            QLabel(
                f"{self.project_name} · {self.incident.title} · "
                f"{self.incident.severity.title()}"
            )
        )

        runbook_row = QHBoxLayout()
        self.runbook_combo = QComboBox()
        self.runbook_combo.currentIndexChanged.connect(self.update_runbook_details)
        runbook_row.addWidget(QLabel("Recommended runbook"))
        runbook_row.addWidget(self.runbook_combo, 1)
        for label, handler in (
            ("Start manual", self.start_selected_runbook),
            ("Dry Run", self.dry_run_automation),
            ("Execute", self.execute_automation),
            ("Policy", self.edit_automation_policy),
            ("New", self.new_runbook),
            ("Edit", self.edit_runbook),
            ("Delete", self.delete_runbook),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            if self.automation_service is None and label in {"Dry Run", "Execute", "Policy"}:
                button.setEnabled(False)
            runbook_row.addWidget(button)
        root.addLayout(runbook_row)

        splitter = QSplitter(Qt.Vertical)
        self.runbook_details = QPlainTextEdit()
        self.runbook_details.setReadOnly(True)
        self.runbook_details.setMaximumHeight(230)
        splitter.addWidget(self.runbook_details)

        remediation_panel = QWidget()
        remediation_layout = QVBoxLayout(remediation_panel)
        execution_row = QHBoxLayout()
        execution_row.addWidget(QLabel("Manual execution history"))
        self.remediation_combo = QComboBox()
        self.remediation_combo.currentIndexChanged.connect(self.populate_steps)
        execution_row.addWidget(self.remediation_combo, 1)
        remediation_layout.addLayout(execution_row)

        self.steps_table = QTableWidget(0, 4)
        self.steps_table.setHorizontalHeaderLabels(
            ["Step", "Status", "Actor", "Note"]
        )
        self.steps_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.steps_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.steps_table.verticalHeader().setVisible(False)
        header = self.steps_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        remediation_layout.addWidget(self.steps_table, 1)

        remediation_layout.addWidget(QLabel("Automated remediation audit"))
        self.automation_history = QPlainTextEdit()
        self.automation_history.setReadOnly(True)
        self.automation_history.setMaximumHeight(170)
        remediation_layout.addWidget(self.automation_history)
        splitter.addWidget(remediation_panel)
        splitter.setSizes([220, 460])
        root.addWidget(splitter, 1)

        self.status_label = QLabel()
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        for label, status in (
            ("In progress", "in_progress"),
            ("Complete step", "completed"),
            ("Skip step", "skipped"),
            ("Fail step", "failed"),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, value=status: self.set_step_status(value)
            )
            actions.addWidget(button)
        resume = QPushButton("Resume")
        resume.clicked.connect(self.resume_execution)
        actions.addWidget(resume)
        cancel = QPushButton("Cancel execution")
        cancel.clicked.connect(self.cancel_execution)
        actions.addWidget(cancel)
        rollback = QPushButton("Mark rollback")
        rollback.clicked.connect(self.mark_rollback)
        rollback.setEnabled(self.automation_service is not None)
        actions.addWidget(rollback)
        actions.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        actions.addWidget(refresh)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

    def refresh(self) -> None:
        self.service.ensure_default_runbooks()
        selected_runbook = str(self.runbook_combo.currentData() or "")
        selected_remediation = str(self.remediation_combo.currentData() or "")
        self.runbooks = self.service.recommend_runbooks(self.incident.incident_id)
        self.remediations = self.service.list_remediations(self.incident.incident_id)
        self.automations = (
            self.automation_service.list_executions(self.incident.incident_id)
            if self.automation_service is not None
            else []
        )

        self.runbook_combo.blockSignals(True)
        self.runbook_combo.clear()
        for runbook in self.runbooks:
            scope = "Project" if runbook.project_id is not None else "Global"
            automation = "Auto" if runbook.automation_enabled else "Manual"
            self.runbook_combo.addItem(
                f"{runbook.name} · {scope} · {automation}", runbook.runbook_id
            )
        index = self.runbook_combo.findData(selected_runbook)
        self.runbook_combo.setCurrentIndex(index if index >= 0 else 0)
        self.runbook_combo.blockSignals(False)

        self.remediation_combo.blockSignals(True)
        self.remediation_combo.clear()
        for remediation in self.remediations:
            label = (
                f"{remediation.runbook_name} · {remediation.status.title()} · "
                f"{remediation.progress_percent}%"
            )
            self.remediation_combo.addItem(label, remediation.remediation_id)
        index = self.remediation_combo.findData(selected_remediation)
        if index < 0:
            index = next(
                (
                    row
                    for row, item in enumerate(self.remediations)
                    if item.status == "active"
                ),
                0,
            )
        self.remediation_combo.setCurrentIndex(index if self.remediations else -1)
        self.remediation_combo.blockSignals(False)
        self.update_runbook_details()
        self.populate_steps()
        self.populate_automation_history()

    def selected_runbook(self) -> GenerationIncidentRunbook | None:
        runbook_id = str(self.runbook_combo.currentData() or "")
        return next(
            (item for item in self.runbooks if item.runbook_id == runbook_id),
            None,
        )

    def selected_remediation(self) -> GenerationIncidentRemediation | None:
        remediation_id = str(self.remediation_combo.currentData() or "")
        return next(
            (
                item
                for item in self.remediations
                if item.remediation_id == remediation_id
            ),
            None,
        )

    def update_runbook_details(self) -> None:
        runbook = self.selected_runbook()
        if runbook is None:
            self.runbook_details.clear()
            return
        pattern = runbook.fingerprint_pattern or "Any fingerprint"
        policy = (
            self.automation_service.get_policy(self.incident.project_id)
            if self.automation_service is not None
            else None
        )
        lines = [
            runbook.description or "No description.",
            "",
            f"Severity: {runbook.severity_filter.title()}",
            f"Fingerprint pattern: {pattern}",
            "",
            "Manual steps:",
            *[f"{index + 1}. {step}" for index, step in enumerate(runbook.steps)],
            "",
            f"Automation: {'Enabled' if runbook.automation_enabled else 'Disabled'}",
            f"Trigger: {runbook.automation_trigger.replace('_', ' ').title()}",
            f"Mode: {'Dry Run only' if runbook.dry_run_only else 'Dry Run or confirmed live'}",
            f"Limits: {runbook.max_auto_runs} run(s), {runbook.cooldown_minutes} min cooldown",
            f"Policy: {'Enabled' if policy and policy.enabled else 'Disabled'}",
            "Automation actions:",
            *[
                f"{index + 1}. {action.action_type} · {action.title}"
                for index, action in enumerate(runbook.automation_actions)
            ],
            f"Rollback: {runbook.rollback_instructions or 'Not documented'}",
        ]
        self.runbook_details.setPlainText("\n".join(lines))

    def populate_steps(self) -> None:
        remediation = self.selected_remediation()
        steps = remediation.steps if remediation is not None else ()
        self.steps_table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            values = (
                f"{step.position + 1}. {step.title}",
                step.status.replace("_", " ").title(),
                step.actor or "—",
                step.note or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, step.position)
                self.steps_table.setItem(row, column, item)
        if remediation is None:
            self.status_label.setText("No manual runbook execution has started.")
        else:
            self.status_label.setText(
                f"{remediation.status.title()} · "
                f"{remediation.completed_steps}/{remediation.total_steps} steps · "
                f"{remediation.progress_percent}%"
            )

    def populate_automation_history(self) -> None:
        if not self.automations:
            self.automation_history.setPlainText("No automated remediation audit records.")
            return
        lines: list[str] = []
        for execution in self.automations[:20]:
            mode = "Dry Run" if execution.dry_run else "Live"
            lines.append(
                f"{execution.started_at.replace('T', ' ')[:19]} · {mode} · "
                f"{execution.trigger.replace('_', ' ')} · {execution.status} · "
                f"{execution.completed_actions}/{execution.total_actions} actions"
            )
            if execution.blocked_reason:
                lines.append(f"  Blocked: {execution.blocked_reason}")
            for result in execution.action_results:
                lines.append(
                    f"  {result.position + 1}. {result.action_type}: "
                    f"{result.status} · {result.message}"
                )
            if execution.rollback_status != "not_requested":
                lines.append(
                    f"  Rollback: {execution.rollback_status} · "
                    f"{execution.rollback_note or 'No note'}"
                )
        self.automation_history.setPlainText("\n".join(lines))

    def start_selected_runbook(self) -> None:
        runbook = self.selected_runbook()
        if runbook is None:
            self.status_label.setText("No runbook is available.")
            return
        try:
            remediation = self.service.start_remediation(
                self.incident.incident_id,
                runbook.runbook_id,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        index = self.remediation_combo.findData(remediation.remediation_id)
        if index >= 0:
            self.remediation_combo.setCurrentIndex(index)
        self.status_label.setText(f"Started runbook '{remediation.runbook_name}'.")

    def dry_run_automation(self) -> None:
        self._execute_automation(dry_run=True, confirmed=False)

    def execute_automation(self) -> None:
        runbook = self.selected_runbook()
        if self.automation_service is None or runbook is None:
            self.status_label.setText("Automation service or runbook is unavailable.")
            return
        answer = QMessageBox.question(
            self,
            "Execute live remediation",
            "Run the selected allowlisted actions live? This changes incident or queue state.",
        )
        if answer != QMessageBox.Yes:
            return
        self._execute_automation(dry_run=False, confirmed=True)

    def _execute_automation(self, *, dry_run: bool, confirmed: bool) -> None:
        runbook = self.selected_runbook()
        if self.automation_service is None or runbook is None:
            self.status_label.setText("Automation service or runbook is unavailable.")
            return
        try:
            execution = self.automation_service.execute(
                self.incident.incident_id,
                runbook.runbook_id,
                dry_run=dry_run,
                confirmed=confirmed,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self.status_label.setText(
            f"Automation {execution.status}: {execution.completed_actions}/"
            f"{execution.total_actions} action(s)."
        )

    def edit_automation_policy(self) -> None:
        if self.automation_service is None:
            return
        dialog = RemediationAutomationPolicyDialog(
            self.automation_service,
            self.incident.project_id,
            self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            policy = self.automation_service.save_policy(dialog.policy())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid automation policy", str(exc))
            return
        self.refresh()
        self.status_label.setText(
            f"Automation policy {'enabled' if policy.enabled else 'disabled'}."
        )

    def mark_rollback(self) -> None:
        if self.automation_service is None or not self.automations:
            self.status_label.setText("No automated execution is available.")
            return
        execution = self.automations[0]
        note, accepted = QInputDialog.getMultiLineText(
            self,
            "Mark rollback completed",
            "Rollback note:",
            execution.rollback_note,
        )
        if not accepted:
            return
        updated = self.automation_service.mark_rollback(
            execution.automation_id,
            "completed",
            note=note,
        )
        self.refresh()
        self.status_label.setText(
            f"Rollback marked {updated.rollback_status.replace('_', ' ')}."
        )

    def new_runbook(self) -> None:
        runbook = GenerationIncidentRunbook(
            runbook_id=uuid.uuid4().hex,
            project_id=self.incident.project_id,
            name="",
            severity_filter=self.incident.severity,
            steps=("",),
        )
        self._edit_and_save(runbook)

    def edit_runbook(self) -> None:
        runbook = self.selected_runbook()
        if runbook is None:
            return
        self._edit_and_save(runbook)

    def _edit_and_save(self, runbook: GenerationIncidentRunbook) -> None:
        dialog = IncidentRunbookEditorDialog(runbook, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            candidate = dialog.runbook()
            if self.automation_service is not None:
                candidate = self.automation_service.validate_runbook(candidate)
            saved = self.service.save_runbook(candidate)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid runbook", str(exc))
            return
        self.refresh()
        index = self.runbook_combo.findData(saved.runbook_id)
        if index >= 0:
            self.runbook_combo.setCurrentIndex(index)
        self.status_label.setText(f"Saved runbook '{saved.name}'.")

    def delete_runbook(self) -> None:
        runbook = self.selected_runbook()
        if runbook is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete runbook",
            f"Delete '{runbook.name}'? Existing execution history will be preserved.",
        )
        if answer != QMessageBox.Yes:
            return
        count = self.service.delete_runbook(runbook.runbook_id)
        self.refresh()
        self.status_label.setText(f"Deleted {count} runbook(s).")

    def selected_step_position(self) -> int | None:
        rows: set[int] = set()
        selection_model = self.steps_table.selectionModel()
        if selection_model is not None:
            rows.update(index.row() for index in selection_model.selectedRows())
            if not rows:
                rows.update(index.row() for index in selection_model.selectedIndexes())
            current = selection_model.currentIndex()
            if not rows and current.isValid():
                rows.add(current.row())
        current_row = self.steps_table.currentRow()
        if not rows and current_row >= 0:
            rows.add(current_row)
        valid_rows = sorted(
            row for row in rows if 0 <= row < self.steps_table.rowCount()
        )
        if not valid_rows:
            return None
        row = valid_rows[0]
        item = self.steps_table.item(row, 0)
        value = item.data(Qt.UserRole) if item is not None else None
        return int(value) if value is not None else row

    def set_step_status(self, status: str) -> None:
        remediation = self.selected_remediation()
        position = self.selected_step_position()
        if remediation is None or position is None:
            self.status_label.setText("Select one remediation step.")
            return
        note = ""
        if status in {"skipped", "failed"}:
            note, accepted = QInputDialog.getMultiLineText(
                self,
                f"{status.title()} remediation step",
                "Note (optional):",
            )
            if not accepted:
                return
        try:
            updated = self.service.update_remediation_step(
                remediation.remediation_id,
                position,
                status,
                note=note,
            )
        except (ValueError, IndexError) as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        index = self.remediation_combo.findData(updated.remediation_id)
        if index >= 0:
            self.remediation_combo.setCurrentIndex(index)
        self.status_label.setText(
            f"Step {position + 1} changed to {status.replace('_', ' ')}."
        )

    def resume_execution(self) -> None:
        remediation = self.selected_remediation()
        if remediation is None:
            return
        try:
            updated = self.service.resume_remediation(remediation.remediation_id)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self.status_label.setText(f"Runbook execution is {updated.status}.")

    def cancel_execution(self) -> None:
        remediation = self.selected_remediation()
        if remediation is None:
            return
        updated = self.service.cancel_remediation(remediation.remediation_id)
        self.refresh()
        self.status_label.setText(f"Runbook execution is {updated.status}.")
