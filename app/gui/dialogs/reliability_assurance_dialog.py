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
from app.models.reliability_assurance import (
    ReliabilityAssuranceRecord,
    ReliabilityAssuranceSnapshot,
)
from app.services.reliability_assurance_service import ReliabilityAssuranceService


class ReliabilityAssuranceDialog(QDialog):
    """Human-controlled reliability assurance and local audit-pack workspace."""

    def __init__(
        self,
        service: ReliabilityAssuranceService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.review_paths = list(service.default_review_paths())
        self.decision_paths = list(service.default_decision_paths())
        self.current_snapshot: ReliabilityAssuranceSnapshot | None = None
        self.latest_record: ReliabilityAssuranceRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("reliabilityAssuranceDialog")
        self.setWindowTitle("Reliability assurance, exceptions & audit pack")
        self.resize(1420, 940)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Reliability assurance, exception governance & audit pack",
            "Verify Phase 67 review/decision custody, surface open reliability exceptions and create a local tamper-evident assurance pack. Nothing is uploaded, published, scheduled, accepted or changed automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        source = DialogSection(
            "Verified Phase 67 sources",
            "Every effectiveness review must have exactly one intact human decision inside the selected assurance window.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.review_summary = self._source_row(
            source_form,
            "Effectiveness reviews",
            "reliabilityAssuranceReviewSummary",
            self.select_reviews,
        )
        self.decision_summary = self._source_row(
            source_form,
            "Human decisions",
            "reliabilityAssuranceDecisionSummary",
            self.select_decisions,
        )
        self.window_days = QSpinBox()
        self.window_days.setObjectName("reliabilityAssuranceWindowDays")
        self.window_days.setRange(
            self.service.MIN_ASSURANCE_WINDOW_DAYS,
            self.service.MAX_ASSURANCE_WINDOW_DAYS,
        )
        self.window_days.setValue(self.service.DEFAULT_ASSURANCE_WINDOW_DAYS)
        source_form.addRow("Assurance window", self.window_days)
        source.add_widget(source_widget)
        self.workspace.add_body_widget(source)

        self.status_card = DialogStatusCard("Checking assurance gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        metrics = DialogSection(
            "Assurance coverage",
            "Verified pairs and the decisions that determine qualified or unqualified assurance.",
        )
        metrics_widget = QWidget()
        metrics_layout = QHBoxLayout(metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_labels: dict[str, QLabel] = {}
        for key, label in (
            ("pairs", "Verified pairs"),
            ("closed", "Closed effective"),
            ("monitoring", "Monitoring"),
            ("escalation", "Escalations"),
            ("risk", "Accepted risk"),
            ("exceptions", "Open exceptions"),
        ):
            card = DialogStatusCard(label, "0", tone="info")
            self.metric_labels[key] = card.detail_label
            metrics_layout.addWidget(card, 1)
        metrics.add_widget(metrics_widget)
        self.workspace.add_body_widget(metrics)

        exceptions = DialogSection(
            "Reliability exceptions",
            "Monitoring, escalation, accepted risk, overdue work and recurrence stay open until a later human governance decision.",
        )
        self.exception_table = QTableWidget(0, 7)
        self.exception_table.setObjectName("reliabilityAssuranceExceptionTable")
        self.exception_table.setAccessibleName("Open reliability exceptions")
        self.exception_table.setHorizontalHeaderLabels(
            ["Severity", "Category", "Summary", "Decision", "Age", "Review", "Status"]
        )
        self._configure_table(self.exception_table)
        exceptions.add_widget(self.exception_table)
        self.workspace.add_body_widget(exceptions)

        gates = DialogSection(
            "Assurance gates",
            "Blockers prevent attestation. Warnings require qualified assurance or withholding.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("reliabilityAssuranceGateTable")
        self.gate_table.setAccessibleName("Reliability assurance gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Detail", "Remediation"]
        )
        self._configure_table(self.gate_table)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        assurance = DialogSection(
            "Human assurance decision",
            "An unqualified decision requires zero open exceptions. Qualified assurance requires an owner and a future review date.",
        )
        assurance_widget = QWidget()
        assurance_form = QFormLayout(assurance_widget)
        assurance_form.setContentsMargins(0, 0, 0, 0)
        self.outcome = QComboBox()
        self.outcome.setObjectName("reliabilityAssuranceOutcome")
        self.outcome.addItems(self.service.ASSURANCE_DECISIONS)
        assurance_form.addRow("Decision", self.outcome)
        self.owner = QLineEdit()
        self.owner.setObjectName("reliabilityAssuranceOwner")
        self.owner.setPlaceholderText("Human assurance owner")
        assurance_form.addRow("Assurance owner", self.owner)
        self.exception_owner = QLineEdit()
        self.exception_owner.setObjectName("reliabilityAssuranceExceptionOwner")
        self.exception_owner.setPlaceholderText("Required for assurance with exceptions")
        assurance_form.addRow("Exception owner", self.exception_owner)
        self.next_review = QLineEdit()
        self.next_review.setObjectName("reliabilityAssuranceNextReview")
        self.next_review.setPlaceholderText("YYYY-MM-DD")
        assurance_form.addRow("Next review", self.next_review)
        self.statement = QTextEdit()
        self.statement.setObjectName("reliabilityAssuranceStatement")
        self.statement.setAccessibleName("Privacy-safe assurance statement")
        self.statement.setPlaceholderText(
            "Describe the human assurance conclusion without credentials or local paths."
        )
        self.statement.setMinimumHeight(86)
        assurance_form.addRow("Statement", self.statement)
        self.acknowledge = QCheckBox(
            "I reviewed every source and exception; create local immutable records only."
        )
        self.acknowledge.setObjectName("reliabilityAssuranceAcknowledge")
        assurance_form.addRow("", self.acknowledge)
        assurance.add_widget(assurance_widget)
        self.workspace.add_body_widget(assurance)

        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        self.workspace.add_footer_widget(refresh)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        self.workspace.add_footer_widget(export)
        self.create_button = QPushButton("Create assurance audit pack")
        self.create_button.setObjectName("reliabilityAssuranceCreateButton")
        self.create_button.setIcon(action_icon("report"))
        self.create_button.clicked.connect(self.create_assurance)
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
    ) -> QLineEdit:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit()
        line.setObjectName(object_name)
        line.setReadOnly(True)
        layout.addWidget(line, 1)
        select = QPushButton("Select files")
        select.setIcon(action_icon("project.open"))
        select.clicked.connect(callback)
        layout.addWidget(select)
        form.addRow(label, row)
        return line

    def select_reviews(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Phase 67 effectiveness reviews",
            str(self.service.prevention_effectiveness_service.reviews_dir),
            "JSON files (*.json)",
        )
        if paths:
            self.review_paths = [Path(path) for path in paths]
            self.refresh()

    def select_decisions(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Phase 67 effectiveness decisions",
            str(self.service.prevention_effectiveness_service.decisions_dir),
            "JSON files (*.json)",
        )
        if paths:
            self.decision_paths = [Path(path) for path in paths]
            self.refresh()

    def _snapshot(self) -> ReliabilityAssuranceSnapshot:
        return self.service.snapshot(
            review_paths=self.review_paths,
            decision_paths=self.decision_paths,
            assurance_window_days=self.window_days.value(),
        )

    def refresh(self) -> ReliabilityAssuranceSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        self.review_summary.setText(f"{len(self.review_paths)} selected")
        self.decision_summary.setText(f"{len(self.decision_paths)} selected")
        tone = "error" if snapshot.blocker_count else "warning" if snapshot.warning_count else "success"
        self.status_card.update_status(snapshot.status_summary, snapshot.status, tone=tone)
        values = {
            "pairs": snapshot.verified_pair_count,
            "closed": snapshot.close_effective_count,
            "monitoring": snapshot.monitoring_count,
            "escalation": snapshot.escalation_count,
            "risk": snapshot.accepted_risk_count,
            "exceptions": snapshot.open_exception_count,
        }
        for key, value in values.items():
            self.metric_labels[key].setText(str(value))
        self._render_exceptions(snapshot)
        self._render_gates(snapshot)
        self.create_button.setEnabled(snapshot.assurance_allowed)
        return snapshot

    def _render_exceptions(self, snapshot: ReliabilityAssuranceSnapshot) -> None:
        self.exception_table.setRowCount(len(snapshot.exceptions))
        for row, item in enumerate(snapshot.exceptions):
            values = (
                item.severity,
                item.category,
                item.summary,
                item.source_decision,
                str(item.age_days),
                item.review_id,
                item.status,
            )
            for column, value in enumerate(values):
                self.exception_table.setItem(row, column, QTableWidgetItem(value))
        self.exception_table.resizeColumnsToContents()

    def _render_gates(self, snapshot: ReliabilityAssuranceSnapshot) -> None:
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (gate.status, gate.label, gate.severity, gate.detail, gate.remediation)
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))
        self.gate_table.resizeColumnsToContents()

    def export_snapshot(self) -> None:
        snapshot = self.refresh()
        path = self.service.export_snapshot(snapshot)
        QMessageBox.information(self, "Snapshot exported", str(path))
        if self.open_path:
            self.open_path(path)

    def create_assurance(self) -> None:
        snapshot = self.refresh()
        result = self.service.create_assurance(
            snapshot,
            decision=self.outcome.currentText(),
            owner=self.owner.text(),
            statement=self.statement.toPlainText(),
            exception_owner=self.exception_owner.text(),
            next_review_date=self.next_review.text(),
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self,
                "Assurance not created",
                f"{result.get('status')}: {result.get('detail')}",
            )
            return
        self.latest_record = result
        QMessageBox.information(
            self,
            "Reliability assurance created",
            f"Attestation:\n{result.attestation_path}\n\nAudit pack:\n{result.audit_pack_path}",
        )
        if self.open_path:
            self.open_path(result.audit_pack_path)
