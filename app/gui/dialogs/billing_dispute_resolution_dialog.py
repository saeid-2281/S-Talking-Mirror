from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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
from app.models.billing_dispute_resolution import (
    BillingDisputeCaseRecord,
    BillingDisputeSnapshot,
    BillingSettlementRecord,
)
from app.services.billing_dispute_resolution_service import (
    BillingDisputeResolutionService,
)


class BillingDisputeResolutionDialog(QDialog):
    """Human-reviewed provider dispute, settlement and ledger closure evidence."""

    def __init__(
        self,
        service: BillingDisputeResolutionService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.result_paths = list(service.default_result_paths())
        self.attestation_paths = list(service.default_attestation_paths())
        self.pack_paths = list(service.default_dispute_pack_paths())
        self.receipt_paths = list(service.default_receipt_paths())
        self.current_snapshot: BillingDisputeSnapshot | None = None
        self.latest_case: BillingDisputeCaseRecord | None = None
        self.latest_settlement: BillingSettlementRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("billingDisputeResolutionDialog")
        self.setWindowTitle("Billing dispute resolution & settlement verification")
        self.resize(1440, 1000)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Billing dispute resolution & settlement verification",
            "Verify Phase 75 reconciliation evidence, record a local provider dispute case and validate credit settlement. This workspace never submits disputes, requests refunds, changes ledgers, emails providers or uploads evidence automatically.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        sources = DialogSection(
            "Phase 75 billing evidence",
            "Select one complete reconciliation result, attestation, dispute pack and receipt per reconciliation identifier.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.result_summary = self._source_row(
            source_form, "Reconciliation results", self.select_results
        )
        self.attestation_summary = self._source_row(
            source_form, "Attestations", self.select_attestations
        )
        self.pack_summary = self._source_row(
            source_form, "Dispute packs", self.select_packs
        )
        self.receipt_summary = self._source_row(
            source_form, "Receipts", self.select_receipts
        )
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        self.status_card = DialogStatusCard(
            "Checking dispute readiness", "", tone="info"
        )
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Readiness gates",
            "Evidence integrity, source uniqueness, currency scope and dispute requirement.",
        )
        self.gate_table = QTableWidget(0, 4)
        self.gate_table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Detail", "Remediation"]
        )
        self.gate_table.setObjectName("billingDisputeGateTable")
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gate_table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        case_section = DialogSection(
            "Record a local provider dispute case",
            "Only withheld Phase 75 reconciliation results can open a dispute case. No provider submission occurs.",
        )
        case_widget = QWidget()
        case_form = QFormLayout(case_widget)
        case_form.setContentsMargins(0, 0, 0, 0)
        self.case_result = QLineEdit()
        self.case_result.setReadOnly(True)
        self.case_result.setPlaceholderText("Select one withheld reconciliation result")
        case_form.addRow("Reconciliation result", self.case_result)
        self.requested_credit = self._money_spin()
        case_form.addRow("Requested credit", self.requested_credit)
        self.case_reference = QLineEdit()
        self.case_reference.setPlaceholderText("Optional internal case reference")
        case_form.addRow("Internal reference", self.case_reference)
        self.case_owner = QLineEdit()
        self.case_owner.setPlaceholderText("Human owner")
        case_form.addRow("Owner", self.case_owner)
        self.case_summary = QTextEdit()
        self.case_summary.setMaximumHeight(80)
        self.case_summary.setPlaceholderText("Privacy-safe dispute summary")
        case_form.addRow("Summary", self.case_summary)
        self.case_ack = QCheckBox(
            "I reviewed the evidence and want to record a local dispute case"
        )
        case_form.addRow("", self.case_ack)
        create_case = QPushButton(action_icon("save"), "Record dispute case")
        create_case.clicked.connect(self.create_case)
        case_form.addRow("", create_case)
        case_section.add_widget(case_widget)
        self.workspace.add_body_widget(case_section)

        settlement_section = DialogSection(
            "Record provider response and settlement",
            "Verify the provider response and reviewed ledger entry before closing or continuing manual follow-up.",
        )
        settlement_widget = QWidget()
        settlement_form = QFormLayout(settlement_widget)
        settlement_form.setContentsMargins(0, 0, 0, 0)
        self.settlement_case = QLineEdit()
        self.settlement_case.setReadOnly(True)
        self.settlement_case.setPlaceholderText("Create or select a dispute case")
        settlement_form.addRow("Dispute case", self.settlement_case)
        choose_case = QPushButton(action_icon("project.open"), "Select case")
        choose_case.clicked.connect(self.select_case)
        settlement_form.addRow("", choose_case)
        self.provider_response = QLineEdit()
        self.provider_response.setPlaceholderText("Provider response reference")
        settlement_form.addRow("Provider response", self.provider_response)
        self.credit_memo = QLineEdit()
        self.credit_memo.setPlaceholderText("Credit memo reference when credit is approved")
        settlement_form.addRow("Credit memo", self.credit_memo)
        self.approved_credit = self._money_spin()
        settlement_form.addRow("Approved credit", self.approved_credit)
        self.applied_credit = self._money_spin()
        settlement_form.addRow("Applied credit", self.applied_credit)
        self.remaining_variance = self._money_spin()
        settlement_form.addRow("Remaining variance", self.remaining_variance)
        self.provider_verified = QCheckBox("Provider response was independently reviewed")
        settlement_form.addRow("", self.provider_verified)
        self.ledger_verified = QCheckBox("Ledger entry was independently reviewed")
        settlement_form.addRow("", self.ledger_verified)
        self.settlement_owner = QLineEdit()
        self.settlement_owner.setPlaceholderText("Human reviewer")
        settlement_form.addRow("Reviewer", self.settlement_owner)
        self.settlement_statement = QTextEdit()
        self.settlement_statement.setMaximumHeight(80)
        self.settlement_statement.setPlaceholderText("Privacy-safe settlement statement")
        settlement_form.addRow("Statement", self.settlement_statement)
        self.settlement_ack = QCheckBox(
            "I reviewed the response and want to record local settlement evidence"
        )
        settlement_form.addRow("", self.settlement_ack)
        record_settlement = QPushButton(action_icon("save"), "Record settlement")
        record_settlement.clicked.connect(self.record_settlement)
        settlement_form.addRow("", record_settlement)
        settlement_section.add_widget(settlement_widget)
        self.workspace.add_body_widget(settlement_section)

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
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        self.workspace.add_footer_layout(buttons)

    def _money_spin(self) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(0, float(self.service.MAX_AMOUNT))
        widget.setDecimals(4)
        return widget

    def _source_row(
        self,
        form: QFormLayout,
        label: str,
        callback: Callable[[], None],
    ) -> QLabel:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        summary = QLabel("0 selected")
        button = QPushButton(action_icon("project.open"), "Select")
        button.clicked.connect(callback)
        layout.addWidget(summary, 1)
        layout.addWidget(button)
        form.addRow(label, row)
        return summary

    def _select(self, title: str, filter_text: str) -> list[Path]:
        paths, _selected = QFileDialog.getOpenFileNames(
            self, title, str(self.service.root), filter_text
        )
        return [Path(path) for path in paths]

    def select_results(self) -> None:
        paths = self._select("Select Phase 75 results", "JSON files (*.json)")
        if paths:
            self.result_paths = paths
            self.refresh()

    def select_attestations(self) -> None:
        paths = self._select("Select Phase 75 attestations", "JSON files (*.json)")
        if paths:
            self.attestation_paths = paths
            self.refresh()

    def select_packs(self) -> None:
        paths = self._select("Select Phase 75 dispute packs", "ZIP files (*.zip)")
        if paths:
            self.pack_paths = paths
            self.refresh()

    def select_receipts(self) -> None:
        paths = self._select("Select Phase 75 receipts", "JSON files (*.json)")
        if paths:
            self.receipt_paths = paths
            self.refresh()

    def select_case(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Select billing dispute case", str(self.service.cases_dir), "JSON files (*.json)"
        )
        if path:
            self.settlement_case.setText(path)

    def refresh(self) -> None:
        self.current_snapshot = self.service.snapshot(
            result_paths=self.result_paths,
            attestation_paths=self.attestation_paths,
            dispute_pack_paths=self.pack_paths,
            receipt_paths=self.receipt_paths,
        )
        snapshot = self.current_snapshot
        self.result_summary.setText(f"{len(self.result_paths)} selected")
        self.attestation_summary.setText(f"{len(self.attestation_paths)} selected")
        self.pack_summary.setText(f"{len(self.pack_paths)} selected")
        self.receipt_summary.setText(f"{len(self.receipt_paths)} selected")
        tone = "success" if snapshot.status == "ready" else (
            "warning" if snapshot.status == "ready_with_warnings" else "danger"
        )
        self.status_card.set_status(
            snapshot.status.replace("_", " ").title(),
            (
                f"{snapshot.status_summary} Dispute required: "
                f"{snapshot.dispute_required_count}; claim: "
                f"{snapshot.total_claim_amount:.4f} {snapshot.currency}; blockers: "
                f"{snapshot.blocker_count}; warnings: {snapshot.warning_count}."
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        withheld = next(
            (source for source in snapshot.sources if source.outcome_status == "withheld"),
            None,
        )
        self.case_result.setText(str(withheld.result_path) if withheld else "")
        if withheld:
            self.requested_credit.setValue(abs(withheld.variance_amount))

    def create_case(self) -> None:
        if self.current_snapshot is None or not self.case_result.text():
            QMessageBox.warning(self, "Billing dispute", "No withheld result is selected.")
            return
        result = self.service.create_dispute_case(
            self.current_snapshot,
            result_path=Path(self.case_result.text()),
            requested_credit_amount=self.requested_credit.value(),
            owner=self.case_owner.text(),
            summary=self.case_summary.toPlainText(),
            internal_reference=self.case_reference.text(),
            acknowledge=self.case_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self, "Billing dispute", result.get("detail", "Dispute case blocked")
            )
            return
        self.latest_case = result
        self.settlement_case.setText(str(result.case_path))
        self.approved_credit.setValue(result.requested_credit_amount)
        self.applied_credit.setValue(result.requested_credit_amount)
        self.remaining_variance.setValue(0)
        self.case_ack.setChecked(False)
        QMessageBox.information(self, "Billing dispute", f"Case recorded:\n{result.case_path}")

    def record_settlement(self) -> None:
        if not self.settlement_case.text():
            QMessageBox.warning(self, "Billing settlement", "Select a dispute case first.")
            return
        result = self.service.record_settlement(
            case_path=Path(self.settlement_case.text()),
            provider_response_reference=self.provider_response.text(),
            credit_memo_reference=self.credit_memo.text(),
            approved_credit_amount=self.approved_credit.value(),
            applied_credit_amount=self.applied_credit.value(),
            remaining_variance_amount=self.remaining_variance.value(),
            owner=self.settlement_owner.text(),
            statement=self.settlement_statement.toPlainText(),
            provider_response_verified=self.provider_verified.isChecked(),
            ledger_entry_verified=self.ledger_verified.isChecked(),
            acknowledge=self.settlement_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self, "Billing settlement", result.get("detail", "Settlement blocked")
            )
            return
        self.latest_settlement = result
        self.settlement_ack.setChecked(False)
        QMessageBox.information(
            self,
            "Billing settlement",
            f"Outcome: {result.outcome_status}\nEvidence: {result.closure_pack_path}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
