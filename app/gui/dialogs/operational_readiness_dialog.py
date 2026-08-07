from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.operational_readiness import OperationalReadinessSnapshot
from app.services.operational_readiness_service import OperationalReadinessCertificationService


class OperationalReadinessDialog(QDialog):
    """Final operational readiness certification workspace."""

    def __init__(
        self,
        service: OperationalReadinessCertificationService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.open_path = open_path
        self.current_snapshot: OperationalReadinessSnapshot | None = None
        self.setObjectName("operationalReadinessDialog")
        self.setWindowTitle("Operational readiness final certification")
        self.resize(1400, 900)
        self.setMinimumSize(1020, 700)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Operational readiness final certification",
            "Freeze the operational reliability track against verified release, operations, freshness and assurance evidence. Certification is read-only and requires explicit human acknowledgement.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard("Loading certification gates", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        gate_section = DialogSection(
            "Final certification gates",
            "Blockers prevent certification. Warnings require human review but never trigger automatic production changes.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Gate", "Status", "Severity", "Detail", "Action"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        gate_section.add_widget(self.table)
        self.workspace.add_body_widget(gate_section)

        approval = DialogSection(
            "Human certification",
            "A reviewer and statement are required to write the final attestation and audit pack.",
        )
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("Reviewer name or role")
        approval.add_widget(self.reviewer)
        self.statement = QLineEdit()
        self.statement.setPlaceholderText("Certification statement (no secrets or local paths)")
        approval.add_widget(self.statement)
        self.workspace.add_body_widget(approval)

        note = QLabel(
            "Read-only contract: no deploy, rollback, restart, provider change, billing change, ticket change, publish or Git tag is performed."
        )
        note.setWordWrap(True)
        self.workspace.add_body_widget(note)

        buttons = QHBoxLayout()
        refresh_button = QPushButton(action_icon("general.refresh"), "Reassess gates")
        refresh_button.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh_button)
        certify_button = QPushButton(action_icon("save"), "Create final certification")
        certify_button.clicked.connect(self.create_certification)
        buttons.addWidget(certify_button)
        open_folder = QPushButton(action_icon("project.output_folder"), "Open certification evidence")
        open_folder.clicked.connect(lambda: self._open(self.service.root))
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        self.workspace.add_footer_layout(buttons)

    def refresh_view(self) -> None:
        snapshot = self.service.assess(project_id=self.project_id)
        self.current_snapshot = snapshot
        tone = (
            "danger"
            if snapshot.status == "blocked"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "success"
        )
        self.overall.set_status(
            snapshot.status.upper(),
            f"{snapshot.pass_count} passed · {snapshot.warning_count} warnings · {snapshot.blocker_count} blockers · commit {snapshot.source_commit or 'unavailable'}",
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = [gate.label, gate.status, gate.severity, gate.detail, gate.action]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()

    def create_certification(self) -> None:
        snapshot = self.service.assess(project_id=self.project_id)
        result = self.service.create_certification(
            snapshot,
            reviewer=self.reviewer.text(),
            statement=self.statement.text(),
            acknowledge=True,
        )
        if result.get("status") in {"blocked", "dry_run"}:
            QMessageBox.warning(self, "Certification not created", str(result.get("detail") or ""))
            self.refresh_view()
            return
        attestation = Path(str(result.get("path") or ""))
        ok, detail = self.service.verify_attestation(attestation)
        if not ok:
            QMessageBox.critical(self, "Certification verification failed", detail)
            return
        self.refresh_view()
        QMessageBox.information(
            self,
            "Operational certification created",
            f"{detail}\n\n{attestation.name}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
