from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.financial_audit import FinancialAuditRecord, FinancialAuditSnapshot
from app.services.financial_audit_service import FinancialAuditService


class FinancialAuditDialog(QDialog):
    """Human-reviewed end-to-end financial audit workspace."""

    def __init__(
        self,
        service: FinancialAuditService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.reconciliation_paths = list(service.default_reconciliation_paths())
        self.reconciliation_attestation_paths = list(
            service.default_reconciliation_attestation_paths()
        )
        self.reconciliation_pack_paths = list(service.default_reconciliation_pack_paths())
        self.reconciliation_receipt_paths = list(
            service.default_reconciliation_receipt_paths()
        )
        self.close_paths = list(service.default_close_paths())
        self.close_attestation_paths = list(service.default_close_attestation_paths())
        self.close_pack_paths = list(service.default_close_pack_paths())
        self.close_receipt_paths = list(service.default_close_receipt_paths())
        self.current_snapshot: FinancialAuditSnapshot | None = None
        self.latest_audit: FinancialAuditRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("financialAuditDialog")
        self.setWindowTitle("Financial audit & cost integrity")
        self.resize(1460, 960)
        self.setMinimumSize(1080, 740)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Financial audit & cost integrity",
            "Reconcile Phase 75 invoice/ledger evidence with Phase 77 settlement credits and financial closes. No ledger, invoice, payment or provider action is automatic.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        sources = DialogSection(
            "Financial evidence scope",
            "Select verified reconciliation and financial-close evidence for one accounting period and currency.",
        )
        source_widget = QWidget()
        form = QFormLayout(source_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.reconciliation_summary = self._source_row(
            form, "Phase 75 reconciliation results", self.select_reconciliations
        )
        self.close_summary = self._source_row(
            form, "Phase 77 financial closes", self.select_closes
        )
        self.period = QLineEdit()
        self.period.setPlaceholderText("YYYY-MM")
        self.period.setText(self.service._now_iso()[:7])
        form.addRow("Accounting period", self.period)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setDecimals(4)
        self.tolerance.setRange(0.0, 1000000.0)
        self.tolerance.setValue(0.01)
        self.tolerance.setSingleStep(0.01)
        form.addRow("Residual tolerance", self.tolerance)
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        self.status_card = DialogStatusCard("Checking financial integrity", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        findings = DialogSection(
            "Invoice integrity findings",
            "Final net invoice equals provider net invoice minus settled credits and should agree with the reviewed internal ledger.",
        )
        self.finding_table = QTableWidget(0, 7)
        self.finding_table.setHorizontalHeaderLabels(
            [
                "Invoice",
                "Provider",
                "Ledger",
                "Net invoice",
                "Settlement credit",
                "Residual",
                "Status",
            ]
        )
        self.finding_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.finding_table.setAlternatingRowColors(True)
        self.finding_table.horizontalHeader().setStretchLastSection(True)
        findings.add_widget(self.finding_table)
        self.workspace.add_body_widget(findings)

        gates = DialogSection(
            "Financial audit gates",
            "Evidence integrity, unique invoice coverage, settlement application and residual variance.",
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

        audit = DialogSection(
            "Record financial audit",
            "Recording an audit creates local tamper-evident evidence only.",
        )
        audit_widget = QWidget()
        audit_form = QFormLayout(audit_widget)
        audit_form.setContentsMargins(0, 0, 0, 0)
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("Human finance auditor")
        audit_form.addRow("Owner", self.owner)
        self.statement = QTextEdit()
        self.statement.setMaximumHeight(90)
        self.statement.setPlaceholderText("Privacy-safe audit statement")
        audit_form.addRow("Statement", self.statement)
        create_button = QPushButton(action_icon("save"), "Record financial audit")
        create_button.clicked.connect(self.create_audit)
        audit_form.addRow("", create_button)
        audit.add_widget(audit_widget)
        self.workspace.add_body_widget(audit)

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

    def _source_row(
        self,
        form: QFormLayout,
        label: str,
        handler: Callable[[], None],
    ) -> QLabel:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        summary = QLabel("0 selected")
        layout.addWidget(summary, 1)
        button = QPushButton(action_icon("project.open"), "Select")
        button.clicked.connect(handler)
        layout.addWidget(button)
        form.addRow(label, row)
        return summary

    def refresh(self) -> None:
        snapshot = self.service.snapshot(
            accounting_period=self.period.text().strip(),
            tolerance_amount=self.tolerance.value(),
            reconciliation_paths=self.reconciliation_paths,
            reconciliation_attestation_paths=self.reconciliation_attestation_paths,
            reconciliation_pack_paths=self.reconciliation_pack_paths,
            reconciliation_receipt_paths=self.reconciliation_receipt_paths,
            close_paths=self.close_paths,
            close_attestation_paths=self.close_attestation_paths,
            close_pack_paths=self.close_pack_paths,
            close_receipt_paths=self.close_receipt_paths,
        )
        self.current_snapshot = snapshot
        self.reconciliation_summary.setText(f"{len(self.reconciliation_paths)} selected")
        self.close_summary.setText(f"{len(self.close_paths)} selected")
        tone = (
            "danger"
            if snapshot.blocker_count
            else "warning"
            if snapshot.warning_count
            else "success"
        )
        self.status_card.set_status(
            f"{snapshot.status} · {snapshot.currency or 'currency pending'}",
            (
                f"{snapshot.status_summary} Ledger {snapshot.total_ledger_amount:.4f}; "
                f"settlement credits {snapshot.total_settlement_credits:.4f}; "
                f"residual {snapshot.total_residual_variance:.4f}."
            ),
            tone=tone,
        )

        self.finding_table.setRowCount(len(snapshot.findings))
        for row, finding in enumerate(snapshot.findings):
            values = (
                finding.invoice_id,
                finding.provider,
                f"{finding.ledger_total_amount:.4f}",
                f"{finding.net_invoice_amount:.4f}",
                f"{finding.settlement_credit_amount:.4f}",
                f"{finding.residual_variance_amount:.4f}",
                finding.status,
            )
            for column, value in enumerate(values):
                self.finding_table.setItem(row, column, QTableWidgetItem(str(value)))

        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))

    def create_audit(self) -> None:
        self.refresh()
        if self.current_snapshot is None:
            return
        result = self.service.create_audit(
            self.current_snapshot,
            owner=self.owner.text(),
            statement=self.statement.toPlainText(),
            acknowledge=True,
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self,
                "Financial audit",
                f"{result.get('status')}: {result.get('detail')}",
            )
            return
        self.latest_audit = result
        QMessageBox.information(
            self,
            "Financial audit recorded",
            (
                f"Audit: {result.audit_path.name}\n"
                f"Audit pack: {result.audit_pack_path.name}\n"
                f"Receipt: {result.receipt_path.name}"
            ),
        )

    def select_reconciliations(self) -> None:
        self.reconciliation_paths = self._choose_files(
            "Select Phase 75 reconciliation results",
            "JSON files (*.json)",
            self.reconciliation_paths,
        )
        self.refresh()

    def select_closes(self) -> None:
        self.close_paths = self._choose_files(
            "Select Phase 77 financial close records",
            "JSON files (*.json)",
            self.close_paths,
        )
        self.refresh()

    def _choose_files(
        self, title: str, filter_text: str, current: list[Path]
    ) -> list[Path]:
        initial = str(current[0].parent if current else self.service.root)
        files, _selected = QFileDialog.getOpenFileNames(self, title, initial, filter_text)
        return [Path(path) for path in files] if files else current

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
