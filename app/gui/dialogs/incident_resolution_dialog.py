from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.incident_resolution import (
    IncidentResolutionRecord,
    IncidentResolutionSnapshot,
)
from app.services.incident_resolution_service import IncidentResolutionService


class IncidentResolutionDialog(QDialog):
    """Human-controlled incident resolution, closure and knowledge capture."""

    def __init__(
        self,
        service: IncidentResolutionService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: IncidentResolutionSnapshot | None = None
        self.latest_record: IncidentResolutionRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("incidentResolutionDialog")
        self.setWindowTitle("Incident resolution, closure & knowledge capture")
        self.resize(1320, 900)
        self.setMinimumSize(1020, 720)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Customer-safe incident resolution, closure & knowledge capture",
            "Verify the Phase 64 case and plan, require passed regression and full Quality Gate evidence, then create local tamper-evident closure records. Deployment, rollback, restart, ticket closure, notification and publication are never automatic.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        inputs = DialogSection(
            "Verified case, plan and test evidence",
            "Evidence must be signed privacy-safe JSON for the same case. Original case and plan files remain immutable.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        default_case = self.service.default_case_path()
        self.case_path = QLineEdit(str(default_case))
        self.case_path.setObjectName("incidentResolutionCase")
        self.case_path.setAccessibleName("Incident triage case path")
        form.addRow("Triage case", self.case_path)
        self.plan_path = QLineEdit(str(self.service.default_plan_path(default_case)))
        self.plan_path.setObjectName("incidentResolutionPlan")
        self.plan_path.setAccessibleName("Incident remediation plan path")
        form.addRow("Remediation plan", self.plan_path)
        self.dedicated_evidence = QLineEdit()
        self.dedicated_evidence.setObjectName("incidentResolutionDedicatedEvidence")
        self.dedicated_evidence.setPlaceholderText("Signed dedicated_regression JSON")
        form.addRow("Dedicated regression", self.dedicated_evidence)
        self.quality_evidence = QLineEdit()
        self.quality_evidence.setObjectName("incidentResolutionQualityEvidence")
        self.quality_evidence.setPlaceholderText("Signed full_quality_gate JSON")
        form.addRow("Full Quality Gate", self.quality_evidence)
        self.resolution_type = QComboBox()
        self.resolution_type.setObjectName("incidentResolutionType")
        for value in sorted(self.service.RESOLUTION_TYPES):
            self.resolution_type.addItem(value.replace("_", " ").title(), value)
        form.addRow("Resolution type", self.resolution_type)
        inputs.add_widget(form_widget)
        self.workspace.add_body_widget(inputs)

        narrative = DialogSection(
            "Privacy-safe closure narrative",
            "Use customer-safe language without credentials, local paths, private project text or internal identifiers.",
        )
        narrative_widget = QWidget()
        narrative_form = QFormLayout(narrative_widget)
        narrative_form.setContentsMargins(0, 0, 0, 0)
        self.resolution_summary = QPlainTextEdit()
        self.resolution_summary.setObjectName("incidentResolutionSummary")
        self.resolution_summary.setAccessibleName("Privacy-safe resolution summary")
        self.resolution_summary.setPlaceholderText(
            "Describe the verified change and why it resolves the incident."
        )
        self.resolution_summary.setMaximumHeight(92)
        narrative_form.addRow("Resolution", self.resolution_summary)
        self.customer_impact = QPlainTextEdit()
        self.customer_impact.setObjectName("incidentResolutionCustomerImpact")
        self.customer_impact.setAccessibleName("Customer-safe impact statement")
        self.customer_impact.setPlaceholderText(
            "Describe the customer-visible impact and current state."
        )
        self.customer_impact.setMaximumHeight(82)
        narrative_form.addRow("Customer impact", self.customer_impact)
        narrative.add_widget(narrative_widget)
        self.workspace.add_body_widget(narrative)

        self.status_card = DialogStatusCard("Checking closure gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Closure gates",
            "Every blocker must pass. Closure records never claim that an external ticket was closed or a customer was notified.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("incidentResolutionGateTable")
        self.table.setAccessibleName("Incident resolution closure gates")
        self.table.setHorizontalHeaderLabels(
            ["Status", "Severity", "Gate", "Evidence", "Remediation"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        gates.add_widget(self.table)
        self.workspace.add_body_widget(gates, 1)

        acknowledgement = QWidget()
        acknowledgement_layout = QHBoxLayout(acknowledgement)
        acknowledgement_layout.setContentsMargins(0, 0, 0, 0)
        self.acknowledge = QCheckBox(
            "I reviewed the verified change, test evidence, rollback readiness and customer-safe closure text."
        )
        self.acknowledge.setObjectName("incidentResolutionAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge incident closure creation")
        acknowledgement_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(acknowledgement)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Incident resolution status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh closure", self.refresh, "general.refresh", True),
            ("Create closure records", self.create_closure, "save", False),
            ("Verify latest closure", self.verify_latest, "health", False),
            ("Open resolution folder", self.open_resolution_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in actions:
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.setIcon(action_icon(icon_name))
            if primary:
                button.setObjectName("dialogPrimaryAction")
            button.clicked.connect(handler)
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.setAccessibleName("Close incident resolution")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _evidence_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(value)
            for value in (
                self.dedicated_evidence.text().strip(),
                self.quality_evidence.text().strip(),
            )
            if value
        )

    def _snapshot(self) -> IncidentResolutionSnapshot:
        return self.service.snapshot(
            case_path=Path(self.case_path.text().strip()),
            plan_path=Path(self.plan_path.text().strip()),
            resolution_summary=self.resolution_summary.toPlainText(),
            customer_impact=self.customer_impact.toPlainText(),
            resolution_type=str(self.resolution_type.currentData() or ""),
            evidence_paths=self._evidence_paths(),
        )

    def refresh(self) -> IncidentResolutionSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        tone = "error" if snapshot.status == "blocked" else "warning" if snapshot.warning_count else "success"
        self.status_card.update_status(
            snapshot.status_summary,
            (
                f"{snapshot.version}/{snapshot.channel} · {snapshot.case_id or 'no case'} · "
                f"{snapshot.priority or 'unclassified'} · {snapshot.component} · "
                f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
            ),
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status.title(),
                gate.severity.title(),
                gate.label,
                gate.detail,
                gate.remediation or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(snapshot.status_summary)
        return snapshot

    def create_closure(self) -> IncidentResolutionRecord | None:
        snapshot = self.refresh()
        result = self.service.create_closure(
            snapshot,
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, IncidentResolutionRecord):
            self.latest_record = result
            detail = f"Verified closure created for {result.case_id}: {result.closure_path.name}"
            self.status_label.setText(detail)
            QMessageBox.information(self, "Incident closure verified", detail)
            return result
        detail = str(result.get("detail") or "Incident closure was not created.")
        self.status_label.setText(detail)
        if result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Incident closure blocked", detail)
        return None

    def verify_latest(self) -> None:
        if self.latest_record is not None:
            resolution = self.latest_record.resolution_path
            closure = self.latest_record.closure_path
            knowledge = self.latest_record.knowledge_path
        else:
            candidates = sorted(
                self.service.closures_dir.glob("*-closure.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                QMessageBox.information(self, "No closure", "No incident closure exists yet.")
                return
            closure = candidates[0]
            stem = closure.name.removesuffix("-closure.json")
            resolution = self.service.records_dir / f"{stem}.json"
            knowledge = self.service.knowledge_dir / f"{stem}-knowledge.json"
        checks = (
            self.service.verify_resolution(resolution),
            self.service.verify_closure(closure),
            self.service.verify_knowledge(knowledge),
        )
        ok = all(item[0] for item in checks)
        detail = " ".join(item[1] for item in checks)
        self.status_label.setText(detail)
        if ok:
            QMessageBox.information(self, "Incident closure verified", detail)
        else:
            QMessageBox.warning(self, "Incident closure verification failed", detail)

    def open_resolution_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)
