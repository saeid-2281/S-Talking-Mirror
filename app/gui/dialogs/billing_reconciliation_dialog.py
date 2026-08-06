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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.billing_reconciliation import (
    BillingReconciliationRecord,
    BillingReconciliationSnapshot,
)
from app.services.billing_reconciliation_service import BillingReconciliationService


class BillingReconciliationDialog(QDialog):
    """Human-reviewed provider invoice reconciliation and dispute evidence."""

    def __init__(
        self,
        service: BillingReconciliationService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.invoice_paths = list(service.default_invoice_paths())
        self.replay_result_paths = list(service.default_replay_result_paths())
        self.replay_attestation_paths = list(
            service.default_replay_attestation_paths()
        )
        self.replay_pack_paths = list(service.default_replay_pack_paths())
        self.replay_receipt_paths = list(service.default_replay_receipt_paths())
        self.current_snapshot: BillingReconciliationSnapshot | None = None
        self.latest_record: BillingReconciliationRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("billingReconciliationDialog")
        self.setWindowTitle("Provider billing reconciliation & dispute readiness")
        self.resize(1440, 1000)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Provider billing reconciliation & dispute readiness",
            "Normalize a local provider invoice, verify Phase 74 recovery evidence and record reviewed billing reconciliation. This workspace never requests refunds, opens disputes, emails providers, uploads files or changes billing automatically.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        import_section = DialogSection(
            "Normalize a provider invoice CSV",
            "Required columns: line_id, request_id and amount. Optional columns: quantity and usage_type. Raw request identifiers are hashed and the original CSV is not embedded.",
        )
        import_widget = QWidget()
        import_form = QFormLayout(import_widget)
        import_form.setContentsMargins(0, 0, 0, 0)
        invoice_row = QWidget()
        invoice_layout = QHBoxLayout(invoice_row)
        invoice_layout.setContentsMargins(0, 0, 0, 0)
        self.invoice_csv = QLineEdit()
        self.invoice_csv.setPlaceholderText("Select normalized provider invoice CSV")
        choose_invoice = QPushButton(action_icon("project.open"), "Select CSV")
        choose_invoice.clicked.connect(self.select_invoice_csv)
        invoice_layout.addWidget(self.invoice_csv, 1)
        invoice_layout.addWidget(choose_invoice)
        import_form.addRow("Invoice CSV", invoice_row)
        self.invoice_id = QLineEdit()
        self.invoice_id.setPlaceholderText("Provider invoice identifier")
        import_form.addRow("Invoice ID", self.invoice_id)
        self.provider = QLineEdit()
        self.provider.setPlaceholderText("Provider name")
        import_form.addRow("Provider", self.provider)
        self.currency = QLineEdit("USD")
        self.currency.setMaxLength(3)
        import_form.addRow("Currency", self.currency)
        self.period_start = QLineEdit()
        self.period_start.setPlaceholderText("YYYY-MM-DD")
        import_form.addRow("Period start", self.period_start)
        self.period_end = QLineEdit()
        self.period_end.setPlaceholderText("YYYY-MM-DD")
        import_form.addRow("Period end", self.period_end)
        self.invoice_owner = QLineEdit()
        self.invoice_owner.setPlaceholderText("Human reviewer")
        import_form.addRow("Owner", self.invoice_owner)
        self.invoice_notes = QTextEdit()
        self.invoice_notes.setMaximumHeight(70)
        self.invoice_notes.setPlaceholderText("Privacy-safe invoice review notes")
        import_form.addRow("Notes", self.invoice_notes)
        self.invoice_ack = QCheckBox(
            "I reviewed the local invoice metadata and want to record a normalized copy"
        )
        import_form.addRow("", self.invoice_ack)
        import_button = QPushButton(action_icon("save"), "Import normalized invoice")
        import_button.clicked.connect(self.import_invoice)
        import_form.addRow("", import_button)
        import_section.add_widget(import_widget)
        self.workspace.add_body_widget(import_section)

        sources = DialogSection(
            "Verified evidence sources",
            "Select one normalized invoice and matching Phase 74 result, attestation, audit-pack and receipt sets.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.invoice_summary = self._source_row(
            source_form, "Invoice records", self.select_invoice_records
        )
        self.result_summary = self._source_row(
            source_form, "Recovery replay results", self.select_replay_results
        )
        self.attestation_summary = self._source_row(
            source_form,
            "Recovery replay attestations",
            self.select_replay_attestations,
        )
        self.pack_summary = self._source_row(
            source_form, "Recovery replay packs", self.select_replay_packs
        )
        self.receipt_summary = self._source_row(
            source_form, "Recovery replay receipts", self.select_replay_receipts
        )
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        self.status_card = DialogStatusCard(
            "Checking billing reconciliation readiness", "", tone="info"
        )
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Readiness gates",
            "Invoice custody, replay evidence, duplicate screening and request-count alignment.",
        )
        self.gate_table = QTableWidget(0, 4)
        self.gate_table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Detail", "Remediation"]
        )
        self.gate_table.setObjectName("billingReconciliationGateTable")
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gate_table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        result_section = DialogSection(
            "Record reviewed reconciliation",
            "Classify requests and compare the normalized invoice total with the reviewed internal usage ledger. Withheld results remain available as a local manual-dispute pack.",
        )
        result_widget = QWidget()
        result_form = QFormLayout(result_widget)
        result_form.setContentsMargins(0, 0, 0, 0)
        self.result_invoice = QLineEdit()
        self.result_invoice.setReadOnly(True)
        self.result_invoice.setPlaceholderText("Select one verified invoice record")
        result_form.addRow("Invoice record", self.result_invoice)
        self.ledger_total = self._money_spin()
        result_form.addRow("Internal ledger total", self.ledger_total)
        self.provider_credits = self._money_spin()
        result_form.addRow("Provider credits", self.provider_credits)
        self.matched_requests = self._count_spin()
        result_form.addRow("Matched requests", self.matched_requests)
        self.missing_requests = self._count_spin()
        result_form.addRow("Internal requests missing from invoice", self.missing_requests)
        self.unexpected_requests = self._count_spin()
        result_form.addRow("Unexpected invoice requests", self.unexpected_requests)
        self.duplicate_charges = self._count_spin()
        result_form.addRow("Confirmed duplicate charges", self.duplicate_charges)
        self.max_variance = QDoubleSpinBox()
        self.max_variance.setRange(0, self.service.MAX_VARIANCE_PERCENT)
        self.max_variance.setDecimals(2)
        self.max_variance.setValue(1.0)
        self.max_variance.setSuffix(" %")
        result_form.addRow("Maximum variance", self.max_variance)
        self.max_duplicates = self._count_spin()
        result_form.addRow("Maximum duplicate charges", self.max_duplicates)
        self.max_unmatched = self._count_spin()
        result_form.addRow("Maximum unmatched requests", self.max_unmatched)
        self.statement_verified = QCheckBox("Provider statement totals were reviewed")
        self.statement_verified.setChecked(True)
        result_form.addRow("", self.statement_verified)
        self.result_owner = QLineEdit()
        self.result_owner.setPlaceholderText("Human reviewer")
        result_form.addRow("Reviewer", self.result_owner)
        self.result_statement = QTextEdit()
        self.result_statement.setMaximumHeight(80)
        self.result_statement.setPlaceholderText("Privacy-safe reconciliation statement")
        result_form.addRow("Statement", self.result_statement)
        self.result_ack = QCheckBox(
            "I reviewed the comparison and want to record local reconciliation evidence"
        )
        result_form.addRow("", self.result_ack)
        record_button = QPushButton(action_icon("save"), "Record reconciliation")
        record_button.clicked.connect(self.create_result)
        result_form.addRow("", record_button)
        result_section.add_widget(result_widget)
        self.workspace.add_body_widget(result_section)

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

    def _count_spin(self) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(0, self.service.MAX_COUNT)
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

    def select_invoice_csv(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Select provider invoice CSV", str(Path.home()), "CSV files (*.csv)"
        )
        if path:
            self.invoice_csv.setText(path)

    def select_invoice_records(self) -> None:
        paths = self._select("Select normalized invoice record", "JSON files (*.json)")
        if paths:
            self.invoice_paths = paths
            self.refresh()

    def select_replay_results(self) -> None:
        paths = self._select("Select Phase 74 replay results", "JSON files (*.json)")
        if paths:
            self.replay_result_paths = paths
            self.refresh()

    def select_replay_attestations(self) -> None:
        paths = self._select(
            "Select Phase 74 replay attestations", "JSON files (*.json)"
        )
        if paths:
            self.replay_attestation_paths = paths
            self.refresh()

    def select_replay_packs(self) -> None:
        paths = self._select("Select Phase 74 replay packs", "ZIP files (*.zip)")
        if paths:
            self.replay_pack_paths = paths
            self.refresh()

    def select_replay_receipts(self) -> None:
        paths = self._select("Select Phase 74 replay receipts", "JSON files (*.json)")
        if paths:
            self.replay_receipt_paths = paths
            self.refresh()

    def import_invoice(self) -> None:
        result = self.service.import_invoice_csv(
            Path(self.invoice_csv.text()),
            invoice_id=self.invoice_id.text(),
            provider=self.provider.text(),
            currency=self.currency.text(),
            billing_period_start=self.period_start.text(),
            billing_period_end=self.period_end.text(),
            owner=self.invoice_owner.text(),
            notes=self.invoice_notes.toPlainText(),
            acknowledge=self.invoice_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self, "Provider invoice", result.get("detail", "Invoice import blocked")
            )
            return
        self.invoice_paths = [result.invoice_path]
        self.invoice_ack.setChecked(False)
        self.refresh()

    def refresh(self) -> None:
        self.current_snapshot = self.service.snapshot(
            invoice_paths=self.invoice_paths,
            replay_result_paths=self.replay_result_paths,
            replay_attestation_paths=self.replay_attestation_paths,
            replay_pack_paths=self.replay_pack_paths,
            replay_receipt_paths=self.replay_receipt_paths,
        )
        snapshot = self.current_snapshot
        self.invoice_summary.setText(f"{len(self.invoice_paths)} selected")
        self.result_summary.setText(f"{len(self.replay_result_paths)} selected")
        self.attestation_summary.setText(
            f"{len(self.replay_attestation_paths)} selected"
        )
        self.pack_summary.setText(f"{len(self.replay_pack_paths)} selected")
        self.receipt_summary.setText(f"{len(self.replay_receipt_paths)} selected")
        tone = "success" if snapshot.status == "ready" else (
            "warning" if snapshot.status == "ready_with_warnings" else "danger"
        )
        self.status_card.set_status(
            snapshot.status.replace("_", " ").title(),
            (
                f"{snapshot.status_summary} Expected requests: "
                f"{snapshot.expected_request_count}; invoice requests: "
                f"{snapshot.invoice_request_count}; blockers: {snapshot.blocker_count}; "
                f"warnings: {snapshot.warning_count}."
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))
        if snapshot.invoices:
            self.result_invoice.setText(str(snapshot.invoices[0].invoice_path))
        else:
            self.result_invoice.clear()
        self.matched_requests.setValue(
            min(snapshot.expected_request_count, snapshot.invoice_request_count)
        )
        self.missing_requests.setValue(
            max(0, snapshot.expected_request_count - snapshot.invoice_request_count)
        )
        self.unexpected_requests.setValue(
            max(0, snapshot.invoice_request_count - snapshot.expected_request_count)
        )

    def create_result(self) -> None:
        if self.current_snapshot is None or not self.result_invoice.text().strip():
            QMessageBox.warning(
                self, "Billing reconciliation", "Select one verified invoice first."
            )
            return
        result = self.service.create_reconciliation_result(
            self.current_snapshot,
            invoice_path=Path(self.result_invoice.text()),
            ledger_total_amount=self.ledger_total.value(),
            provider_credits_amount=self.provider_credits.value(),
            matched_request_count=self.matched_requests.value(),
            missing_invoice_request_count=self.missing_requests.value(),
            unexpected_invoice_request_count=self.unexpected_requests.value(),
            duplicate_charge_count=self.duplicate_charges.value(),
            max_variance_percent=self.max_variance.value(),
            max_duplicate_charges=self.max_duplicates.value(),
            max_unmatched_requests=self.max_unmatched.value(),
            provider_statement_verified=self.statement_verified.isChecked(),
            owner=self.result_owner.text(),
            statement=self.result_statement.toPlainText(),
            acknowledge=self.result_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self, "Billing reconciliation", result.get("detail", "Blocked")
            )
            return
        self.latest_record = result
        self.result_ack.setChecked(False)
        QMessageBox.information(
            self,
            "Billing reconciliation evidence",
            (
                f"Outcome: {result.outcome_status}\n"
                f"Dispute pack: {result.dispute_pack_path}"
            ),
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
