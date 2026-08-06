from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
from app.models.degradation_readiness import (
    DegradationDrillRecord,
    DegradationReadinessSnapshot,
)
from app.services.degradation_readiness_service import DegradationReadinessService


class DegradationReadinessDialog(QDialog):
    """Human-controlled degradation drill and recovery validation workspace."""

    def __init__(
        self,
        service: DegradationReadinessService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.plan_paths = list(service.default_plan_paths())
        self.capacity_snapshot_paths = list(service.default_capacity_snapshot_paths())
        self.capacity_decision_paths = list(service.default_capacity_decision_paths())
        self.capacity_pack_paths = list(service.default_capacity_pack_paths())
        self.capacity_receipt_paths = list(service.default_capacity_receipt_paths())
        self.current_snapshot: DegradationReadinessSnapshot | None = None
        self.latest_record: DegradationDrillRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("degradationReadinessDialog")
        self.setWindowTitle("Controlled degradation drill & recovery validation")
        self.resize(1440, 980)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Controlled degradation drill & recovery validation",
            "Create reviewed drill plans, verify Phase 72 capacity evidence and record observed recovery. This workspace never sheds production load, pauses queues, changes provider routing, scales workers, deploys or restarts automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        sources = DialogSection(
            "Verified evidence sources",
            "Select reviewed plans and matching Phase 72 capacity snapshot, decision, audit-pack and receipt sets.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.plan_summary = self._source_row(
            source_form, "Degradation plans", self.select_plans
        )
        self.capacity_snapshot_summary = self._source_row(
            source_form, "Capacity snapshots", self.select_capacity_snapshots
        )
        self.capacity_decision_summary = self._source_row(
            source_form, "Capacity decisions", self.select_capacity_decisions
        )
        self.capacity_pack_summary = self._source_row(
            source_form, "Capacity packs", self.select_capacity_packs
        )
        self.capacity_receipt_summary = self._source_row(
            source_form, "Capacity receipts", self.select_capacity_receipts
        )
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        plan_section = DialogSection(
            "Create a reviewed drill plan",
            "The plan records limits and recovery checks only. Execution remains manual and isolated.",
        )
        plan_widget = QWidget()
        plan_form = QFormLayout(plan_widget)
        plan_form.setContentsMargins(0, 0, 0, 0)
        self.scenario = QComboBox()
        self.scenario.setObjectName("degradationScenario")
        for value in self.service.SCENARIOS:
            self.scenario.addItem(value.replace("_", " ").title(), value)
        plan_form.addRow("Scenario", self.scenario)
        self.target_reduction = QDoubleSpinBox()
        self.target_reduction.setRange(
            self.service.MIN_REDUCTION_PERCENT,
            self.service.MAX_REDUCTION_PERCENT,
        )
        self.target_reduction.setValue(20.0)
        self.target_reduction.setSuffix(" %")
        plan_form.addRow("Target load reduction", self.target_reduction)
        self.max_queue = QSpinBox()
        self.max_queue.setRange(0, self.service.MAX_QUEUE_LIMIT)
        self.max_queue.setValue(100)
        plan_form.addRow("Maximum queue depth", self.max_queue)
        self.recovery_target = QSpinBox()
        self.recovery_target.setRange(
            self.service.MIN_RECOVERY_MINUTES,
            self.service.MAX_RECOVERY_MINUTES,
        )
        self.recovery_target.setValue(15)
        self.recovery_target.setSuffix(" min")
        plan_form.addRow("Recovery target", self.recovery_target)
        self.max_failed = QSpinBox()
        self.max_failed.setRange(0, self.service.MAX_FAILED_REQUEST_LIMIT)
        self.max_failed.setValue(0)
        plan_form.addRow("Maximum failed requests", self.max_failed)
        self.plan_owner = QLineEdit()
        self.plan_owner.setPlaceholderText("Human owner")
        plan_form.addRow("Owner", self.plan_owner)
        self.plan_notes = QTextEdit()
        self.plan_notes.setMaximumHeight(80)
        self.plan_notes.setPlaceholderText("Privacy-safe review notes")
        plan_form.addRow("Notes", self.plan_notes)
        self.plan_ack = QCheckBox("I reviewed this plan and want to record it locally")
        self.plan_ack.setObjectName("degradationPlanAcknowledge")
        plan_form.addRow("", self.plan_ack)
        create_plan = QPushButton(action_icon("save"), "Create reviewed plan")
        create_plan.clicked.connect(self.create_plan)
        plan_form.addRow("", create_plan)
        plan_section.add_widget(plan_widget)
        self.workspace.add_body_widget(plan_section)

        self.status_card = DialogStatusCard(
            "Checking degradation readiness", "", tone="info"
        )
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Readiness gates",
            "Capacity inheritance, plan custody and scenario coverage.",
        )
        self.gate_table = QTableWidget(0, 4)
        self.gate_table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Detail", "Remediation"]
        )
        self.gate_table.setObjectName("degradationReadinessGateTable")
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gate_table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        result_section = DialogSection(
            "Record observed drill result",
            "Measurements are compared with the selected plan. A failed drill is preserved as withheld evidence.",
        )
        result_widget = QWidget()
        result_form = QFormLayout(result_widget)
        result_form.setContentsMargins(0, 0, 0, 0)
        self.result_plan = QComboBox()
        self.result_plan.setObjectName("degradationResultPlan")
        result_form.addRow("Plan", self.result_plan)
        self.achieved_reduction = QDoubleSpinBox()
        self.achieved_reduction.setRange(0, 100)
        self.achieved_reduction.setValue(20.0)
        self.achieved_reduction.setSuffix(" %")
        result_form.addRow("Achieved load reduction", self.achieved_reduction)
        self.observed_queue = QSpinBox()
        self.observed_queue.setRange(0, self.service.MAX_QUEUE_LIMIT)
        result_form.addRow("Observed maximum queue", self.observed_queue)
        self.recovery_minutes = QSpinBox()
        self.recovery_minutes.setRange(0, self.service.MAX_RECOVERY_MINUTES * 4)
        self.recovery_minutes.setValue(10)
        self.recovery_minutes.setSuffix(" min")
        result_form.addRow("Observed recovery", self.recovery_minutes)
        self.failed_requests = QSpinBox()
        self.failed_requests.setRange(0, self.service.MAX_FAILED_REQUEST_LIMIT)
        result_form.addRow("Failed requests", self.failed_requests)
        self.data_loss = QSpinBox()
        self.data_loss.setRange(0, 100000)
        result_form.addRow("Data-loss count", self.data_loss)
        self.health_passed = QCheckBox("Health checks passed")
        self.health_passed.setChecked(True)
        result_form.addRow("", self.health_passed)
        self.tests_passed = QCheckBox("Dedicated regression tests passed")
        self.tests_passed.setChecked(True)
        result_form.addRow("", self.tests_passed)
        self.result_owner = QLineEdit()
        self.result_owner.setPlaceholderText("Human reviewer")
        result_form.addRow("Reviewer", self.result_owner)
        self.result_statement = QTextEdit()
        self.result_statement.setMaximumHeight(80)
        self.result_statement.setPlaceholderText("Privacy-safe outcome statement")
        result_form.addRow("Statement", self.result_statement)
        self.result_ack = QCheckBox(
            "I reviewed the measurements and want to record local evidence"
        )
        result_form.addRow("", self.result_ack)
        create_result = QPushButton(action_icon("save"), "Record drill result")
        create_result.clicked.connect(self.create_result)
        result_form.addRow("", create_result)
        result_section.add_widget(result_widget)
        self.workspace.add_body_widget(result_section)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Refresh")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        open_folder = QPushButton(action_icon("project.output_folder"), "Open evidence folder")
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

    def _select_json(self, title: str) -> list[Path]:
        files, _filter = QFileDialog.getOpenFileNames(
            self, title, str(self.service.root), "JSON files (*.json)"
        )
        return [Path(path) for path in files]

    def _select_zip(self, title: str) -> list[Path]:
        files, _filter = QFileDialog.getOpenFileNames(
            self, title, str(self.service.root), "ZIP files (*.zip)"
        )
        return [Path(path) for path in files]

    def select_plans(self) -> None:
        self.plan_paths = self._select_json("Select degradation plans")
        self.refresh()

    def select_capacity_snapshots(self) -> None:
        self.capacity_snapshot_paths = self._select_json("Select capacity snapshots")
        self.refresh()

    def select_capacity_decisions(self) -> None:
        self.capacity_decision_paths = self._select_json("Select capacity decisions")
        self.refresh()

    def select_capacity_packs(self) -> None:
        self.capacity_pack_paths = self._select_zip("Select capacity audit packs")
        self.refresh()

    def select_capacity_receipts(self) -> None:
        self.capacity_receipt_paths = self._select_json("Select capacity receipts")
        self.refresh()

    def create_plan(self) -> None:
        result = self.service.create_plan(
            scenario=str(self.scenario.currentData()),
            target_load_reduction_percent=self.target_reduction.value(),
            max_queue_depth=self.max_queue.value(),
            recovery_target_minutes=self.recovery_target.value(),
            max_failed_requests=self.max_failed.value(),
            owner=self.plan_owner.text(),
            notes=self.plan_notes.toPlainText(),
            acknowledge=self.plan_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(self, "Plan not recorded", result.get("detail", "Blocked"))
            return
        self.plan_paths.append(result.plan_path)
        self.plan_ack.setChecked(False)
        QMessageBox.information(self, "Plan recorded", str(result.plan_path))
        self.refresh()

    def refresh(self) -> None:
        self.plan_summary.setText(f"{len(self.plan_paths)} selected")
        self.capacity_snapshot_summary.setText(
            f"{len(self.capacity_snapshot_paths)} selected"
        )
        self.capacity_decision_summary.setText(
            f"{len(self.capacity_decision_paths)} selected"
        )
        self.capacity_pack_summary.setText(f"{len(self.capacity_pack_paths)} selected")
        self.capacity_receipt_summary.setText(
            f"{len(self.capacity_receipt_paths)} selected"
        )
        self.current_snapshot = self.service.snapshot(
            plan_paths=self.plan_paths,
            capacity_snapshot_paths=self.capacity_snapshot_paths,
            capacity_decision_paths=self.capacity_decision_paths,
            capacity_pack_paths=self.capacity_pack_paths,
            capacity_receipt_paths=self.capacity_receipt_paths,
        )
        tone = {
            "ready": "success",
            "ready_with_warnings": "warning",
            "blocked": "danger",
        }.get(self.current_snapshot.status, "info")
        self.status_card.set_status(
            self.current_snapshot.status.replace("_", " ").title(),
            self.current_snapshot.status_summary,
            tone=tone,
        )
        self.gate_table.setRowCount(len(self.current_snapshot.gates))
        for row, gate in enumerate(self.current_snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        selected = self.result_plan.currentData()
        self.result_plan.clear()
        for path in self.plan_paths:
            self.result_plan.addItem(path.stem.replace("degradation-plan-", "Plan "), path)
        if selected is not None:
            index = self.result_plan.findData(selected)
            if index >= 0:
                self.result_plan.setCurrentIndex(index)

    def create_result(self) -> None:
        if self.current_snapshot is None or self.result_plan.currentData() is None:
            QMessageBox.warning(self, "No plan", "Select or create a reviewed plan first.")
            return
        result = self.service.create_drill_result(
            self.current_snapshot,
            plan_path=Path(self.result_plan.currentData()),
            achieved_load_reduction_percent=self.achieved_reduction.value(),
            observed_max_queue_depth=self.observed_queue.value(),
            recovery_minutes=self.recovery_minutes.value(),
            failed_requests=self.failed_requests.value(),
            data_loss_count=self.data_loss.value(),
            health_checks_passed=self.health_passed.isChecked(),
            dedicated_tests_passed=self.tests_passed.isChecked(),
            owner=self.result_owner.text(),
            statement=self.result_statement.toPlainText(),
            acknowledge=self.result_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(
                self, "Result not recorded", result.get("detail", "Blocked")
            )
            return
        self.latest_record = result
        self.result_ack.setChecked(False)
        QMessageBox.information(
            self,
            "Drill evidence recorded",
            f"Outcome: {result.outcome_status}\n{result.audit_pack_path}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
