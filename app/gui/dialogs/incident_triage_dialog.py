from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
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
from app.models.incident_triage import IncidentTriageCase, IncidentTriageSnapshot
from app.services.incident_triage_service import IncidentTriageService


class IncidentTriageDialog(QDialog):
    """Verified support-bundle intake and human-controlled remediation workspace."""

    def __init__(
        self,
        service: IncidentTriageService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: IncidentTriageSnapshot | None = None
        self.latest_case: IncidentTriageCase | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("incidentTriageDialog")
        self.setWindowTitle("Incident triage & remediation readiness")
        self.resize(1280, 840)
        self.setMinimumSize(980, 680)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Support bundle intake, incident triage & remediation readiness",
            "Verify a Phase 63 bundle and receipt, classify priority and component, then create local tamper-evident case records. Ticket creation, patching, rollback, restart and publication are never automatic.",
            icon_name="warning",
            parent=self,
        )
        root.addWidget(self.workspace)

        inputs = DialogSection(
            "Verified incident evidence",
            "Use the original Phase 63 ZIP and matching receipt. The bundle is inspected in place and private source files are never copied into triage records.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        default_bundle = self.service.default_bundle_path()
        self.bundle = QLineEdit(str(default_bundle))
        self.bundle.setObjectName("incidentTriageBundle")
        self.bundle.setAccessibleName("Incident support bundle path")
        form.addRow("Support bundle", self.bundle)
        default_receipt = self.service.default_receipt_path(default_bundle)
        self.receipt = QLineEdit(str(default_receipt or ""))
        self.receipt.setObjectName("incidentTriageReceipt")
        self.receipt.setAccessibleName("Incident support receipt path")
        self.receipt.setPlaceholderText("Optional: matching Phase 63 receipt JSON")
        form.addRow("Support receipt", self.receipt)
        inputs.add_widget(form_widget)
        self.workspace.add_body_widget(inputs)

        self.status_card = DialogStatusCard("Checking incident triage gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        summary_section = DialogSection(
            "Triage classification",
            "Priority and component are deterministic recommendations. A human incident owner remains responsible for confirmation and any operational decision.",
        )
        summary_widget = QWidget()
        summary_layout = QHBoxLayout(summary_widget)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.classification_label = QLabel("No verified incident loaded")
        self.classification_label.setObjectName("historyStatusLabel")
        self.classification_label.setAccessibleName("Incident triage classification")
        self.classification_label.setWordWrap(True)
        summary_layout.addWidget(self.classification_label, 1)
        summary_section.add_widget(summary_widget)
        self.workspace.add_body_widget(summary_section)

        gates = DialogSection(
            "Triage gates and custody checks",
            "Blockers prevent case creation. Warnings remain recorded for manual review and duplicate-case handling.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("incidentTriageGateTable")
        self.table.setAccessibleName("Incident triage gates")
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
            "I reviewed bundle custody, priority, duplicate warnings and the manual remediation plan."
        )
        self.acknowledge.setObjectName("incidentTriageAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge incident triage case creation")
        acknowledgement_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(acknowledgement)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Incident triage status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh triage", self.refresh, "general.refresh", True),
            ("Create triage case", self.create_case, "save", False),
            ("Verify latest case", self.verify_latest_case, "health", False),
            ("Open triage folder", self.open_triage_folder, "project.output_folder", False),
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
        close.setAccessibleName("Close incident triage")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _snapshot(self) -> IncidentTriageSnapshot:
        receipt_text = self.receipt.text().strip()
        return self.service.snapshot(
            bundle_path=Path(self.bundle.text().strip()),
            receipt_path=Path(receipt_text) if receipt_text else None,
        )

    def refresh(self) -> IncidentTriageSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        tone = (
            "error"
            if snapshot.status == "blocked"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "success"
        )
        self.status_card.update_status(
            snapshot.status_summary,
            (
                f"{snapshot.version}/{snapshot.channel} · {snapshot.priority} · "
                f"{snapshot.effective_severity} · {snapshot.component} · "
                f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
            ),
            tone=tone,
        )
        self.classification_label.setText(
            f"Incident {snapshot.incident_id or 'unavailable'} · Reported {snapshot.reported_severity} · "
            f"Effective {snapshot.effective_severity}/{snapshot.priority} · Component {snapshot.component} · "
            f"Acknowledge within {snapshot.acknowledgement_target_minutes} minute(s) · "
            f"Remediation target {snapshot.remediation_target_minutes} minute(s) · "
            f"Related verified cases {snapshot.duplicate_count}"
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

    def create_case(self) -> IncidentTriageCase | None:
        snapshot = self.refresh()
        result = self.service.create_case(
            snapshot,
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, IncidentTriageCase):
            self.latest_case = result
            detail = (
                f"Verified {result.priority} triage case created for {result.component}: "
                f"{result.case_path.name}"
            )
            self.status_label.setText(detail)
            QMessageBox.information(self, "Incident triage case verified", detail)
            return result

        detail = str(result.get("detail") or "Incident triage case was not created.")
        self.status_label.setText(detail)
        if result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Incident triage blocked", detail)
        return None

    def verify_latest_case(self) -> None:
        if self.latest_case is not None:
            case_path = self.latest_case.case_path
            plan_path = self.latest_case.plan_path
        else:
            candidates = sorted(
                self.service.cases_dir.glob("triage-*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                QMessageBox.information(self, "No triage case", "No incident triage case exists yet.")
                return
            case_path = candidates[0]
            plan_path = self.service.plans_dir / f"{case_path.stem}-remediation-plan.json"
        case_ok, case_detail = self.service.verify_case(case_path)
        plan_ok, plan_detail = self.service.verify_plan(plan_path)
        detail = f"{case_detail} {plan_detail}"
        self.status_label.setText(detail)
        if case_ok and plan_ok:
            QMessageBox.information(self, "Incident triage verified", detail)
        else:
            QMessageBox.warning(self, "Incident triage verification failed", detail)

    def open_triage_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)
