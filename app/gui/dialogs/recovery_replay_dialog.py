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
from app.models.recovery_replay import RecoveryReplayRecord, RecoveryReplaySnapshot
from app.services.recovery_replay_service import RecoveryReplayService


class RecoveryReplayDialog(QDialog):
    """Human-reviewed queue replay, duplicate and billing safety workspace."""

    def __init__(
        self,
        service: RecoveryReplayService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.plan_paths = list(service.default_plan_paths())
        self.degradation_result_paths = list(
            service.default_degradation_result_paths()
        )
        self.degradation_attestation_paths = list(
            service.default_degradation_attestation_paths()
        )
        self.degradation_pack_paths = list(service.default_degradation_pack_paths())
        self.degradation_receipt_paths = list(
            service.default_degradation_receipt_paths()
        )
        self.current_snapshot: RecoveryReplaySnapshot | None = None
        self.latest_record: RecoveryReplayRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("recoveryReplayDialog")
        self.setWindowTitle("Recovery replay integrity & duplicate prevention")
        self.resize(1440, 980)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Recovery replay integrity & duplicate prevention",
            "Verify Phase 73 recovery evidence, define replay safety limits and record observed queue replay results. This workspace never resumes queues, retries jobs, switches providers, deletes artifacts or performs billing actions automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        sources = DialogSection(
            "Verified evidence sources",
            "Select reviewed replay plans and matching Phase 73 result, attestation, audit-pack and receipt sets.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.plan_summary = self._source_row(source_form, "Replay plans", self.select_plans)
        self.result_summary = self._source_row(
            source_form, "Degradation results", self.select_results
        )
        self.attestation_summary = self._source_row(
            source_form, "Degradation attestations", self.select_attestations
        )
        self.pack_summary = self._source_row(
            source_form, "Degradation packs", self.select_packs
        )
        self.receipt_summary = self._source_row(
            source_form, "Degradation receipts", self.select_receipts
        )
        sources.add_widget(source_widget)
        self.workspace.add_body_widget(sources)

        plan_section = DialogSection(
            "Create a reviewed recovery replay plan",
            "Limits protect exactly-once output, receipt continuity and billing safety. Execution remains manual.",
        )
        plan_widget = QWidget()
        plan_form = QFormLayout(plan_widget)
        plan_form.setContentsMargins(0, 0, 0, 0)
        self.expected_jobs = self._spin(1, self.service.MAX_JOB_COUNT, 10)
        plan_form.addRow("Expected jobs", self.expected_jobs)
        self.recovery_target = self._spin(
            1, self.service.MAX_RECOVERY_MINUTES, 15, " min"
        )
        plan_form.addRow("Recovery target", self.recovery_target)
        self.max_duplicate_requests = self._spin(
            0, self.service.MAX_DUPLICATE_LIMIT, 0
        )
        plan_form.addRow("Maximum duplicate API requests", self.max_duplicate_requests)
        self.max_duplicate_outputs = self._spin(
            0, self.service.MAX_DUPLICATE_LIMIT, 0
        )
        plan_form.addRow("Maximum duplicate outputs", self.max_duplicate_outputs)
        self.max_orphans = self._spin(0, self.service.MAX_ARTIFACT_LIMIT, 0)
        plan_form.addRow("Maximum orphan artifacts", self.max_orphans)
        self.max_manifest_mismatches = self._spin(
            0, self.service.MAX_ARTIFACT_LIMIT, 0
        )
        plan_form.addRow("Maximum manifest mismatches", self.max_manifest_mismatches)
        self.max_cost_variance = QDoubleSpinBox()
        self.max_cost_variance.setRange(0, self.service.MAX_COST_VARIANCE_PERCENT)
        self.max_cost_variance.setDecimals(2)
        self.max_cost_variance.setValue(1.0)
        self.max_cost_variance.setSuffix(" %")
        plan_form.addRow("Maximum cost variance", self.max_cost_variance)
        self.plan_owner = QLineEdit()
        self.plan_owner.setPlaceholderText("Human owner")
        plan_form.addRow("Owner", self.plan_owner)
        self.plan_notes = QTextEdit()
        self.plan_notes.setMaximumHeight(80)
        self.plan_notes.setPlaceholderText("Privacy-safe review notes")
        plan_form.addRow("Notes", self.plan_notes)
        self.plan_ack = QCheckBox("I reviewed these limits and want to record them locally")
        self.plan_ack.setObjectName("recoveryReplayPlanAcknowledge")
        plan_form.addRow("", self.plan_ack)
        create_plan = QPushButton(action_icon("save"), "Create reviewed plan")
        create_plan.clicked.connect(self.create_plan)
        plan_form.addRow("", create_plan)
        plan_section.add_widget(plan_widget)
        self.workspace.add_body_widget(plan_section)

        self.status_card = DialogStatusCard("Checking recovery replay readiness", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Readiness gates",
            "Plan custody, degradation evidence integrity and verified recovery state.",
        )
        self.gate_table = QTableWidget(0, 4)
        self.gate_table.setHorizontalHeaderLabels(
            ["Gate", "Status", "Detail", "Remediation"]
        )
        self.gate_table.setObjectName("recoveryReplayGateTable")
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gate_table.horizontalHeader().setStretchLastSection(True)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        result_section = DialogSection(
            "Record observed recovery replay result",
            "Measurements are compared with the reviewed plan. Failed evidence is preserved as withheld.",
        )
        result_widget = QWidget()
        result_form = QFormLayout(result_widget)
        result_form.setContentsMargins(0, 0, 0, 0)
        self.result_plan = QLineEdit()
        self.result_plan.setReadOnly(True)
        self.result_plan.setPlaceholderText("Select a replay plan through the source picker")
        result_form.addRow("Plan", self.result_plan)
        self.attempted_jobs = self._spin(0, self.service.MAX_JOB_COUNT, 10)
        result_form.addRow("Attempted jobs", self.attempted_jobs)
        self.resumed_jobs = self._spin(0, self.service.MAX_JOB_COUNT, 10)
        result_form.addRow("Resumed jobs", self.resumed_jobs)
        self.completed_jobs = self._spin(0, self.service.MAX_JOB_COUNT, 10)
        result_form.addRow("Completed jobs", self.completed_jobs)
        self.duplicate_requests = self._spin(0, self.service.MAX_DUPLICATE_LIMIT, 0)
        result_form.addRow("Duplicate API requests", self.duplicate_requests)
        self.duplicate_outputs = self._spin(0, self.service.MAX_DUPLICATE_LIMIT, 0)
        result_form.addRow("Duplicate outputs", self.duplicate_outputs)
        self.orphan_artifacts = self._spin(0, self.service.MAX_ARTIFACT_LIMIT, 0)
        result_form.addRow("Orphan artifacts", self.orphan_artifacts)
        self.manifest_mismatches = self._spin(0, self.service.MAX_ARTIFACT_LIMIT, 0)
        result_form.addRow("Manifest mismatches", self.manifest_mismatches)
        self.cost_variance = QDoubleSpinBox()
        self.cost_variance.setRange(0, self.service.MAX_COST_VARIANCE_PERCENT)
        self.cost_variance.setDecimals(2)
        self.cost_variance.setSuffix(" %")
        result_form.addRow("Observed cost variance", self.cost_variance)
        self.recovery_minutes = self._spin(
            0, self.service.MAX_RECOVERY_MINUTES * 4, 10, " min"
        )
        result_form.addRow("Observed recovery", self.recovery_minutes)
        self.receipt_verified = QCheckBox("Execution receipt chain verified")
        self.receipt_verified.setChecked(True)
        result_form.addRow("", self.receipt_verified)
        self.checksums_verified = QCheckBox("Output checksums verified")
        self.checksums_verified.setChecked(True)
        result_form.addRow("", self.checksums_verified)
        self.tests_passed = QCheckBox("Dedicated recovery tests passed")
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
        record = QPushButton(action_icon("save"), "Record replay result")
        record.clicked.connect(self.create_result)
        result_form.addRow("", record)
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

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        if suffix:
            widget.setSuffix(suffix)
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
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self, title, str(self.service.root), filter_text
        )
        return [Path(path) for path in paths]

    def select_plans(self) -> None:
        paths = self._select("Select recovery replay plans", "JSON files (*.json)")
        if paths:
            self.plan_paths = paths
            self.refresh()

    def select_results(self) -> None:
        paths = self._select("Select Phase 73 results", "JSON files (*.json)")
        if paths:
            self.degradation_result_paths = paths
            self.refresh()

    def select_attestations(self) -> None:
        paths = self._select("Select Phase 73 attestations", "JSON files (*.json)")
        if paths:
            self.degradation_attestation_paths = paths
            self.refresh()

    def select_packs(self) -> None:
        paths = self._select("Select Phase 73 audit packs", "ZIP files (*.zip)")
        if paths:
            self.degradation_pack_paths = paths
            self.refresh()

    def select_receipts(self) -> None:
        paths = self._select("Select Phase 73 receipts", "JSON files (*.json)")
        if paths:
            self.degradation_receipt_paths = paths
            self.refresh()

    def create_plan(self) -> None:
        result = self.service.create_plan(
            expected_job_count=self.expected_jobs.value(),
            recovery_target_minutes=self.recovery_target.value(),
            max_duplicate_requests=self.max_duplicate_requests.value(),
            max_duplicate_outputs=self.max_duplicate_outputs.value(),
            max_orphan_artifacts=self.max_orphans.value(),
            max_manifest_mismatches=self.max_manifest_mismatches.value(),
            max_cost_variance_percent=self.max_cost_variance.value(),
            owner=self.plan_owner.text(),
            notes=self.plan_notes.toPlainText(),
            acknowledge=self.plan_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(self, "Recovery replay plan", result.get("detail", "Blocked"))
            return
        self.plan_paths.append(result.plan_path)
        self.plan_ack.setChecked(False)
        self.refresh()

    def refresh(self) -> None:
        self.current_snapshot = self.service.snapshot(
            plan_paths=self.plan_paths,
            degradation_result_paths=self.degradation_result_paths,
            degradation_attestation_paths=self.degradation_attestation_paths,
            degradation_pack_paths=self.degradation_pack_paths,
            degradation_receipt_paths=self.degradation_receipt_paths,
        )
        snapshot = self.current_snapshot
        self.plan_summary.setText(f"{len(self.plan_paths)} selected")
        self.result_summary.setText(f"{len(self.degradation_result_paths)} selected")
        self.attestation_summary.setText(
            f"{len(self.degradation_attestation_paths)} selected"
        )
        self.pack_summary.setText(f"{len(self.degradation_pack_paths)} selected")
        self.receipt_summary.setText(
            f"{len(self.degradation_receipt_paths)} selected"
        )
        tone = "success" if snapshot.status == "ready" else (
            "warning" if snapshot.status == "ready_with_warnings" else "danger"
        )
        self.status_card.set_status(
            snapshot.status.replace("_", " ").title(),
            f"{snapshot.status_summary} Blockers: {snapshot.blocker_count}; warnings: {snapshot.warning_count}.",
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            for column, value in enumerate(
                (gate.label, gate.status, gate.detail, gate.remediation)
            ):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))
        if snapshot.plans:
            self.result_plan.setText(str(snapshot.plans[0].plan_path))
        else:
            self.result_plan.clear()

    def create_result(self) -> None:
        if self.current_snapshot is None or not self.result_plan.text().strip():
            QMessageBox.warning(self, "Recovery replay", "Select and verify a replay plan first.")
            return
        result = self.service.create_replay_result(
            self.current_snapshot,
            plan_path=Path(self.result_plan.text()),
            attempted_jobs=self.attempted_jobs.value(),
            resumed_jobs=self.resumed_jobs.value(),
            completed_jobs=self.completed_jobs.value(),
            duplicate_api_requests=self.duplicate_requests.value(),
            duplicate_outputs=self.duplicate_outputs.value(),
            orphan_artifacts=self.orphan_artifacts.value(),
            manifest_mismatches=self.manifest_mismatches.value(),
            cost_variance_percent=self.cost_variance.value(),
            recovery_minutes=self.recovery_minutes.value(),
            receipt_chain_verified=self.receipt_verified.isChecked(),
            output_checksums_verified=self.checksums_verified.isChecked(),
            dedicated_tests_passed=self.tests_passed.isChecked(),
            owner=self.result_owner.text(),
            statement=self.result_statement.toPlainText(),
            acknowledge=self.result_ack.isChecked(),
        )
        if isinstance(result, dict):
            QMessageBox.warning(self, "Recovery replay", result.get("detail", "Blocked"))
            return
        self.latest_record = result
        self.result_ack.setChecked(False)
        QMessageBox.information(
            self,
            "Recovery replay evidence",
            f"Outcome: {result.outcome_status}\nAudit pack: {result.audit_pack_path}",
        )

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(path)
