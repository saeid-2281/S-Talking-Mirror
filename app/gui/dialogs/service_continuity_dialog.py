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
from app.models.service_continuity import (
    ServiceContinuityDrillRecord,
    ServiceContinuitySnapshot,
)
from app.services.service_continuity_service import ServiceContinuityService


class ServiceContinuityDialog(QDialog):
    """Human-controlled service continuity and recovery drill workspace."""

    def __init__(
        self,
        service: ServiceContinuityService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.renewal_paths = list(service.default_renewal_paths())
        self.follow_up_paths = list(service.default_follow_up_paths())
        self.audit_pack_paths = list(service.default_audit_pack_paths())
        self.receipt_paths = list(service.default_receipt_paths())
        self.backup_dirs = list(service.default_backup_dirs())
        self.current_snapshot: ServiceContinuitySnapshot | None = None
        self.latest_record: ServiceContinuityDrillRecord | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("serviceContinuityDialog")
        self.setWindowTitle("Service continuity & recovery drill")
        self.resize(1440, 960)
        self.setMinimumSize(1100, 780)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Service continuity, backup recovery & RTO/RPO evidence",
            "Verify Phase 69 renewal custody and upgrade-recovery backups, create a non-destructive drill plan and record measured recovery evidence. Nothing is restored, deleted, restarted, deployed, uploaded or published automatically.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        source = DialogSection(
            "Verified continuity sources",
            "Each renewal requires its matching follow-up, audit pack and receipt. At least one verified backup directory is required.",
        )
        source_widget = QWidget()
        source_form = QFormLayout(source_widget)
        source_form.setContentsMargins(0, 0, 0, 0)
        self.renewal_summary = self._source_row(
            source_form, "Renewals", "continuityRenewalSummary", self.select_renewals
        )
        self.follow_up_summary = self._source_row(
            source_form, "Follow-up", "continuityFollowUpSummary", self.select_follow_ups
        )
        self.pack_summary = self._source_row(
            source_form, "Audit packs", "continuityPackSummary", self.select_packs
        )
        self.receipt_summary = self._source_row(
            source_form, "Receipts", "continuityReceiptSummary", self.select_receipts
        )
        self.backup_summary = self._source_row(
            source_form, "Recovery backups", "continuityBackupSummary", self.select_backup
        )
        self.rto_target = QSpinBox()
        self.rto_target.setObjectName("continuityRtoTarget")
        self.rto_target.setRange(self.service.MIN_RTO_MINUTES, self.service.MAX_RTO_MINUTES)
        self.rto_target.setValue(self.service.DEFAULT_RTO_MINUTES)
        self.rto_target.setSuffix(" min")
        source_form.addRow("RTO target", self.rto_target)
        self.rpo_target = QSpinBox()
        self.rpo_target.setObjectName("continuityRpoTarget")
        self.rpo_target.setRange(self.service.MIN_RPO_MINUTES, self.service.MAX_RPO_MINUTES)
        self.rpo_target.setValue(self.service.DEFAULT_RPO_MINUTES)
        self.rpo_target.setSuffix(" min")
        source_form.addRow("RPO target", self.rpo_target)
        self.drill_window = QSpinBox()
        self.drill_window.setObjectName("continuityDrillWindow")
        self.drill_window.setRange(
            self.service.MIN_DRILL_WINDOW_DAYS,
            self.service.MAX_DRILL_WINDOW_DAYS,
        )
        self.drill_window.setValue(self.service.DEFAULT_DRILL_WINDOW_DAYS)
        self.drill_window.setSuffix(" days")
        source_form.addRow("Evidence freshness", self.drill_window)
        source.add_widget(source_widget)
        self.workspace.add_body_widget(source)

        self.status_card = DialogStatusCard("Checking continuity gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        metrics = DialogSection(
            "Continuity readiness",
            "Verified renewal custody, backup freshness and governed follow-up.",
        )
        metrics_widget = QWidget()
        metrics_layout = QHBoxLayout(metrics_widget)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        self.metric_labels: dict[str, QLabel] = {}
        for key, label in (
            ("renewals", "Renewals"),
            ("backups", "Backups"),
            ("stale", "Stale backups"),
            ("follow_up", "Open follow-up"),
            ("rejected", "Rejected"),
        ):
            card = DialogStatusCard(label, "0", tone="info")
            self.metric_labels[key] = card.detail_label
            metrics_layout.addWidget(card, 1)
        metrics.add_widget(metrics_widget)
        self.workspace.add_body_widget(metrics)

        evidence = DialogSection(
            "Verified recovery evidence",
            "Review backup age, payload count and database coverage before creating the drill plan.",
        )
        self.evidence_table = QTableWidget(0, 7)
        self.evidence_table.setObjectName("continuityEvidenceTable")
        self.evidence_table.setAccessibleName("Service continuity recovery evidence")
        self.evidence_table.setHorizontalHeaderLabels(
            ["Type", "Status", "Identity", "Created", "Age", "Files/follow-up", "Source"]
        )
        self._configure_table(self.evidence_table)
        evidence.add_widget(self.evidence_table)
        self.workspace.add_body_widget(evidence)

        gates = DialogSection(
            "Continuity gates",
            "Blockers prevent planning. Warnings require explicit follow-up during the drill.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("continuityGateTable")
        self.gate_table.setAccessibleName("Service continuity gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Gate", "Severity", "Detail", "Remediation"]
        )
        self._configure_table(self.gate_table)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        plan = DialogSection(
            "Human drill plan",
            "The generated plan is evidence only. Every recovery step remains manual and isolated from production.",
        )
        plan_widget = QWidget()
        plan_form = QFormLayout(plan_widget)
        plan_form.setContentsMargins(0, 0, 0, 0)
        self.plan_owner = QLineEdit()
        self.plan_owner.setObjectName("continuityPlanOwner")
        self.plan_owner.setPlaceholderText("Human continuity owner")
        plan_form.addRow("Owner", self.plan_owner)
        self.environment = QComboBox()
        self.environment.setObjectName("continuityEnvironment")
        self.environment.addItems(self.service.ENVIRONMENTS)
        plan_form.addRow("Environment", self.environment)
        self.plan_notes = QTextEdit()
        self.plan_notes.setObjectName("continuityPlanNotes")
        self.plan_notes.setAccessibleName("Privacy-safe continuity drill statement")
        self.plan_notes.setPlaceholderText(
            "Describe the isolated drill purpose without credentials or local absolute paths."
        )
        self.plan_notes.setMinimumHeight(78)
        plan_form.addRow("Plan statement", self.plan_notes)
        self.plan_acknowledge = QCheckBox(
            "I reviewed the sources and objectives; create a local non-destructive plan only."
        )
        self.plan_acknowledge.setObjectName("continuityPlanAcknowledge")
        plan_form.addRow("", self.plan_acknowledge)
        plan.add_widget(plan_widget)
        self.workspace.add_body_widget(plan)

        result = DialogSection(
            "Measured drill result",
            "Record evidence only after a human completes the isolated recovery exercise.",
        )
        result_widget = QWidget()
        result_form = QFormLayout(result_widget)
        result_form.setContentsMargins(0, 0, 0, 0)
        plan_row = QWidget()
        plan_layout = QHBoxLayout(plan_row)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        self.result_plan_path = QLineEdit()
        self.result_plan_path.setObjectName("continuityResultPlanPath")
        self.result_plan_path.setPlaceholderText("Select a verified continuity plan")
        plan_layout.addWidget(self.result_plan_path, 1)
        browse_plan = QPushButton("Select")
        browse_plan.clicked.connect(self.select_plan)
        plan_layout.addWidget(browse_plan)
        result_form.addRow("Plan", plan_row)
        self.actual_restore = QSpinBox()
        self.actual_restore.setObjectName("continuityActualRestore")
        self.actual_restore.setRange(0, self.service.MAX_RTO_MINUTES)
        self.actual_restore.setSuffix(" min")
        result_form.addRow("Actual restore", self.actual_restore)
        self.data_loss = QSpinBox()
        self.data_loss.setObjectName("continuityObservedDataLoss")
        self.data_loss.setRange(0, self.service.MAX_RPO_MINUTES)
        self.data_loss.setSuffix(" min")
        result_form.addRow("Observed data loss", self.data_loss)
        self.database_check = QComboBox()
        self.database_check.setObjectName("continuityDatabaseCheck")
        self.database_check.addItems(("ok", "not_applicable", "failed"))
        result_form.addRow("Database quick_check", self.database_check)
        self.manifest_verified = QCheckBox("Backup manifest and payload hashes were re-verified")
        self.manifest_verified.setObjectName("continuityManifestVerified")
        result_form.addRow("Manifest", self.manifest_verified)
        self.regression_tests = QSpinBox()
        self.regression_tests.setObjectName("continuityRegressionTests")
        self.regression_tests.setRange(1, 100000)
        self.regression_tests.setValue(1)
        result_form.addRow("Regression tests", self.regression_tests)
        self.failed_tests = QSpinBox()
        self.failed_tests.setObjectName("continuityFailedTests")
        self.failed_tests.setRange(0, 100000)
        result_form.addRow("Failed tests", self.failed_tests)
        self.result_owner = QLineEdit()
        self.result_owner.setObjectName("continuityResultOwner")
        self.result_owner.setPlaceholderText("Human result owner")
        result_form.addRow("Result owner", self.result_owner)
        self.conclusion = QTextEdit()
        self.conclusion.setObjectName("continuityConclusion")
        self.conclusion.setAccessibleName("Privacy-safe continuity drill conclusion")
        self.conclusion.setPlaceholderText(
            "Summarize measured RTO, RPO and integrity evidence without secrets or local paths."
        )
        self.conclusion.setMinimumHeight(78)
        result_form.addRow("Conclusion", self.conclusion)
        self.result_acknowledge = QCheckBox(
            "I reviewed the measured evidence; create local result, attestation and audit pack."
        )
        self.result_acknowledge.setObjectName("continuityResultAcknowledge")
        result_form.addRow("", self.result_acknowledge)
        result.add_widget(result_widget)
        self.workspace.add_body_widget(result)

        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        self.workspace.add_footer_widget(refresh)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        self.workspace.add_footer_widget(export)
        create_plan = QPushButton("Create drill plan")
        create_plan.setObjectName("continuityCreatePlanButton")
        create_plan.setIcon(action_icon("report"))
        create_plan.clicked.connect(self.create_plan)
        self.workspace.add_footer_widget(create_plan)
        record_result = QPushButton("Record drill result")
        record_result.setObjectName("continuityRecordResultButton")
        record_result.setIcon(action_icon("health"))
        record_result.clicked.connect(self.record_result)
        self.workspace.add_footer_widget(record_result)

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
        layout.addWidget(summary, 1)
        button = QPushButton("Select")
        button.clicked.connect(callback)
        layout.addWidget(button)
        form.addRow(label, row)
        return summary

    def select_renewals(self) -> None:
        self.renewal_paths = self._select_files("Select Phase 69 renewal records", "JSON files (*.json)")
        self.refresh()

    def select_follow_ups(self) -> None:
        self.follow_up_paths = self._select_files("Select Phase 69 follow-up registers", "JSON files (*.json)")
        self.refresh()

    def select_packs(self) -> None:
        self.audit_pack_paths = self._select_files("Select Phase 69 audit packs", "ZIP files (*.zip)")
        self.refresh()

    def select_receipts(self) -> None:
        self.receipt_paths = self._select_files("Select Phase 69 receipts", "JSON files (*.json)")
        self.refresh()

    def select_backup(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select verified upgrade-recovery backup")
        if path:
            selected = Path(path)
            if selected not in self.backup_dirs:
                self.backup_dirs.append(selected)
        self.refresh()

    def select_plan(self) -> None:
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "Select continuity drill plan",
            str(self.service.plans_dir),
            "JSON files (*.json)",
        )
        if filename:
            self.result_plan_path.setText(filename)

    def _select_files(self, title: str, file_filter: str) -> list[Path]:
        filenames, _selected = QFileDialog.getOpenFileNames(self, title, "", file_filter)
        return [Path(filename) for filename in filenames]

    def refresh(self) -> None:
        self.renewal_summary.setText(f"{len(self.renewal_paths)} selected")
        self.follow_up_summary.setText(f"{len(self.follow_up_paths)} selected")
        self.pack_summary.setText(f"{len(self.audit_pack_paths)} selected")
        self.receipt_summary.setText(f"{len(self.receipt_paths)} selected")
        self.backup_summary.setText(f"{len(self.backup_dirs)} selected")
        self.current_snapshot = self.service.snapshot(
            renewal_paths=self.renewal_paths,
            follow_up_paths=self.follow_up_paths,
            audit_pack_paths=self.audit_pack_paths,
            receipt_paths=self.receipt_paths,
            backup_dirs=self.backup_dirs,
            rto_target_minutes=self.rto_target.value(),
            rpo_target_minutes=self.rpo_target.value(),
            drill_window_days=self.drill_window.value(),
        )
        snapshot = self.current_snapshot
        tone = "danger" if snapshot.blocker_count else "warning" if snapshot.warning_count else "success"
        self.status_card.set_status(snapshot.status.replace("_", " ").title(), snapshot.status_summary, tone=tone)
        self.metric_labels["renewals"].setText(str(snapshot.verified_renewal_count))
        self.metric_labels["backups"].setText(str(snapshot.verified_backup_count))
        self.metric_labels["stale"].setText(str(snapshot.stale_backup_count))
        self.metric_labels["follow_up"].setText(str(snapshot.open_follow_up_count))
        self.metric_labels["rejected"].setText(str(snapshot.rejected_source_count))
        self._populate_evidence(snapshot)
        self._populate_gates(snapshot)

    def _populate_evidence(self, snapshot: ServiceContinuitySnapshot) -> None:
        rows: list[list[str]] = []
        for source in snapshot.renewals:
            rows.append(
                [
                    "Renewal",
                    source.decision,
                    source.renewal_id,
                    source.created_at,
                    "—",
                    source.follow_up_status,
                    source.renewal_path.name,
                ]
            )
        for source in snapshot.backups:
            rows.append(
                [
                    "Backup",
                    source.status,
                    source.backup_id,
                    source.created_at,
                    f"{source.age_days} days",
                    f"{source.file_count} files · DB {'yes' if source.database_included else 'no'}",
                    source.backup_name,
                ]
            )
        self.evidence_table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, value in enumerate(values):
                self.evidence_table.setItem(row_index, column, QTableWidgetItem(value))
        self.evidence_table.resizeColumnsToContents()

    def _populate_gates(self, snapshot: ServiceContinuitySnapshot) -> None:
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = [gate.status, gate.label, gate.severity, gate.detail, gate.remediation]
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(value))
        self.gate_table.resizeColumnsToContents()

    def export_snapshot(self) -> None:
        self.refresh()
        if self.current_snapshot is None:
            return
        path = self.service.export_snapshot(self.current_snapshot)
        self._notify_path("Continuity snapshot exported", path)

    def create_plan(self) -> None:
        self.refresh()
        if self.current_snapshot is None:
            return
        result = self.service.create_drill_plan(
            self.current_snapshot,
            owner=self.plan_owner.text(),
            environment=self.environment.currentText(),
            notes=self.plan_notes.toPlainText(),
            acknowledge=self.plan_acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            self._notify_result(result)
            return
        self.latest_record = result
        self.result_plan_path.setText(str(result.plan_path))
        self._notify_path("Continuity drill plan created", result.plan_path)

    def record_result(self) -> None:
        plan_path = Path(self.result_plan_path.text().strip())
        result = self.service.record_drill_result(
            plan_path,
            actual_restore_minutes=self.actual_restore.value(),
            observed_data_loss_minutes=self.data_loss.value(),
            database_quick_check=self.database_check.currentText(),
            manifest_verified=self.manifest_verified.isChecked(),
            regression_test_count=self.regression_tests.value(),
            failed_test_count=self.failed_tests.value(),
            owner=self.result_owner.text(),
            conclusion=self.conclusion.toPlainText(),
            acknowledge=self.result_acknowledge.isChecked(),
        )
        if isinstance(result, dict):
            self._notify_result(result)
            return
        self.latest_record = result
        title = "Continuity drill passed" if result.outcome == "passed" else "Continuity attestation withheld"
        self._notify_path(title, result.audit_pack_path or result.result_path or result.plan_path)

    def _notify_result(self, result: dict[str, object]) -> None:
        status = str(result.get("status") or "blocked")
        detail = str(result.get("detail") or "Continuity operation did not complete.")
        if status == "dry_run":
            QMessageBox.information(self, "Human acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Continuity operation blocked", detail)

    def _notify_path(self, title: str, path: Path) -> None:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Information)
        box.setText(title)
        box.setInformativeText(str(path))
        open_button = None
        if self.open_path is not None:
            open_button = box.addButton("Open", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if open_button is not None and box.clickedButton() is open_button:
            self.open_path(path)
