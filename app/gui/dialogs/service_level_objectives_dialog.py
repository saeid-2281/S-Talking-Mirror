from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
from app.models.service_level_objectives import (
    ServiceLevelDecisionRecord,
    ServiceLevelObjectivesSnapshot,
)
from app.services.service_level_objectives_service import ServiceLevelObjectivesService


class ServiceLevelObjectivesDialog(QDialog):
    """Human-controlled SLO, error-budget and release-safety workspace."""

    def __init__(
        self,
        service: ServiceLevelObjectivesService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.observation_paths = list(service.default_observation_paths())
        self.result_paths = list(service.default_continuity_result_paths())
        self.attestation_paths = list(
            service.default_continuity_attestation_paths()
        )
        self.pack_paths = list(service.default_continuity_pack_paths())
        self.receipt_paths = list(service.default_continuity_receipt_paths())
        self.current_snapshot: ServiceLevelObjectivesSnapshot | None = None
        self.latest_decision: ServiceLevelDecisionRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("serviceLevelObjectivesDialog")
        self.setWindowTitle("Service-level objectives & error budget")
        self.resize(1440, 960)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Service-level objectives, error budget & release safety",
            "Combine human-reviewed operational observations with verified Phase 70 continuity evidence. The workspace calculates SLOs and records a local human decision; it never deploys, rolls back, restarts or publishes automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        policy = DialogSection(
            "SLO policy and verified sources",
            "Select operational observations and one-to-one Phase 70 result, attestation, audit-pack and receipt sets.",
        )
        policy_widget = QWidget()
        form = QFormLayout(policy_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.observation_summary = self._source_row(
            form,
            "Observations",
            "sloObservationSummary",
            self.select_observations,
        )
        self.result_summary = self._source_row(
            form,
            "Continuity results",
            "sloResultSummary",
            self.select_results,
        )
        self.attestation_summary = self._source_row(
            form,
            "Continuity attestations",
            "sloAttestationSummary",
            self.select_attestations,
        )
        self.pack_summary = self._source_row(
            form,
            "Continuity packs",
            "sloPackSummary",
            self.select_packs,
        )
        self.receipt_summary = self._source_row(
            form,
            "Continuity receipts",
            "sloReceiptSummary",
            self.select_receipts,
        )
        self.window_days = QSpinBox()
        self.window_days.setObjectName("sloWindowDays")
        self.window_days.setRange(self.service.MIN_WINDOW_DAYS, self.service.MAX_WINDOW_DAYS)
        self.window_days.setValue(self.service.DEFAULT_WINDOW_DAYS)
        form.addRow("SLO window", self.window_days)
        self.availability_target = QDoubleSpinBox()
        self.availability_target.setObjectName("sloAvailabilityTarget")
        self.availability_target.setRange(
            self.service.MIN_PERCENT_TARGET,
            self.service.MAX_PERCENT_TARGET,
        )
        self.availability_target.setDecimals(3)
        self.availability_target.setValue(self.service.DEFAULT_AVAILABILITY_TARGET)
        self.availability_target.setSuffix(" %")
        form.addRow("Availability target", self.availability_target)
        self.success_target = QDoubleSpinBox()
        self.success_target.setObjectName("sloSuccessTarget")
        self.success_target.setRange(
            self.service.MIN_PERCENT_TARGET,
            self.service.MAX_PERCENT_TARGET,
        )
        self.success_target.setDecimals(3)
        self.success_target.setValue(self.service.DEFAULT_SUCCESS_TARGET)
        self.success_target.setSuffix(" %")
        form.addRow("Success target", self.success_target)
        self.latency_target = QSpinBox()
        self.latency_target.setObjectName("sloLatencyTarget")
        self.latency_target.setRange(
            self.service.MIN_LATENCY_TARGET_MS,
            self.service.MAX_LATENCY_TARGET_MS,
        )
        self.latency_target.setValue(self.service.DEFAULT_P95_LATENCY_TARGET_MS)
        self.latency_target.setSuffix(" ms")
        form.addRow("P95 latency target", self.latency_target)
        policy.add_widget(policy_widget)
        self.workspace.add_body_widget(policy)

        self.status_card = DialogStatusCard("Checking SLO gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        metrics = DialogSection(
            "Calculated service level",
            "Conservative aggregate metrics and availability error-budget consumption.",
        )
        metrics_widget = QWidget()
        metrics_layout = QHBoxLayout(metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_labels: dict[str, QLabel] = {}
        for key, label in (
            ("availability", "Availability"),
            ("success", "Success"),
            ("latency", "P95 latency"),
            ("budget", "Budget remaining"),
            ("burn", "Burn rate"),
            ("gate", "Release gate"),
        ):
            card = DialogStatusCard(label, "—", tone="info")
            self.metric_labels[key] = card.detail_label
            metrics_layout.addWidget(card, 1)
        metrics.add_widget(metrics_widget)
        self.workspace.add_body_widget(metrics)

        gates = DialogSection(
            "SLO and release-safety gates",
            "Blockers force a hold. Warnings require explicit human review.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("sloGateTable")
        self.gate_table.setAccessibleName("Service-level objective gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Detail", "Remediation"]
        )
        self._configure_table(self.gate_table)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        observation = DialogSection(
            "Create human-reviewed observation",
            "Record aggregate counters only. Do not include project text, credentials, filenames or local paths.",
        )
        observation_widget = QWidget()
        observation_form = QFormLayout(observation_widget)
        observation_form.setContentsMargins(0, 0, 0, 0)
        now = datetime.now(timezone.utc)
        self.observation_start = QLineEdit((now - timedelta(days=30)).isoformat())
        self.observation_start.setObjectName("sloObservationStart")
        observation_form.addRow("Window start", self.observation_start)
        self.observation_end = QLineEdit(now.isoformat())
        self.observation_end.setObjectName("sloObservationEnd")
        observation_form.addRow("Window end", self.observation_end)
        self.total_operations = QSpinBox()
        self.total_operations.setObjectName("sloTotalOperations")
        self.total_operations.setRange(0, 1000000000)
        self.total_operations.setValue(1000)
        observation_form.addRow("Total operations", self.total_operations)
        self.failed_operations = QSpinBox()
        self.failed_operations.setObjectName("sloFailedOperations")
        self.failed_operations.setRange(0, 1000000000)
        observation_form.addRow("Failed operations", self.failed_operations)
        self.unavailable_minutes = QSpinBox()
        self.unavailable_minutes.setObjectName("sloUnavailableMinutes")
        self.unavailable_minutes.setRange(0, 525600)
        observation_form.addRow("Unavailable minutes", self.unavailable_minutes)
        self.observed_latency = QSpinBox()
        self.observed_latency.setObjectName("sloObservedLatency")
        self.observed_latency.setRange(0, self.service.MAX_LATENCY_TARGET_MS)
        self.observed_latency.setValue(500)
        self.observed_latency.setSuffix(" ms")
        observation_form.addRow("Observed P95 latency", self.observed_latency)
        self.observation_owner = QLineEdit()
        self.observation_owner.setObjectName("sloObservationOwner")
        self.observation_owner.setPlaceholderText("Human observation owner")
        observation_form.addRow("Owner", self.observation_owner)
        self.observation_notes = QTextEdit()
        self.observation_notes.setObjectName("sloObservationNotes")
        self.observation_notes.setAccessibleName("Privacy-safe SLO observation notes")
        self.observation_notes.setPlaceholderText(
            "Describe the aggregate metric source without credentials or local paths."
        )
        self.observation_notes.setMinimumHeight(72)
        observation_form.addRow("Notes", self.observation_notes)
        self.observation_acknowledge = QCheckBox(
            "I reviewed the aggregate metrics; create a local observation only."
        )
        self.observation_acknowledge.setObjectName("sloObservationAcknowledge")
        observation_form.addRow("", self.observation_acknowledge)
        create_observation = QPushButton("Create observation")
        create_observation.setIcon(action_icon("save"))
        create_observation.clicked.connect(self.create_observation)
        observation_form.addRow("", create_observation)
        observation.add_widget(observation_widget)
        self.workspace.add_body_widget(observation)

        decision = DialogSection(
            "Human release-safety decision",
            "The calculated gate cannot be overridden. No release action is executed automatically.",
        )
        decision_widget = QWidget()
        decision_form = QFormLayout(decision_widget)
        decision_form.setContentsMargins(0, 0, 0, 0)
        self.decision = QComboBox()
        self.decision.setObjectName("sloDecision")
        self.decision.addItems(self.service.DECISIONS)
        decision_form.addRow("Decision", self.decision)
        self.decision_owner = QLineEdit()
        self.decision_owner.setObjectName("sloDecisionOwner")
        self.decision_owner.setPlaceholderText("Human release owner")
        decision_form.addRow("Owner", self.decision_owner)
        self.decision_statement = QTextEdit()
        self.decision_statement.setObjectName("sloDecisionStatement")
        self.decision_statement.setAccessibleName("Privacy-safe SLO decision statement")
        self.decision_statement.setPlaceholderText(
            "Summarize the human release-safety decision without credentials or local paths."
        )
        self.decision_statement.setMinimumHeight(80)
        decision_form.addRow("Statement", self.decision_statement)
        self.decision_acknowledge = QCheckBox(
            "I reviewed every gate; create local immutable evidence only."
        )
        self.decision_acknowledge.setObjectName("sloDecisionAcknowledge")
        decision_form.addRow("", self.decision_acknowledge)
        decision.add_widget(decision_widget)
        self.workspace.add_body_widget(decision)

        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        self.workspace.add_footer_widget(refresh)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        self.workspace.add_footer_widget(export)
        self.create_decision_button = QPushButton("Create decision audit pack")
        self.create_decision_button.setObjectName("sloCreateDecisionButton")
        self.create_decision_button.setIcon(action_icon("report"))
        self.create_decision_button.clicked.connect(self.create_decision)
        self.workspace.add_footer_widget(self.create_decision_button)

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

    def _select_files(self, title: str, directory: Path, pattern: str) -> list[Path]:
        paths, _ = QFileDialog.getOpenFileNames(self, title, str(directory), pattern)
        return [Path(path) for path in paths]

    def select_observations(self) -> None:
        paths = self._select_files(
            "Select SLO observations",
            self.service.observations_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.observation_paths = paths
            self.refresh()

    def select_results(self) -> None:
        paths = self._select_files(
            "Select Phase 70 continuity results",
            self.service.service_continuity_service.results_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.result_paths = paths
            self.refresh()

    def select_attestations(self) -> None:
        paths = self._select_files(
            "Select Phase 70 continuity attestations",
            self.service.service_continuity_service.attestations_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.attestation_paths = paths
            self.refresh()

    def select_packs(self) -> None:
        paths = self._select_files(
            "Select Phase 70 continuity audit packs",
            self.service.service_continuity_service.audit_packs_dir,
            "ZIP files (*.zip)",
        )
        if paths:
            self.pack_paths = paths
            self.refresh()

    def select_receipts(self) -> None:
        paths = self._select_files(
            "Select Phase 70 continuity receipts",
            self.service.service_continuity_service.receipts_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.receipt_paths = paths
            self.refresh()

    def refresh(self) -> None:
        self.observation_summary.setText(f"{len(self.observation_paths)} selected")
        self.result_summary.setText(f"{len(self.result_paths)} selected")
        self.attestation_summary.setText(f"{len(self.attestation_paths)} selected")
        self.pack_summary.setText(f"{len(self.pack_paths)} selected")
        self.receipt_summary.setText(f"{len(self.receipt_paths)} selected")
        self.current_snapshot = self.service.snapshot(
            observation_paths=self.observation_paths,
            continuity_result_paths=self.result_paths,
            continuity_attestation_paths=self.attestation_paths,
            continuity_pack_paths=self.pack_paths,
            continuity_receipt_paths=self.receipt_paths,
            window_days=self.window_days.value(),
            availability_target_percent=self.availability_target.value(),
            success_target_percent=self.success_target.value(),
            p95_latency_target_ms=self.latency_target.value(),
        )
        snapshot = self.current_snapshot
        tone = (
            "danger"
            if snapshot.blocker_count
            else "warning"
            if snapshot.warning_count
            else "success"
        )
        self.status_card.update_status(
            snapshot.status.replace("_", " ").title(),
            snapshot.status_summary,
            tone=tone,
        )
        values = {
            "availability": f"{snapshot.availability_percent:.4f}%",
            "success": f"{snapshot.success_percent:.4f}%",
            "latency": f"{snapshot.p95_latency_ms} ms",
            "budget": f"{snapshot.error_budget_remaining_minutes:.2f} min",
            "burn": f"{snapshot.error_budget_burn_rate:.3f}",
            "gate": snapshot.release_gate.replace("_", " ").title(),
        }
        for key, value in values.items():
            self.metric_labels[key].setText(value)
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.status, gate.label, gate.severity, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))
        self.create_decision_button.setEnabled(snapshot.decision_allowed)
        index = self.decision.findText(snapshot.release_gate)
        if index >= 0:
            self.decision.setCurrentIndex(index)

    def create_observation(self) -> None:
        total = self.total_operations.value()
        failed = self.failed_operations.value()
        result = self.service.create_observation(
            window_start=self.observation_start.text(),
            window_end=self.observation_end.text(),
            total_operations=total,
            successful_operations=max(0, total - failed),
            failed_operations=failed,
            unavailable_minutes=self.unavailable_minutes.value(),
            p95_latency_ms=self.observed_latency.value(),
            owner=self.observation_owner.text(),
            notes=self.observation_notes.toPlainText(),
            acknowledge=self.observation_acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            self._show_blocked("Observation", result)
            return
        self.observation_paths.append(result.observation_path)
        QMessageBox.information(self, "Observation created", str(result.observation_path))
        self.refresh()

    def export_snapshot(self) -> None:
        if self.current_snapshot is None:
            self.refresh()
        assert self.current_snapshot is not None
        path = self.service.export_snapshot(self.current_snapshot)
        QMessageBox.information(self, "Snapshot exported", str(path))
        self._open_path(path)

    def create_decision(self) -> None:
        self.refresh()
        assert self.current_snapshot is not None
        result = self.service.create_release_decision(
            self.current_snapshot,
            decision=self.decision.currentText(),
            owner=self.decision_owner.text(),
            statement=self.decision_statement.toPlainText(),
            acknowledge=self.decision_acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            self._show_blocked("Decision", result)
            return
        self.latest_decision = result
        QMessageBox.information(
            self,
            "Decision created",
            f"Decision: {result.decision_path}\nAudit pack: {result.audit_pack_path}\nReceipt: {result.receipt_path}",
        )
        self._open_path(result.audit_pack_path)

    def _show_blocked(self, title: str, result: dict[str, str]) -> None:
        detail = str(result.get("detail") or f"{title} was not created.")
        if result.get("status") == "dry_run":
            QMessageBox.information(self, f"{title} dry run", detail)
        else:
            QMessageBox.warning(self, f"{title} blocked", detail)

    def _open_path(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
