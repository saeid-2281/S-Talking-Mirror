from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
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
from app.models.provider_credit_close import (
    ProviderCreditCloseRecord,
    ProviderCreditCloseSnapshot,
)
from app.services.provider_credit_close_service import ProviderCreditCloseService


class ProviderCreditCloseDialog(QDialog):
    """Human-reviewed provider credit period close and audit evidence."""

    def __init__(
        self,
        service: ProviderCreditCloseService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.settlement_paths = list(service.default_settlement_paths())
        self.attestation_paths = list(service.default_attestation_paths())
        self.pack_paths = list(service.default_closure_pack_paths())
        self.receipt_paths = list(service.default_receipt_paths())
        self.current_snapshot: ProviderCreditCloseSnapshot | None = None
        self.latest_close: ProviderCreditCloseRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("providerCreditCloseDialog")
        self.setWindowTitle("Provider credit ledger close & financial control")
        self.resize(1420, 940)
        self.setMinimumSize(1040, 720)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Provider credit ledger close & financial control",
            "Verify Phase 76 settlement evidence and record a privacy-safe accounting-period close. This workspace never changes invoices, ledgers, payments, credit memos or provider accounts automatically.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        sources = DialogSection(
            "Phase 76 settlement evidence",
            "Select one complete settlement, attestation, closure pack and receipt per settlement identifier.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.settlement_summary = self._source_row(
            source_form, "Settlements", self.select_settlements
        )
        self.attestation_summary = self._source_row(
            source_form, "Attestations", self.select_attestations
        )
        self.pack_summary = self._source_row(
            source_form, "Closure packs", self.select_packs
        )
        self.receipt_summary = self._source_row(
            source_form, "Receipts", self.select_receipts
        )
        self.period = QLineEdit()
        self.period.setPlaceholderText("YYYY-MM")
        self.period.setText(self.service._now_iso()[:7])
        source_form.addRow("Accounting period", self.period)
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        self.status_card = DialogStatusCard("Checking close readiness", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Financial close gates",
            "Evidence integrity, accounting period, currency scope, settlement state and remaining variance.",
        )
        self.gate_table = QTableWidget(0, 4)
        self.gate_table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Detail", "Remediation"]
        )
        self.gate_table.setObjectName("providerCreditCloseGateTable")
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gate_table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        close_section = DialogSection(
            "Record accounting-period close",
            "A clean close requires fully settled evidence, zero remaining variance and independent review of the ledger export.",
        )
        close_widget = QWidget()
        close_form = QFormLayout(close_widget)
        close_form.setContentsMargins(0, 0, 0, 0)
        self.owner = QLineEdit()
        self.owner.setPlaceholderText("Human finance reviewer")
        close_form.addRow("Owner", self.owner)
        self.statement = QTextEdit()
        self.statement.setMaximumHeight(90)
        self.statement.setPlaceholderText("Privacy-safe close statement")
        close_form.addRow("Close statement", self.statement)
        self.ledger_verified = QCheckBox(
            "I independently reviewed the ledger export against this settlement evidence"
        )
        close_form.addRow("", self.ledger_verified)
        self.acknowledge = QCheckBox(
            "I reviewed the evidence and want to record a local close record"
        )
        close_form.addRow("", self.acknowledge)
        create_button = QPushButton(action_icon("save"), "Record period close")
        create_button.clicked.connect(self.create_close)
        close_form.addRow("", create_button)
        close_section.add_widget(close_widget)
        self.workspace.add_body_widget(close_section)

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
            settlement_paths=self.settlement_paths,
            attestation_paths=self.attestation_paths,
            closure_pack_paths=self.pack_paths,
            receipt_paths=self.receipt_paths,
        )
        self.current_snapshot = snapshot
        self.settlement_summary.setText(f"{len(self.settlement_paths)} selected")
        self.attestation_summary.setText(f"{len(self.attestation_paths)} selected")
        self.pack_summary.setText(f"{len(self.pack_paths)} selected")
        self.receipt_summary.setText(f"{len(self.receipt_paths)} selected")
        tone = "danger" if snapshot.blocker_count else "warning" if snapshot.warning_count else "success"
        self.status_card.set_status(
            f"{snapshot.status} · {snapshot.currency or 'currency pending'}",
            (
                f"{snapshot.status_summary} Applied {snapshot.total_applied_credit:.4f}; "
                f"remaining {snapshot.total_remaining_variance:.4f}; "
                f"recovery {snapshot.recovery_rate_percent:.2f}%."
            ),
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))

    def create_close(self) -> None:
        self.refresh()
        if self.current_snapshot is None:
            return
        result = self.service.create_close(
            self.current_snapshot,
            owner=self.owner.text(),
            statement=self.statement.toPlainText(),
            ledger_export_verified=self.ledger_verified.isChecked(),
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self,
                "Provider credit close",
                f"{result.get('status')}: {result.get('detail')}",
            )
            return
        self.latest_close = result
        QMessageBox.information(
            self,
            "Provider credit close recorded",
            (
                f"Close: {result.close_path.name}\n"
                f"Audit pack: {result.audit_pack_path.name}\n"
                f"Receipt: {result.receipt_path.name}"
            ),
        )

    def select_settlements(self) -> None:
        self.settlement_paths = self._choose_json(
            "Select Phase 76 settlement records", self.settlement_paths
        )
        self.refresh()

    def select_attestations(self) -> None:
        self.attestation_paths = self._choose_json(
            "Select Phase 76 settlement attestations", self.attestation_paths
        )
        self.refresh()

    def select_packs(self) -> None:
        self.pack_paths = self._choose_files(
            "Select Phase 76 closure packs", "ZIP files (*.zip)", self.pack_paths
        )
        self.refresh()

    def select_receipts(self) -> None:
        self.receipt_paths = self._choose_json(
            "Select Phase 76 closure receipts", self.receipt_paths
        )
        self.refresh()

    def _choose_json(self, title: str, current: list[Path]) -> list[Path]:
        return self._choose_files(title, "JSON files (*.json)", current)

    def _choose_files(
        self, title: str, filter_text: str, current: list[Path]
    ) -> list[Path]:
        start = str(current[0].parent if current else self.service.root)
        files, _filter = QFileDialog.getOpenFileNames(self, title, start, filter_text)
        return [Path(path) for path in files] if files else current

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
