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
from app.models.prevention_effectiveness import (
    PreventionEffectivenessRecord,
    PreventionEffectivenessSnapshot,
)
from app.services.prevention_effectiveness_service import PreventionEffectivenessService


class PreventionEffectivenessDialog(QDialog):
    """Human-controlled preventive-action and recurrence effectiveness review."""

    def __init__(
        self,
        service: PreventionEffectivenessService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: PreventionEffectivenessSnapshot | None = None
        self.latest_record: PreventionEffectivenessRecord | None = None
        self.baseline_path = service.default_baseline_path()
        self.register_path = service.default_register_path(self.baseline_path)
        self.selected_closures = list(service.default_closure_paths())
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("preventionEffectivenessDialog")
        self.setWindowTitle("Preventive action effectiveness & residual risk")
        self.resize(1400, 940)
        self.setMinimumSize(1080, 760)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Preventive action governance, effectiveness review & residual risk",
            "Verify the immutable Phase 66 baseline, record human action outcomes, measure post-baseline recurrence and create local tamper-evident review decisions. Nothing is completed, accepted, scheduled, deployed or published automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        source = DialogSection(
            "Verified Phase 66 sources",
            "The selected baseline and action register must match byte-for-byte. Post-baseline closures are inspected without modifying prior records.",
        )
        source_widget = QWidget()
        form = QFormLayout(source_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.baseline_edit = self._path_row(
            form,
            "Baseline",
            "preventionEffectivenessBaselinePath",
            self.baseline_path,
            self.select_baseline,
        )
        self.register_edit = self._path_row(
            form,
            "Action register",
            "preventionEffectivenessRegisterPath",
            self.register_path,
            self.select_register,
        )
        closure_row = QWidget()
        closure_layout = QHBoxLayout(closure_row)
        closure_layout.setContentsMargins(0, 0, 0, 0)
        self.closure_summary = QLineEdit()
        self.closure_summary.setObjectName("preventionEffectivenessClosureSummary")
        self.closure_summary.setAccessibleName("Selected post-baseline closures")
        self.closure_summary.setReadOnly(True)
        closure_layout.addWidget(self.closure_summary, 1)
        select_closures = QPushButton("Select closures")
        select_closures.setIcon(action_icon("project.open"))
        select_closures.clicked.connect(self.select_closures)
        closure_layout.addWidget(select_closures)
        form.addRow("Post-baseline closures", closure_row)
        self.observation_days = QSpinBox()
        self.observation_days.setObjectName("preventionEffectivenessObservationDays")
        self.observation_days.setRange(
            self.service.MIN_OBSERVATION_DAYS,
            self.service.MAX_OBSERVATION_DAYS,
        )
        self.observation_days.setValue(self.service.DEFAULT_OBSERVATION_DAYS)
        form.addRow("Observation days", self.observation_days)
        source.add_widget(source_widget)
        self.workspace.add_body_widget(source)

        self.status_card = DialogStatusCard("Checking effectiveness gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        actions = DialogSection(
            "Preventive action state",
            "Action outcomes are separate human attestations. The Phase 66 action register remains immutable.",
        )
        self.action_table = QTableWidget(0, 8)
        self.action_table.setObjectName("preventionEffectivenessActionTable")
        self.action_table.setAccessibleName("Preventive action states")
        self.action_table.setHorizontalHeaderLabels(
            ["Status", "Overdue", "Action", "Owner", "Target", "Due", "Evidence", "Code"]
        )
        self._configure_table(self.action_table)
        self.action_table.itemSelectionChanged.connect(self._selected_action_changed)
        actions.add_widget(self.action_table)
        self.workspace.add_body_widget(actions, 1)

        attestation = DialogSection(
            "Record a human action outcome",
            "Completed actions require a privacy-safe evidence reference. Deferred and risk-accepted outcomes remain explicit decisions; no external system is updated.",
        )
        attestation_widget = QWidget()
        attestation_form = QFormLayout(attestation_widget)
        attestation_form.setContentsMargins(0, 0, 0, 0)
        self.action_code = QComboBox()
        self.action_code.setObjectName("preventionEffectivenessActionCode")
        self.action_code.setAccessibleName("Preventive action code")
        attestation_form.addRow("Action", self.action_code)
        self.action_status = QComboBox()
        self.action_status.setObjectName("preventionEffectivenessActionStatus")
        self.action_status.addItem("Completed", "completed")
        self.action_status.addItem("Deferred", "deferred")
        self.action_status.addItem("Risk accepted", "risk_accepted")
        attestation_form.addRow("Outcome", self.action_status)
        self.action_owner = QLineEdit()
        self.action_owner.setObjectName("preventionEffectivenessActionOwner")
        self.action_owner.setPlaceholderText("Human owner or accountable role")
        attestation_form.addRow("Owner", self.action_owner)
        self.evidence_summary = QLineEdit()
        self.evidence_summary.setObjectName("preventionEffectivenessEvidenceSummary")
        self.evidence_summary.setPlaceholderText("Privacy-safe verification summary")
        attestation_form.addRow("Evidence summary", self.evidence_summary)
        self.evidence_reference = QLineEdit()
        self.evidence_reference.setObjectName("preventionEffectivenessEvidenceReference")
        self.evidence_reference.setPlaceholderText("Ticket, report or test reference; no local path")
        attestation_form.addRow("Evidence reference", self.evidence_reference)
        self.attestation_acknowledge = QCheckBox(
            "I confirm this is a human-reviewed outcome and no external action is performed automatically."
        )
        self.attestation_acknowledge.setObjectName("preventionEffectivenessAttestationAcknowledgement")
        attestation_form.addRow("Acknowledgement", self.attestation_acknowledge)
        record_action = QPushButton("Record action attestation")
        record_action.setObjectName("dialogPrimaryAction")
        record_action.setIcon(action_icon("report"))
        record_action.clicked.connect(self.record_attestation)
        attestation_form.addRow("", record_action)
        attestation.add_widget(attestation_widget)
        self.workspace.add_body_widget(attestation)

        patterns = DialogSection(
            "Post-baseline effectiveness",
            "Residual scores compare the Phase 66 pattern with verified closures after baseline creation.",
        )
        self.pattern_table = QTableWidget(0, 8)
        self.pattern_table.setObjectName("preventionEffectivenessPatternTable")
        self.pattern_table.setAccessibleName("Prevention effectiveness patterns")
        self.pattern_table.setHorizontalHeaderLabels(
            [
                "Effectiveness",
                "Component",
                "Baseline count",
                "New count",
                "Baseline risk",
                "Residual risk",
                "Latest recurrence",
                "Fingerprint",
            ]
        )
        self._configure_table(self.pattern_table)
        patterns.add_widget(self.pattern_table)
        self.workspace.add_body_widget(patterns, 1)

        gates = DialogSection(
            "Effectiveness gates",
            "A review decision requires verified source custody, privacy-safe attestations and explicit human acknowledgement.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("preventionEffectivenessGateTable")
        self.gate_table.setAccessibleName("Prevention effectiveness gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Severity", "Gate", "Evidence", "Remediation"]
        )
        self._configure_table(self.gate_table)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        decision = DialogSection(
            "Human review decision",
            "Closing as effective, escalating, monitoring or accepting residual risk creates local records only.",
        )
        decision_widget = QWidget()
        decision_form = QFormLayout(decision_widget)
        decision_form.setContentsMargins(0, 0, 0, 0)
        self.review_decision = QComboBox()
        self.review_decision.setObjectName("preventionEffectivenessDecision")
        self.review_decision.addItem("Continue monitoring", "continue_monitoring")
        self.review_decision.addItem("Escalate preventive work", "escalate_prevention")
        self.review_decision.addItem("Accept residual risk", "accept_residual_risk")
        self.review_decision.addItem("Close as effective", "close_effective")
        decision_form.addRow("Decision", self.review_decision)
        self.review_rationale = QTextEdit()
        self.review_rationale.setObjectName("preventionEffectivenessRationale")
        self.review_rationale.setAccessibleName("Effectiveness decision rationale")
        self.review_rationale.setPlaceholderText(
            "Explain the human decision without secrets, customer data or local absolute paths."
        )
        self.review_rationale.setMaximumHeight(110)
        decision_form.addRow("Rationale", self.review_rationale)
        self.review_acknowledge = QCheckBox(
            "I reviewed every gate, action state and recurrence result and acknowledge this local decision record."
        )
        self.review_acknowledge.setObjectName("preventionEffectivenessReviewAcknowledgement")
        decision_form.addRow("Acknowledgement", self.review_acknowledge)
        decision.add_widget(decision_widget)
        self.workspace.add_body_widget(decision)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Prevention effectiveness status")
        self.workspace.add_footer_widget(self.status_label, 1)
        footer_actions = (
            ("Refresh review", self.refresh, "general.refresh", True),
            ("Export snapshot", self.export_snapshot, "save", False),
            ("Create review decision", self.create_review, "health", False),
            ("Verify latest review", self.verify_latest, "report", False),
            ("Open effectiveness folder", self.open_effectiveness_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in footer_actions:
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.setIcon(action_icon(icon_name))
            if primary:
                button.setObjectName("dialogPrimaryAction")
            button.clicked.connect(handler)
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.setAccessibleName("Close prevention effectiveness")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _path_row(
        self,
        form: QFormLayout,
        label: str,
        object_name: str,
        path: Path,
        handler: Callable[[], None],
    ) -> QLineEdit:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(str(path))
        edit.setObjectName(object_name)
        edit.setAccessibleName(label)
        edit.setReadOnly(True)
        layout.addWidget(edit, 1)
        select = QPushButton("Select")
        select.setIcon(action_icon("project.open"))
        select.clicked.connect(handler)
        layout.addWidget(select)
        form.addRow(label, row)
        return edit

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)

    def select_baseline(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select verified Phase 66 prevention baseline",
            str(self.service.incident_prevention_service.baselines_dir),
            "Prevention baselines (baseline-*.json);;JSON files (*.json)",
        )
        if path:
            self.baseline_path = Path(path)
            self.register_path = self.service.default_register_path(self.baseline_path)
            self.baseline_edit.setText(str(self.baseline_path))
            self.register_edit.setText(str(self.register_path))
            self.refresh()

    def select_register(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select matching Phase 66 action register",
            str(self.service.incident_prevention_service.registers_dir),
            "Action registers (*-action-register.json);;JSON files (*.json)",
        )
        if path:
            self.register_path = Path(path)
            self.register_edit.setText(str(self.register_path))
            self.refresh()

    def select_closures(self) -> None:
        start = self.service.incident_prevention_service.incident_resolution_service.closures_dir
        files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Select post-baseline incident closures",
            str(start),
            "Incident closures (*-closure.json);;JSON files (*.json)",
        )
        if files:
            self.selected_closures = [Path(path) for path in files]
            self.refresh()

    def _snapshot(self) -> PreventionEffectivenessSnapshot:
        return self.service.snapshot(
            baseline_path=self.baseline_path,
            register_path=self.register_path,
            closure_paths=tuple(self.selected_closures),
            observation_days=self.observation_days.value(),
        )

    def refresh(self) -> PreventionEffectivenessSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        self.closure_summary.setText(
            f"{snapshot.selected_closure_count} selected · "
            f"{snapshot.verified_closure_count} verified post-baseline · "
            f"{snapshot.rejected_closure_count} rejected · "
            f"{snapshot.ignored_closure_count} ignored"
        )
        tone = "error" if snapshot.blocker_count else "warning" if snapshot.warning_count else "success"
        self.status_card.set_status(
            snapshot.status_summary,
            (
                f"Actions: {snapshot.completed_action_count} completed, "
                f"{snapshot.open_action_count} open, {snapshot.overdue_action_count} overdue · "
                f"Patterns: {snapshot.recurrent_pattern_count} recurrent, "
                f"{snapshot.ineffective_pattern_count} ineffective"
            ),
            tone=tone,
        )
        self._render_actions(snapshot)
        self._render_patterns(snapshot)
        self._render_gates(snapshot)
        self.status_label.setText(snapshot.status_summary)
        return snapshot

    def _render_actions(self, snapshot: PreventionEffectivenessSnapshot) -> None:
        self.action_table.setRowCount(len(snapshot.actions))
        selected_code = self.action_code.currentData()
        self.action_code.clear()
        for row, action in enumerate(snapshot.actions):
            values = (
                action.status,
                "Yes" if action.overdue else "No",
                action.label,
                action.owner,
                f"{action.target_days} days",
                action.due_at,
                action.evidence_summary,
                action.code,
            )
            for column, value in enumerate(values):
                self.action_table.setItem(row, column, QTableWidgetItem(str(value)))
            self.action_code.addItem(f"{action.label} [{action.code}]", action.code)
        if selected_code:
            index = self.action_code.findData(selected_code)
            if index >= 0:
                self.action_code.setCurrentIndex(index)
        self.action_table.resizeColumnsToContents()

    def _render_patterns(self, snapshot: PreventionEffectivenessSnapshot) -> None:
        self.pattern_table.setRowCount(len(snapshot.patterns))
        for row, pattern in enumerate(snapshot.patterns):
            values = (
                pattern.effectiveness,
                pattern.component,
                pattern.baseline_occurrence_count,
                pattern.post_baseline_occurrence_count,
                pattern.baseline_risk_score,
                pattern.residual_risk_score,
                pattern.latest_closed_at,
                pattern.fingerprint,
            )
            for column, value in enumerate(values):
                self.pattern_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.pattern_table.resizeColumnsToContents()

    def _render_gates(self, snapshot: PreventionEffectivenessSnapshot) -> None:
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (gate.status, gate.severity, gate.label, gate.detail, gate.remediation)
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.gate_table.resizeColumnsToContents()

    def _selected_action_changed(self) -> None:
        rows = self.action_table.selectionModel().selectedRows()
        if not rows:
            return
        code_item = self.action_table.item(rows[0].row(), 7)
        if code_item is None:
            return
        index = self.action_code.findData(code_item.text())
        if index >= 0:
            self.action_code.setCurrentIndex(index)

    def record_attestation(self) -> None:
        action_code = str(self.action_code.currentData() or "")
        result = self.service.create_action_attestation(
            baseline_path=self.baseline_path,
            register_path=self.register_path,
            action_code=action_code,
            status=str(self.action_status.currentData() or ""),
            owner=self.action_owner.text(),
            evidence_summary=self.evidence_summary.text(),
            evidence_reference=self.evidence_reference.text(),
            acknowledge=self.attestation_acknowledge.isChecked(),
        )
        if isinstance(result, Path):
            self.status_label.setText(f"Action attestation created: {result.name}")
            self.attestation_acknowledge.setChecked(False)
            self.refresh()
            return
        QMessageBox.warning(self, "Action attestation", str(result.get("detail") or "Blocked"))

    def export_snapshot(self) -> None:
        snapshot = self.current_snapshot or self.refresh()
        path = self.service.export_snapshot(snapshot)
        self.status_label.setText(f"Snapshot exported: {path.name}")
        if self.open_path is not None:
            self.open_path(path)

    def create_review(self) -> None:
        snapshot = self.current_snapshot or self.refresh()
        result = self.service.create_review(
            snapshot,
            decision=str(self.review_decision.currentData() or ""),
            rationale=self.review_rationale.toPlainText(),
            acknowledge=self.review_acknowledge.isChecked(),
        )
        if isinstance(result, PreventionEffectivenessRecord):
            self.latest_record = result
            self.status_label.setText(f"Effectiveness review created: {result.review_id}")
            self.review_acknowledge.setChecked(False)
            if self.open_path is not None:
                self.open_path(result.review_path)
            return
        QMessageBox.warning(self, "Effectiveness review", str(result.get("detail") or "Blocked"))

    def verify_latest(self) -> None:
        record = self.latest_record
        review_path = record.review_path if record else self.service.root / "latest-effectiveness-review.json"
        decision_path = (
            record.decision_path if record else self.service.root / "latest-effectiveness-decision.json"
        )
        review_ok, review_detail = self.service.verify_review(review_path)
        decision_ok, decision_detail = self.service.verify_decision(decision_path)
        detail = review_detail if not review_ok else decision_detail
        if review_ok and decision_ok:
            QMessageBox.information(self, "Effectiveness verification", detail)
        else:
            QMessageBox.warning(self, "Effectiveness verification", detail)

    def open_effectiveness_folder(self) -> None:
        if self.open_path is not None:
            self.open_path(self.service.root)
