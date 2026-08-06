from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
from app.models.reliability_assurance_renewal import (
    ReliabilityAssuranceRenewalRecord,
    ReliabilityAssuranceRenewalSnapshot,
)
from app.services.reliability_assurance_renewal_service import (
    ReliabilityAssuranceRenewalService,
)


class ReliabilityAssuranceRenewalDialog(QDialog):
    """Human-controlled assurance renewal and exception follow-up workspace."""

    def __init__(
        self,
        service: ReliabilityAssuranceRenewalService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.attestation_paths = list(service.default_attestation_paths())
        self.audit_pack_paths = list(service.default_audit_pack_paths())
        self.receipt_paths = list(service.default_receipt_paths())
        self.current_snapshot: ReliabilityAssuranceRenewalSnapshot | None = None
        self.latest_record: ReliabilityAssuranceRenewalRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("reliabilityAssuranceRenewalDialog")
        self.setWindowTitle("Reliability assurance renewal & follow-up")
        self.resize(1420, 940)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Reliability assurance renewal & exception follow-up",
            "Verify Phase 68 assurance custody, detect due or overdue lifecycle reviews and create a local tamper-evident renewal record. Nothing is uploaded, scheduled, ticketed, accepted or changed automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        source = DialogSection(
            "Verified Phase 68 assurance sources",
            "Every assurance requires one intact attestation, audit pack and receipt.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.attestation_summary = self._source_row(
            source_form,
            "Attestations",
            "reliabilityRenewalAttestationSummary",
            self.select_attestations,
        )
        self.pack_summary = self._source_row(
            source_form,
            "Audit packs",
            "reliabilityRenewalPackSummary",
            self.select_packs,
        )
        self.receipt_summary = self._source_row(
            source_form,
            "Receipts",
            "reliabilityRenewalReceiptSummary",
            self.select_receipts,
        )
        self.validity_days = QSpinBox()
        self.validity_days.setObjectName("reliabilityRenewalValidityDays")
        self.validity_days.setRange(
            self.service.MIN_VALIDITY_DAYS,
            self.service.MAX_VALIDITY_DAYS,
        )
        self.validity_days.setValue(self.service.DEFAULT_VALIDITY_DAYS)
        source_form.addRow("Validity period", self.validity_days)
        self.due_soon_days = QSpinBox()
        self.due_soon_days.setObjectName("reliabilityRenewalDueSoonDays")
        self.due_soon_days.setRange(
            self.service.MIN_DUE_SOON_DAYS,
            self.service.MAX_DUE_SOON_DAYS,
        )
        self.due_soon_days.setValue(self.service.DEFAULT_DUE_SOON_DAYS)
        source_form.addRow("Due-soon window", self.due_soon_days)
        source.add_widget(source_widget)
        self.workspace.add_body_widget(source)

        self.status_card = DialogStatusCard("Checking renewal gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        metrics = DialogSection(
            "Renewal lifecycle",
            "Current, due-soon, overdue and withheld assurances across verified source custody.",
        )
        metrics_widget = QWidget()
        metrics_layout = QHBoxLayout(metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_labels: dict[str, QLabel] = {}
        for key, label in (
            ("triplets", "Verified triplets"),
            ("current", "Current"),
            ("due", "Due soon"),
            ("overdue", "Overdue"),
            ("withheld", "Withheld"),
            ("exceptions", "Follow-up items"),
        ):
            card = DialogStatusCard(label, "0", tone="info")
            self.metric_labels[key] = card.detail_label
            metrics_layout.addWidget(card, 1)
        metrics.add_widget(metrics_widget)
        self.workspace.add_body_widget(metrics)

        sources = DialogSection(
            "Assurance lifecycle sources",
            "Review the human assurance decision and lifecycle deadline before renewal.",
        )
        self.source_table = QTableWidget(0, 7)
        self.source_table.setObjectName("reliabilityRenewalSourceTable")
        self.source_table.setAccessibleName("Reliability assurance renewal sources")
        self.source_table.setHorizontalHeaderLabels(
            ["Status", "Assurance", "Decision", "Age", "Review due", "Days", "Exceptions"]
        )
        self._configure_table(self.source_table)
        sources.add_widget(self.source_table)
        self.workspace.add_body_widget(sources)

        exceptions = DialogSection(
            "Renewal follow-up",
            "Due, overdue, withheld and carried exceptions require an explicit human decision.",
        )
        self.exception_table = QTableWidget(0, 6)
        self.exception_table.setObjectName("reliabilityRenewalExceptionTable")
        self.exception_table.setAccessibleName("Reliability assurance renewal follow-up")
        self.exception_table.setHorizontalHeaderLabels(
            ["Severity", "Category", "Summary", "Due", "Assurance", "Status"]
        )
        self._configure_table(self.exception_table)
        exceptions.add_widget(self.exception_table)
        self.workspace.add_body_widget(exceptions)

        gates = DialogSection(
            "Renewal gates",
            "Blockers prevent renewal. Warnings require governed follow-up or withholding.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("reliabilityRenewalGateTable")
        self.gate_table.setAccessibleName("Reliability assurance renewal gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Detail", "Remediation"]
        )
        self._configure_table(self.gate_table)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        renewal = DialogSection(
            "Human renewal decision",
            "Unqualified renewal requires zero follow-up items. Qualified renewal requires an owner and future review date.",
        )
        renewal_widget = QWidget()
        renewal_form = QFormLayout(renewal_widget)
        renewal_form.setContentsMargins(0, 0, 0, 0)
        self.outcome = QComboBox()
        self.outcome.setObjectName("reliabilityRenewalOutcome")
        self.outcome.addItems(self.service.RENEWAL_DECISIONS)
        renewal_form.addRow("Decision", self.outcome)
        self.owner = QLineEdit()
        self.owner.setObjectName("reliabilityRenewalOwner")
        self.owner.setPlaceholderText("Human renewal owner")
        renewal_form.addRow("Renewal owner", self.owner)
        self.follow_up_owner = QLineEdit()
        self.follow_up_owner.setObjectName("reliabilityRenewalFollowUpOwner")
        self.follow_up_owner.setPlaceholderText("Required for renewal with follow-up")
        renewal_form.addRow("Follow-up owner", self.follow_up_owner)
        self.next_review = QLineEdit()
        self.next_review.setObjectName("reliabilityRenewalNextReview")
        self.next_review.setPlaceholderText("YYYY-MM-DD")
        renewal_form.addRow("Next review", self.next_review)
        self.statement = QTextEdit()
        self.statement.setObjectName("reliabilityRenewalStatement")
        self.statement.setAccessibleName("Privacy-safe renewal statement")
        self.statement.setPlaceholderText(
            "Describe the human renewal conclusion without credentials or local paths."
        )
        self.statement.setMinimumHeight(86)
        renewal_form.addRow("Statement", self.statement)
        self.acknowledge = QCheckBox(
            "I reviewed every source and follow-up item; create local immutable records only."
        )
        self.acknowledge.setObjectName("reliabilityRenewalAcknowledge")
        renewal_form.addRow("", self.acknowledge)
        renewal.add_widget(renewal_widget)
        self.workspace.add_body_widget(renewal)

        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        self.workspace.add_footer_widget(refresh)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        self.workspace.add_footer_widget(export)
        self.create_button = QPushButton("Create renewal audit pack")
        self.create_button.setObjectName("reliabilityRenewalCreateButton")
        self.create_button.setIcon(action_icon("report"))
        self.create_button.clicked.connect(self.create_renewal)
        self.workspace.add_footer_widget(self.create_button)

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)

    def _source_row(
        self,
        form: QFormLayout,
        label: str,
        object_name: str,
        callback: Callable[[], None],
    ) -> QLabel:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        summary = QLabel("0 selected")
        summary.setObjectName(object_name)
        summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        button = QPushButton("Select")
        button.clicked.connect(callback)
        layout.addWidget(summary, 1)
        layout.addWidget(button)
        form.addRow(label, row)
        return summary

    def select_attestations(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Phase 68 assurance attestations",
            str(self.service.reliability_assurance_service.attestations_dir),
            "JSON files (*.json)",
        )
        if paths:
            self.attestation_paths = [Path(path) for path in paths]
            self.refresh()

    def select_packs(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Phase 68 assurance audit packs",
            str(self.service.reliability_assurance_service.audit_packs_dir),
            "ZIP files (*.zip)",
        )
        if paths:
            self.audit_pack_paths = [Path(path) for path in paths]
            self.refresh()

    def select_receipts(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Phase 68 assurance receipts",
            str(self.service.reliability_assurance_service.receipts_dir),
            "JSON files (*.json)",
        )
        if paths:
            self.receipt_paths = [Path(path) for path in paths]
            self.refresh()

    def refresh(self) -> None:
        self.attestation_summary.setText(f"{len(self.attestation_paths)} selected")
        self.pack_summary.setText(f"{len(self.audit_pack_paths)} selected")
        self.receipt_summary.setText(f"{len(self.receipt_paths)} selected")
        self.current_snapshot = self.service.snapshot(
            attestation_paths=self.attestation_paths,
            audit_pack_paths=self.audit_pack_paths,
            receipt_paths=self.receipt_paths,
            validity_days=self.validity_days.value(),
            due_soon_days=self.due_soon_days.value(),
        )
        snapshot = self.current_snapshot
        tone = "danger" if snapshot.blocker_count else "warning" if snapshot.warning_count else "success"
        self.status_card.update_status(
            snapshot.status.replace("_", " ").title(),
            snapshot.status_summary,
            tone=tone,
        )
        values = {
            "triplets": snapshot.verified_triplet_count,
            "current": snapshot.current_count,
            "due": snapshot.due_soon_count,
            "overdue": snapshot.overdue_count,
            "withheld": snapshot.withheld_count,
            "exceptions": snapshot.open_exception_count,
        }
        for key, value in values.items():
            self.metric_labels[key].setText(str(value))
        self._populate_sources(snapshot)
        self._populate_exceptions(snapshot)
        self._populate_gates(snapshot)
        self.create_button.setEnabled(snapshot.renewal_allowed)

    def _populate_sources(self, snapshot: ReliabilityAssuranceRenewalSnapshot) -> None:
        self.source_table.setRowCount(len(snapshot.sources))
        for row, source in enumerate(snapshot.sources):
            values = (
                source.lifecycle_status,
                source.assurance_id,
                source.assurance_decision,
                str(source.age_days),
                source.review_due_date,
                str(source.days_until_review),
                str(source.source_exception_count),
            )
            for column, value in enumerate(values):
                self.source_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_exceptions(self, snapshot: ReliabilityAssuranceRenewalSnapshot) -> None:
        self.exception_table.setRowCount(len(snapshot.exceptions))
        for row, item in enumerate(snapshot.exceptions):
            values = (
                item.severity,
                item.category,
                item.summary,
                item.due_date,
                item.assurance_id,
                item.status,
            )
            for column, value in enumerate(values):
                self.exception_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_gates(self, snapshot: ReliabilityAssuranceRenewalSnapshot) -> None:
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status,
                gate.label,
                gate.severity,
                gate.detail,
                gate.remediation,
            )
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))

    def export_snapshot(self) -> None:
        if self.current_snapshot is None:
            self.refresh()
        assert self.current_snapshot is not None
        path = self.service.export_snapshot(self.current_snapshot)
        QMessageBox.information(self, "Snapshot exported", str(path))
        self._open_path(path)

    def create_renewal(self) -> None:
        self.refresh()
        assert self.current_snapshot is not None
        result = self.service.create_renewal(
            self.current_snapshot,
            decision=self.outcome.currentText(),
            owner=self.owner.text(),
            statement=self.statement.toPlainText(),
            follow_up_owner=self.follow_up_owner.text(),
            next_review_date=self.next_review.text(),
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            message = str(result.get("detail") or "Renewal was not created.")
            if result.get("status") == "dry_run":
                QMessageBox.information(self, "Renewal dry run", message)
            else:
                QMessageBox.warning(self, "Renewal blocked", message)
            return
        self.latest_record = result
        QMessageBox.information(
            self,
            "Renewal created",
            f"Renewal: {result.renewal_path}\nAudit pack: {result.audit_pack_path}\nReceipt: {result.receipt_path}",
        )
        self._open_path(result.audit_pack_path)
        self.refresh()

    def _open_path(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
