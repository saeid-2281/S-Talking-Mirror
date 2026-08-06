from __future__ import annotations

from datetime import datetime, timezone
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
from app.models.capacity_readiness import CapacityDecisionRecord, CapacityReadinessSnapshot
from app.services.capacity_readiness_service import CapacityReadinessService


class CapacityReadinessDialog(QDialog):
    """Human-controlled capacity forecast and degradation-readiness workspace."""

    def __init__(
        self,
        service: CapacityReadinessService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.observation_paths = list(service.default_observation_paths())
        self.slo_snapshot_paths = list(service.default_slo_snapshot_paths())
        self.slo_decision_paths = list(service.default_slo_decision_paths())
        self.slo_pack_paths = list(service.default_slo_pack_paths())
        self.slo_receipt_paths = list(service.default_slo_receipt_paths())
        self.current_snapshot: CapacityReadinessSnapshot | None = None
        self.latest_decision: CapacityDecisionRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("capacityReadinessDialog")
        self.setWindowTitle("Capacity forecast & degradation readiness")
        self.resize(1440, 960)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Capacity forecast, saturation guard & degradation readiness",
            "Combine aggregate capacity observations with verified Phase 71 SLO evidence. The workspace records local human decisions and never scales, sheds load, changes queues, deploys or restarts automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        policy = DialogSection(
            "Forecast policy and verified sources",
            "Select aggregate observations and matching Phase 71 snapshot, decision, audit-pack and receipt sets.",
        )
        policy_widget = QWidget()
        form = QFormLayout(policy_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.observation_summary = self._source_row(
            form, "Capacity observations", self.select_observations
        )
        self.slo_snapshot_summary = self._source_row(
            form, "SLO snapshots", self.select_slo_snapshots
        )
        self.slo_decision_summary = self._source_row(
            form, "SLO decisions", self.select_slo_decisions
        )
        self.slo_pack_summary = self._source_row(
            form, "SLO packs", self.select_slo_packs
        )
        self.slo_receipt_summary = self._source_row(
            form, "SLO receipts", self.select_slo_receipts
        )
        self.forecast_days = QSpinBox()
        self.forecast_days.setObjectName("capacityForecastDays")
        self.forecast_days.setRange(
            self.service.MIN_FORECAST_DAYS,
            self.service.MAX_FORECAST_DAYS,
        )
        self.forecast_days.setValue(self.service.DEFAULT_FORECAST_DAYS)
        form.addRow("Forecast horizon", self.forecast_days)
        self.minimum_headroom = QDoubleSpinBox()
        self.minimum_headroom.setObjectName("capacityMinimumHeadroom")
        self.minimum_headroom.setRange(
            self.service.MINIMUM_HEADROOM_LIMIT,
            self.service.MAXIMUM_HEADROOM_LIMIT,
        )
        self.minimum_headroom.setDecimals(2)
        self.minimum_headroom.setValue(
            self.service.DEFAULT_MINIMUM_HEADROOM_PERCENT
        )
        self.minimum_headroom.setSuffix(" %")
        form.addRow("Minimum headroom", self.minimum_headroom)
        policy.add_widget(policy_widget)
        self.workspace.add_body_widget(policy)

        self.status_card = DialogStatusCard("Checking capacity gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        metrics = DialogSection(
            "Conservative capacity forecast",
            "Worst observed values and projected peak demand.",
        )
        metrics_widget = QWidget()
        metrics_layout = QHBoxLayout(metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_labels: dict[str, QLabel] = {}
        for key, label in (
            ("headroom", "Current headroom"),
            ("projected", "Projected headroom"),
            ("saturation", "Days to saturation"),
            ("queue", "Queue depth"),
            ("worker", "Worker utilization"),
            ("gate", "Release gate"),
        ):
            card = DialogStatusCard(label, "—", tone="info")
            self.metric_labels[key] = card.detail_label
            metrics_layout.addWidget(card, 1)
        metrics.add_widget(metrics_widget)
        self.workspace.add_body_widget(metrics)

        gates = DialogSection(
            "Capacity and release-safety gates",
            "Blockers force a hold. Warnings require a reviewed scale or degraded-mode decision.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("capacityGateTable")
        self.gate_table.setAccessibleName("Capacity readiness gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Detail", "Remediation"]
        )
        self._configure_table(self.gate_table)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        observation = DialogSection(
            "Create human-reviewed capacity observation",
            "Record aggregate counters only. Do not include credentials, filenames, project text or local paths.",
        )
        observation_widget = QWidget()
        observation_form = QFormLayout(observation_widget)
        observation_form.setContentsMargins(0, 0, 0, 0)
        self.captured_at = QLineEdit(datetime.now(timezone.utc).isoformat())
        self.captured_at.setObjectName("capacityCapturedAt")
        observation_form.addRow("Captured at", self.captured_at)
        self.interval_minutes = self._spin(1, 10080, 60, "capacityIntervalMinutes")
        observation_form.addRow("Observation interval", self.interval_minutes)
        self.current_load = self._spin(0, 1000000000, 500, "capacityCurrentLoad")
        observation_form.addRow("Current load/min", self.current_load)
        self.peak_load = self._spin(0, 1000000000, 600, "capacityPeakLoad")
        observation_form.addRow("Peak load/min", self.peak_load)
        self.sustainable_capacity = self._spin(
            1, 1000000000, 1000, "capacitySustainableLimit"
        )
        observation_form.addRow("Sustainable capacity/min", self.sustainable_capacity)
        self.queue_depth = self._spin(0, 100000000, 0, "capacityQueueDepth")
        observation_form.addRow("Queue depth", self.queue_depth)
        self.worker_utilization = self._percent("capacityWorkerUtilization", 50.0)
        observation_form.addRow("Worker utilization", self.worker_utilization)
        self.memory_utilization = self._percent("capacityMemoryUtilization", 55.0)
        observation_form.addRow("Memory utilization", self.memory_utilization)
        self.provider_throttle = self._percent("capacityProviderThrottle", 0.0)
        observation_form.addRow("Provider throttle", self.provider_throttle)
        self.daily_growth = QDoubleSpinBox()
        self.daily_growth.setObjectName("capacityDailyGrowth")
        self.daily_growth.setRange(-100.0, 1000.0)
        self.daily_growth.setDecimals(4)
        self.daily_growth.setValue(0.2)
        self.daily_growth.setSuffix(" %/day")
        observation_form.addRow("Demand growth", self.daily_growth)
        self.observation_owner = QLineEdit()
        self.observation_owner.setObjectName("capacityObservationOwner")
        self.observation_owner.setPlaceholderText("Human observation owner")
        observation_form.addRow("Owner", self.observation_owner)
        self.observation_notes = QTextEdit()
        self.observation_notes.setObjectName("capacityObservationNotes")
        self.observation_notes.setMinimumHeight(72)
        self.observation_notes.setPlaceholderText(
            "Describe the aggregate metric source without credentials or local paths."
        )
        observation_form.addRow("Notes", self.observation_notes)
        self.observation_acknowledge = QCheckBox(
            "I reviewed these aggregate metrics; create a local observation only."
        )
        self.observation_acknowledge.setObjectName("capacityObservationAcknowledge")
        observation_form.addRow("", self.observation_acknowledge)
        create_observation = QPushButton("Create observation")
        create_observation.setIcon(action_icon("save"))
        create_observation.clicked.connect(self.create_observation)
        observation_form.addRow("", create_observation)
        observation.add_widget(observation_widget)
        self.workspace.add_body_widget(observation)

        decision = DialogSection(
            "Human capacity decision",
            "The calculated gate cannot be bypassed. No scale, queue, deployment or degraded-mode action is executed automatically.",
        )
        decision_widget = QWidget()
        decision_form = QFormLayout(decision_widget)
        decision_form.setContentsMargins(0, 0, 0, 0)
        self.decision = QComboBox()
        self.decision.setObjectName("capacityDecision")
        self.decision.addItems(self.service.DECISIONS)
        decision_form.addRow("Decision", self.decision)
        self.decision_owner = QLineEdit()
        self.decision_owner.setObjectName("capacityDecisionOwner")
        decision_form.addRow("Owner", self.decision_owner)
        self.decision_statement = QTextEdit()
        self.decision_statement.setObjectName("capacityDecisionStatement")
        self.decision_statement.setMinimumHeight(72)
        decision_form.addRow("Statement", self.decision_statement)
        self.decision_acknowledge = QCheckBox(
            "I reviewed the gates; record a local human decision only."
        )
        self.decision_acknowledge.setObjectName("capacityDecisionAcknowledge")
        decision_form.addRow("", self.decision_acknowledge)
        self.create_decision_button = QPushButton("Create decision and audit pack")
        self.create_decision_button.setIcon(action_icon("save"))
        self.create_decision_button.clicked.connect(self.create_decision)
        decision_form.addRow("", self.create_decision_button)
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
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        self.workspace.add_footer_widget(close)

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int, name: str) -> QSpinBox:
        widget = QSpinBox()
        widget.setObjectName(name)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    @staticmethod
    def _percent(name: str, value: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setObjectName(name)
        widget.setRange(0.0, 100.0)
        widget.setDecimals(2)
        widget.setValue(value)
        widget.setSuffix(" %")
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
        button = QPushButton("Select…")
        button.clicked.connect(callback)
        layout.addWidget(summary, 1)
        layout.addWidget(button)
        form.addRow(label, row)
        return summary

    def _select_files(self, title: str, directory: Path, pattern: str) -> list[Path]:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            title,
            str(directory),
            pattern,
        )
        return [Path(path) for path in paths]

    def select_observations(self) -> None:
        paths = self._select_files(
            "Select capacity observations",
            self.service.observations_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.observation_paths = paths
            self.refresh()

    def select_slo_snapshots(self) -> None:
        paths = self._select_files(
            "Select Phase 71 SLO snapshots",
            self.service.service_level_objectives_service.snapshots_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.slo_snapshot_paths = paths
            self.refresh()

    def select_slo_decisions(self) -> None:
        paths = self._select_files(
            "Select Phase 71 SLO decisions",
            self.service.service_level_objectives_service.decisions_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.slo_decision_paths = paths
            self.refresh()

    def select_slo_packs(self) -> None:
        paths = self._select_files(
            "Select Phase 71 SLO audit packs",
            self.service.service_level_objectives_service.audit_packs_dir,
            "ZIP files (*.zip)",
        )
        if paths:
            self.slo_pack_paths = paths
            self.refresh()

    def select_slo_receipts(self) -> None:
        paths = self._select_files(
            "Select Phase 71 SLO receipts",
            self.service.service_level_objectives_service.receipts_dir,
            "JSON files (*.json)",
        )
        if paths:
            self.slo_receipt_paths = paths
            self.refresh()

    def refresh(self) -> None:
        self.observation_summary.setText(f"{len(self.observation_paths)} selected")
        self.slo_snapshot_summary.setText(f"{len(self.slo_snapshot_paths)} selected")
        self.slo_decision_summary.setText(f"{len(self.slo_decision_paths)} selected")
        self.slo_pack_summary.setText(f"{len(self.slo_pack_paths)} selected")
        self.slo_receipt_summary.setText(f"{len(self.slo_receipt_paths)} selected")
        self.current_snapshot = self.service.snapshot(
            observation_paths=self.observation_paths,
            slo_snapshot_paths=self.slo_snapshot_paths,
            slo_decision_paths=self.slo_decision_paths,
            slo_pack_paths=self.slo_pack_paths,
            slo_receipt_paths=self.slo_receipt_paths,
            forecast_days=self.forecast_days.value(),
            minimum_headroom_percent=self.minimum_headroom.value(),
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
            "headroom": f"{snapshot.current_headroom_percent:.2f}%",
            "projected": f"{snapshot.projected_headroom_percent:.2f}%",
            "saturation": (
                "No growth"
                if snapshot.days_to_saturation is None
                else f"{snapshot.days_to_saturation:.1f} days"
            ),
            "queue": str(snapshot.max_queue_depth),
            "worker": f"{snapshot.max_worker_utilization_percent:.2f}%",
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
        index = self.decision.findText(snapshot.recommended_decision)
        if index >= 0:
            self.decision.setCurrentIndex(index)

    def create_observation(self) -> None:
        result = self.service.create_observation(
            captured_at=self.captured_at.text(),
            interval_minutes=self.interval_minutes.value(),
            current_load_per_minute=self.current_load.value(),
            peak_load_per_minute=self.peak_load.value(),
            sustainable_capacity_per_minute=self.sustainable_capacity.value(),
            queue_depth=self.queue_depth.value(),
            worker_utilization_percent=self.worker_utilization.value(),
            memory_utilization_percent=self.memory_utilization.value(),
            provider_throttle_percent=self.provider_throttle.value(),
            daily_growth_percent=self.daily_growth.value(),
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
        self.refresh()
        assert self.current_snapshot is not None
        path = self.service.export_snapshot(self.current_snapshot)
        QMessageBox.information(self, "Snapshot exported", str(path))
        self._open_path(path)

    def create_decision(self) -> None:
        self.refresh()
        assert self.current_snapshot is not None
        result = self.service.create_decision(
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
