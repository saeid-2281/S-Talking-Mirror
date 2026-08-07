from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.provider_governance import ProviderGovernanceRecord, ProviderGovernanceSnapshot
from app.services.provider_governance_service import ProviderGovernanceService


class ProviderGovernanceDialog(QDialog):
    """Human-reviewed provider performance and governance workspace."""

    def __init__(
        self,
        service: ProviderGovernanceService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.project_id = project_id
        self.audit_paths = list(service.default_financial_audit_paths())
        self.attestation_paths = list(service.default_financial_attestation_paths())
        self.pack_paths = list(service.default_financial_pack_paths())
        self.receipt_paths = list(service.default_financial_receipt_paths())
        self.current_snapshot: ProviderGovernanceSnapshot | None = None
        self.latest_record: ProviderGovernanceRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("providerGovernanceDialog")
        self.setWindowTitle("Provider performance governance")
        self.resize(1480, 960)
        self.setMinimumSize(1080, 740)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Provider performance governance",
            "Combine provider reliability with verified financial-audit evidence. This workspace records governance evidence only and never changes routing, failover, provider accounts or pricing automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        sources = DialogSection(
            "Governance evidence scope",
            "Use the current reliability window and verified Phase 78 financial-audit evidence.",
        )
        source_widget = QWidget()
        form = QFormLayout(source_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.audit_summary = QLabel("0 selected")
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.audit_summary, 1)
        select_button = QPushButton(action_icon("project.open"), "Select Phase 78 audits")
        select_button.clicked.connect(self.select_audits)
        row_layout.addWidget(select_button)
        form.addRow("Financial audits", row)
        self.minimum_sessions = QSpinBox()
        self.minimum_sessions.setRange(1, 100000)
        self.minimum_sessions.setValue(3)
        form.addRow("Minimum sessions", self.minimum_sessions)
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        self.status_card = DialogStatusCard("Checking provider evidence", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        scorecards = DialogSection(
            "Provider scorecards",
            "Reliability, health, throughput and post-settlement billing accuracy are combined into evidence-backed governance recommendations.",
        )
        self.score_table = QTableWidget(0, 10)
        self.score_table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Sessions",
                "Success",
                "Retry",
                "Health",
                "Billing accuracy",
                "Adjustment",
                "Overall",
                "Risk",
                "Recommendation",
            ]
        )
        self.score_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.score_table.setAlternatingRowColors(True)
        self.score_table.horizontalHeader().setStretchLastSection(True)
        scorecards.add_widget(self.score_table)
        self.workspace.add_body_widget(scorecards)

        gates = DialogSection(
            "Governance gates",
            "Source integrity, financial coverage, overlapping invoices and provider risk are checked before a governance record can be created.",
        )
        self.gate_table = QTableWidget(0, 4)
        self.gate_table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Detail", "Remediation"]
        )
        self.gate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        record = DialogSection(
            "Record governance baseline",
            "A human acknowledgement records the evidence-backed recommendations. It does not apply routing or provider changes.",
        )
        record_widget = QWidget()
        record_form = QFormLayout(record_widget)
        record_form.setContentsMargins(0, 0, 0, 0)
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("Human operations reviewer")
        record_form.addRow("Owner", self.owner)
        self.statement = QTextEdit()
        self.statement.setMaximumHeight(90)
        self.statement.setPlaceholderText("Privacy-safe review statement")
        record_form.addRow("Statement", self.statement)
        create_button = QPushButton(action_icon("save"), "Record governance baseline")
        create_button.clicked.connect(self.create_governance)
        record_form.addRow("", create_button)
        record.add_widget(record_widget)
        self.workspace.add_body_widget(record)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Refresh")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        open_folder = QPushButton(
            action_icon("project.output_folder"), "Open evidence folder"
        )
        open_folder.clicked.connect(lambda: self._open(self.service.root))
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        self.workspace.add_footer_layout(buttons)

    def refresh(self) -> None:
        snapshot = self.service.snapshot(
            project_id=self.project_id,
            minimum_sessions=self.minimum_sessions.value(),
            financial_audit_paths=self.audit_paths,
            financial_attestation_paths=self.attestation_paths,
            financial_pack_paths=self.pack_paths,
            financial_receipt_paths=self.receipt_paths,
        )
        self.current_snapshot = snapshot
        self.audit_summary.setText(f"{len(self.audit_paths)} selected")
        tone = (
            "danger"
            if snapshot.blocker_count
            else "warning"
            if snapshot.warning_count
            else "success"
        )
        self.status_card.set_status(
            f"{snapshot.status} · {snapshot.provider_count} provider(s)",
            snapshot.status_summary,
            tone=tone,
        )
        self._fill_scorecards(snapshot)
        self._fill_gates(snapshot)

    def _fill_scorecards(self, snapshot: ProviderGovernanceSnapshot) -> None:
        self.score_table.setRowCount(len(snapshot.scorecards))
        for row, item in enumerate(snapshot.scorecards):
            values = [
                item.provider,
                str(item.session_count),
                f"{item.job_success_rate:.2f}%",
                f"{item.retry_rate:.2f}%",
                f"{item.average_health_score:.1f}",
                f"{item.billing_accuracy_score:.1f}",
                f"{item.billing_adjustment_rate:.2f}%",
                f"{item.overall_score:.1f}",
                item.risk_level,
                item.recommended_governance,
            ]
            for column, value in enumerate(values):
                self.score_table.setItem(row, column, QTableWidgetItem(value))
        self.score_table.resizeColumnsToContents()

    def _fill_gates(self, snapshot: ProviderGovernanceSnapshot) -> None:
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = [gate.label, gate.status, gate.detail, gate.remediation]
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))
        self.gate_table.resizeColumnsToContents()

    def select_audits(self) -> None:
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select Phase 78 financial audit records",
            str(self.service.financial_audit_service.audits_dir),
            "Financial audit JSON (*.json)",
        )
        if not files:
            return
        self.audit_paths = [Path(item) for item in files]
        audit_ids = []
        for path in self.audit_paths:
            payload = self.service._read_json(path)
            audit_ids.append(str((payload or {}).get("audit_id") or ""))
        self.attestation_paths = [
            self.service.financial_audit_service.attestations_dir
            / f"{audit_id}-attestation.json"
            for audit_id in audit_ids
            if audit_id
        ]
        self.pack_paths = [
            self.service.financial_audit_service.audit_packs_dir
            / f"{audit_id}-audit-pack.zip"
            for audit_id in audit_ids
            if audit_id
        ]
        self.receipt_paths = [
            self.service.financial_audit_service.receipts_dir
            / f"{audit_id}-receipt.json"
            for audit_id in audit_ids
            if audit_id
        ]
        self.refresh()

    def create_governance(self) -> None:
        snapshot = self.current_snapshot
        if snapshot is None:
            return
        result = self.service.create_governance(
            snapshot,
            owner=self.owner.text(),
            statement=self.statement.toPlainText(),
            acknowledge=True,
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self,
                "Provider governance",
                str(result.get("detail") or result.get("status") or "Blocked"),
            )
            return
        self.latest_record = result
        QMessageBox.information(
            self,
            "Provider governance",
            f"Governance evidence created:\n{result.governance_path}",
        )
        self._open(result.governance_path)

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
