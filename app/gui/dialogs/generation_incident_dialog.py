from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.dialogs.generation_incident_runbook_dialog import (
    GenerationIncidentRunbookDialog,
)
from app.gui.dialogs.generation_incident_review_dialog import (
    GenerationIncidentReviewDialog,
)
from app.gui.dialogs.generation_problem_dialog import GenerationProblemDialog
from app.gui.dialogs.incident_sla_policy_dialog import IncidentSlaPolicyDialog
from app.models.generation_incident import GenerationIncident
from app.services.generation_incident_service import GenerationIncidentService
from app.services.generation_problem_service import GenerationProblemService
from app.services.generation_remediation_automation_service import (
    GenerationRemediationAutomationService,
)


class GenerationIncidentDialog(QDialog):
    """Searchable incident queue with ownership, SLA, and escalation controls."""

    def __init__(
        self,
        service: GenerationIncidentService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        export_dir: Path | None = None,
        problem_service: GenerationProblemService | None = None,
        automation_service: GenerationRemediationAutomationService | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.export_dir = export_dir or Path.cwd() / "reports" / "incidents"
        self.problem_service = problem_service
        self.automation_service = automation_service
        self.all_incidents: list[GenerationIncident] = []
        self.filtered_incidents: list[GenerationIncident] = []
        self.setWindowTitle("Generation Incident Center")
        self.resize(1240, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("Generation Incident Center")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        root.addWidget(title)

        filters = QHBoxLayout()
        self.current_project_only = QCheckBox("Current project only")
        self.current_project_only.setChecked(self.project_id is not None)
        self.current_project_only.setEnabled(self.project_id is not None)
        self.status_filter = QComboBox()
        for label, value in (
            ("All statuses", ""),
            ("Open", "open"),
            ("Acknowledged", "acknowledged"),
            ("Resolved", "resolved"),
            ("Dismissed", "dismissed"),
        ):
            self.status_filter.addItem(label, value)
        self.severity_filter = QComboBox()
        for label, value in (
            ("All severities", ""),
            ("Critical", "critical"),
            ("Warning", "warning"),
        ):
            self.severity_filter.addItem(label, value)
        self.sla_filter = QComboBox()
        for label, value in (
            ("All SLA states", ""),
            ("On track", "on_track"),
            ("Response overdue", "response_overdue"),
            ("Resolution overdue", "resolution_overdue"),
            ("Met", "met"),
            ("Breached", "breached"),
            ("Not configured", "not_configured"),
        ):
            self.sla_filter.addItem(label, value)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search incident, owner, session, fingerprint or note")
        filters.addWidget(self.current_project_only)
        filters.addWidget(self.status_filter)
        filters.addWidget(self.severity_filter)
        filters.addWidget(self.sla_filter)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Status",
                "Severity / SLA",
                "Due",
                "Occurrences",
                "Owner",
                "Escalation",
                "Latest session",
                "Title",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText("Select an incident to view details and update history.")
        splitter.addWidget(self.table)
        splitter.addWidget(self.details)
        splitter.setSizes([440, 240])
        root.addWidget(splitter, 1)

        self.summary_label = QLabel()
        self.status_label = QLabel()
        root.addWidget(self.summary_label)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        for label, handler in (
            ("Assign", self.assign_selected),
            ("Add note", self.add_note_selected),
            ("Acknowledge", self.acknowledge_selected),
            ("Resolve", self.resolve_selected),
            ("Dismiss", self.dismiss_selected),
            ("Reopen", self.reopen_selected),
            ("Runbook", self.open_runbook_selected),
            ("Review", self.open_review_selected),
            ("Create problem", self.create_problem_selected),
            ("Problem Center", self.open_problem_center),
            ("SLA policy", self.edit_sla_policy),
            ("Export filtered", self.export_filtered),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

        self.current_project_only.toggled.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.severity_filter.currentIndexChanged.connect(self.apply_filters)
        self.sla_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.update_details)

    def refresh(self) -> None:
        scope = (
            self.project_id
            if self.project_id is not None and self.current_project_only.isChecked()
            else None
        )
        self.service.evaluate_sla(project_id=scope)
        self.service.evaluate_action_items(project_id=scope)
        self.all_incidents = self.service.list_incidents(limit=1000)
        self.apply_filters()

    def apply_filters(self) -> None:
        project_id = (
            self.project_id
            if self.project_id is not None and self.current_project_only.isChecked()
            else None
        )
        status = str(self.status_filter.currentData() or "")
        severity = str(self.severity_filter.currentData() or "")
        sla_state = str(self.sla_filter.currentData() or "")
        search = self.search.text().strip().casefold()
        records = self.all_incidents
        if project_id is not None:
            records = [item for item in records if item.project_id == project_id]
        if status:
            records = [item for item in records if item.status == status]
        if severity:
            records = [item for item in records if item.severity == severity]
        if sla_state:
            records = [item for item in records if item.sla_state == sla_state]
        if search:
            records = [item for item in records if search in self._search_text(item)]
        self.filtered_incidents = records
        self._populate_table()
        self._update_summary()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.filtered_incidents))
        for row, incident in enumerate(self.filtered_incidents):
            due = incident.resolution_due_at or incident.response_due_at or ""
            values = (
                self._label(incident.status),
                f"{self._label(incident.severity)} / {self._label(incident.sla_state)}",
                self._short_timestamp(due),
                str(incident.occurrence_count),
                incident.assigned_to or "Unassigned",
                f"L{incident.escalation_level}",
                self._short_id(incident.latest_session_id),
                incident.title,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, incident.incident_id)
                self.table.setItem(row, column, item)
        self.table.clearSelection()
        self.details.clear()

    def _update_summary(self) -> None:
        summary = self.service.summary(self.filtered_incidents)
        overdue = summary.response_overdue_count + summary.resolution_overdue_count
        self.summary_label.setText(
            f"{summary.total} incident(s) · {summary.open_count} open · "
            f"{summary.acknowledged_count} acknowledged · {summary.resolved_count} resolved · "
            f"{summary.unassigned_count} unassigned · {overdue} overdue · "
            f"{summary.escalated_count} escalated"
        )

    def selected_incident_ids(self) -> list[str]:
        ids: list[str] = []
        for row in self._selected_rows():
            item = self.table.item(row, 0)
            value = item.data(Qt.UserRole) if item is not None else None
            incident_id = str(value or "").strip()
            if not incident_id and 0 <= row < len(self.filtered_incidents):
                incident_id = self.filtered_incidents[row].incident_id
            if incident_id and incident_id not in ids:
                ids.append(incident_id)
        return ids

    def selected_incidents(self) -> list[GenerationIncident]:
        by_id = {item.incident_id: item for item in self.filtered_incidents}
        return [by_id[value] for value in self.selected_incident_ids() if value in by_id]

    def _selected_rows(self) -> list[int]:
        rows: set[int] = set()
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            rows.update(index.row() for index in selection_model.selectedRows())
            if not rows:
                rows.update(index.row() for index in selection_model.selectedIndexes())
            current = selection_model.currentIndex()
            if not rows and current.isValid():
                rows.add(current.row())
        current_row = self.table.currentRow()
        if not rows and current_row >= 0:
            rows.add(current_row)
        return sorted(row for row in rows if 0 <= row < self.table.rowCount())

    def update_details(self) -> None:
        records = self.selected_incidents()
        if len(records) != 1:
            self.details.setPlainText(
                "Select one incident to view details. Multiple selection is supported for actions."
                if records
                else ""
            )
            return
        incident = records[0]
        updates = self.service.list_updates(incident.incident_id, limit=30)
        remediations = self.service.list_remediations(incident.incident_id, limit=10)
        automations = (
            self.automation_service.list_executions(incident.incident_id, limit=10)
            if self.automation_service is not None
            else []
        )
        review = self.service.get_review(incident.incident_id)
        corrective_actions = self.service.list_action_items(incident.incident_id)
        remediation_lines = [
            (
                f"- {self._short_timestamp(item.started_at)} · {item.runbook_name} · "
                f"{self._label(item.status)} · {item.progress_percent}%"
            )
            for item in remediations
        ]
        automation_lines = [
            (
                f"- {self._short_timestamp(item.started_at)} · "
                f"{'Dry Run' if item.dry_run else 'Live'} · "
                f"{self._label(item.trigger)} · {self._label(item.status)} · "
                f"{item.completed_actions}/{item.total_actions} actions"
            )
            for item in automations
        ]
        action_lines = [
            (
                f"- {item.priority.upper()} · {self._label(item.status)} · "
                f"{item.owner or 'Unassigned'} · {self._short_timestamp(item.due_at or '')}: "
                f"{item.title}"
            )
            for item in corrective_actions
        ]
        update_lines = [
            f"- {self._short_timestamp(item.created_at)} · {self._label(item.kind)}"
            f"{f' · {item.actor}' if item.actor else ''}: {item.message}"
            for item in updates
        ]
        self.details.setPlainText(
            "\n".join(
                [
                    f"Incident: {incident.incident_id}",
                    f"Status / Severity: {self._label(incident.status)} / {self._label(incident.severity)}",
                    f"Priority / Owner: {incident.priority.upper()} / {incident.assigned_to or 'Unassigned'}",
                    f"SLA: {self._label(incident.sla_state)} · escalation L{incident.escalation_level}",
                    f"Response due: {incident.response_due_at or '—'}",
                    f"Resolution due: {incident.resolution_due_at or '—'}",
                    f"Escalated: {incident.escalated_at or '—'}",
                    f"Project: {incident.project_id if incident.project_id is not None else 'Global'}",
                    f"Fingerprint: {incident.alert_fingerprint}",
                    f"Occurrences: {incident.occurrence_count}",
                    f"First session: {incident.first_session_id}",
                    f"Latest session: {incident.latest_session_id}",
                    f"Sessions: {', '.join(incident.session_ids)}",
                    f"Created: {incident.created_at}",
                    f"Updated: {incident.updated_at}",
                    f"Acknowledged: {incident.acknowledged_at or '—'}",
                    f"Resolved: {incident.resolved_at or '—'}",
                    f"Summary: {incident.summary}",
                    f"Resolution note: {incident.resolution_note or '—'}",
                    f"Known problem: {incident.problem_id or '—'}",
                    f"Problem status: {self._label(incident.problem_status)}",
                    "",
                    "Post-incident review:",
                    (
                        f"{self._label(review.status)} · {self._label(review.root_cause_category)} · "
                        f"reviewer: {review.reviewer or 'Unassigned'}"
                        if review is not None
                        else "Not started"
                    ),
                    f"Root cause: {review.root_cause or '—'}" if review is not None else "",
                    f"Lessons learned: {review.lessons_learned or '—'}" if review is not None else "",
                    "",
                    "Corrective actions:",
                    *(action_lines or ["—"]),
                    "",
                    "Runbook executions:",
                    *(remediation_lines or ["—"]),
                    "",
                    "Automated remediations:",
                    *(automation_lines or ["—"]),
                    "",
                    "Incident updates:",
                    *(update_lines or ["—"]),
                ]
            )
        )

    def assign_selected(self) -> None:
        ids = self.selected_incident_ids()
        if not ids:
            self.status_label.setText("Select at least one incident.")
            return
        owner, accepted = QInputDialog.getText(
            self,
            "Assign incidents",
            "Owner name (leave blank to unassign):",
        )
        if not accepted:
            return
        count = self.service.assign(ids, owner)
        self.refresh()
        self.status_label.setText(f"Updated assignment for {count} incident(s).")

    def add_note_selected(self) -> None:
        records = self.selected_incidents()
        if len(records) != 1:
            self.status_label.setText("Select exactly one incident to add a note.")
            return
        note, accepted = QInputDialog.getMultiLineText(
            self,
            "Add incident note",
            "Note:",
        )
        if not accepted:
            return
        update = self.service.add_note(records[0].incident_id, note)
        self.refresh()
        self.status_label.setText("Incident note added." if update is not None else "No note added.")

    def acknowledge_selected(self) -> None:
        count = self.service.acknowledge(self.selected_incident_ids())
        self.refresh()
        self.status_label.setText(f"Acknowledged {count} incident(s).")

    def resolve_selected(self) -> None:
        ids = self.selected_incident_ids()
        if not ids:
            self.status_label.setText("Select at least one incident.")
            return
        note, accepted = QInputDialog.getMultiLineText(
            self,
            "Resolve incidents",
            "Resolution note (optional):",
        )
        if not accepted:
            return
        count = self.service.resolve(ids, note)
        self.refresh()
        self.status_label.setText(f"Resolved {count} incident(s).")

    def dismiss_selected(self) -> None:
        count = self.service.dismiss(self.selected_incident_ids())
        self.refresh()
        self.status_label.setText(f"Dismissed {count} incident(s).")

    def reopen_selected(self) -> None:
        count = self.service.reopen(self.selected_incident_ids())
        self.refresh()
        self.status_label.setText(f"Reopened {count} incident(s).")


    def open_runbook_selected(self) -> None:
        records = self.selected_incidents()
        if len(records) != 1:
            self.status_label.setText("Select exactly one incident to open its runbook.")
            return
        dialog = GenerationIncidentRunbookDialog(
            self.service,
            records[0],
            self,
            project_name=self.project_name,
            automation_service=self.automation_service,
        )
        dialog.exec()
        self.refresh()
        self.status_label.setText("Incident runbook closed.")

    def open_review_selected(self) -> None:
        records = self.selected_incidents()
        if len(records) != 1:
            self.status_label.setText(
                "Select exactly one incident to open its post-incident review."
            )
            return
        dialog = GenerationIncidentReviewDialog(self.service, records[0], self)
        dialog.exec()
        self.refresh()
        self.status_label.setText("Post-incident review closed.")

    def create_problem_selected(self) -> None:
        if self.problem_service is None:
            self.status_label.setText("Problem Management service is unavailable.")
            return
        ids = self.selected_incident_ids()
        if not ids:
            self.status_label.setText("Select at least one incident.")
            return
        try:
            problem = self.problem_service.create_from_incidents(ids)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.refresh()
        self.status_label.setText(
            f"Known problem {problem.problem_id} created or updated."
        )

    def open_problem_center(self) -> None:
        if self.problem_service is None:
            self.status_label.setText("Problem Management service is unavailable.")
            return
        dialog = GenerationProblemDialog(
            self.problem_service,
            self,
            project_id=self.project_id,
            project_name=self.project_name,
            export_dir=self.export_dir.parent / "problems",
        )
        dialog.exec()
        self.refresh()
        self.status_label.setText("Problem Center closed.")

    def edit_sla_policy(self) -> None:
        scope = (
            self.project_id
            if self.project_id is not None and self.current_project_only.isChecked()
            else None
        )
        policy = self.service.get_sla_policy(scope)
        if policy.project_id != scope:
            policy = type(policy)(
                project_id=scope,
                enabled=policy.enabled,
                critical_response_minutes=policy.critical_response_minutes,
                critical_resolution_minutes=policy.critical_resolution_minutes,
                warning_response_minutes=policy.warning_response_minutes,
                warning_resolution_minutes=policy.warning_resolution_minutes,
                updated_at=policy.updated_at,
            )
        dialog = IncidentSlaPolicyDialog(
            policy,
            self,
            project_name=self.project_name if scope is not None else "Global",
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.service.save_sla_policy(dialog.policy())
        self.refresh()
        self.status_label.setText("Incident SLA policy saved and active deadlines recalculated.")

    def export_filtered(self) -> tuple[Path, Path] | None:
        if not self.filtered_incidents:
            self.status_label.setText("No incidents match the current filters.")
            return None
        json_path, csv_path = self.service.export(
            self.filtered_incidents,
            self.export_dir,
            project_name=(
                self.project_name
                if self.project_id is not None and self.current_project_only.isChecked()
                else "all-projects"
            ),
        )
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}")
        return json_path, csv_path

    @staticmethod
    def _search_text(incident: GenerationIncident) -> str:
        return " ".join(
            (
                incident.incident_id,
                incident.alert_fingerprint,
                incident.title,
                incident.summary,
                incident.first_session_id,
                incident.latest_session_id,
                incident.resolution_note or "",
                incident.assigned_to or "",
                incident.priority,
                incident.sla_state,
                incident.problem_id or "",
                incident.problem_status,
            )
        ).casefold()

    @staticmethod
    def _label(value: str) -> str:
        return value.replace("_", " ").title()

    @staticmethod
    def _short_timestamp(value: str) -> str:
        return value.replace("T", " ")[:19] if value else "—"

    @staticmethod
    def _short_id(value: str) -> str:
        return value if len(value) <= 16 else f"{value[:13]}…"
