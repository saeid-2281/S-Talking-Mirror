from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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
from app.models.incident_support import IncidentSupportBundle, IncidentSupportSnapshot
from app.services.incident_support_service import IncidentSupportService


class IncidentSupportDialog(QDialog):
    """Production incident intake and privacy-safe support bundle workspace."""

    def __init__(
        self,
        service: IncidentSupportService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: IncidentSupportSnapshot | None = None
        self.latest_bundle: IncidentSupportBundle | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("incidentSupportDialog")
        self.setWindowTitle("Production incident support")
        self.resize(1280, 840)
        self.setMinimumSize(980, 680)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Production incident response & support bundle",
            "Describe the issue, verify the Phase 62 baseline and crash evidence, then prepare a local privacy-safe bundle. Upload, email, publication, restart and cleanup are never automatic.",
            icon_name="warning",
            parent=self,
        )
        root.addWidget(self.workspace)

        inputs = DialogSection(
            "Incident intake",
            "Do not paste API keys, tokens, passwords, customer text or other private content into the summary.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.summary = QTextEdit()
        self.summary.setObjectName("incidentSupportSummary")
        self.summary.setAccessibleName("Incident summary")
        self.summary.setPlaceholderText(
            "Example: Audio generation stops after queue resume; 12 jobs remain pending and the UI stays responsive."
        )
        self.summary.setFixedHeight(86)
        form.addRow("Summary", self.summary)
        self.severity = QComboBox()
        self.severity.setObjectName("incidentSupportSeverity")
        self.severity.setAccessibleName("Incident severity")
        self.severity.addItems(["Low", "Medium", "High", "Critical"])
        self.severity.setCurrentText("Medium")
        form.addRow("Severity", self.severity)
        self.baseline = QLineEdit(str(self.service.default_baseline_path()))
        self.baseline.setObjectName("incidentSupportBaseline")
        self.baseline.setAccessibleName("Post-GA maintenance baseline path")
        form.addRow("Phase 62 baseline", self.baseline)
        self.include_logs = QCheckBox("Include recent text logs after privacy redaction")
        self.include_logs.setObjectName("incidentSupportIncludeLogs")
        self.include_logs.setAccessibleName("Include recent redacted logs")
        self.include_logs.setChecked(True)
        form.addRow("Logs", self.include_logs)
        self.max_log_age = QSpinBox()
        self.max_log_age.setObjectName("incidentSupportMaxLogAge")
        self.max_log_age.setAccessibleName("Maximum support log age in days")
        self.max_log_age.setRange(1, 365)
        self.max_log_age.setValue(14)
        self.max_log_age.setSuffix(" days")
        form.addRow("Maximum log age", self.max_log_age)
        self.max_bundle_size = QSpinBox()
        self.max_bundle_size.setObjectName("incidentSupportMaxBundleSize")
        self.max_bundle_size.setAccessibleName("Maximum support bundle size in megabytes")
        self.max_bundle_size.setRange(1, 128)
        self.max_bundle_size.setValue(16)
        self.max_bundle_size.setSuffix(" MB")
        form.addRow("Bundle limit", self.max_bundle_size)
        inputs.add_widget(form_widget)
        self.workspace.add_body_widget(inputs)

        self.status_card = DialogStatusCard("Checking incident support gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        gates = DialogSection(
            "Incident support gates",
            "Blockers prevent bundle creation. Warnings remain visible in the bundle receipt for manual review.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("incidentSupportGateTable")
        self.table.setAccessibleName("Incident support gates")
        self.table.setHorizontalHeaderLabels(
            ["Status", "Severity", "Gate", "Evidence", "Remediation"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        gates.add_widget(self.table)
        self.workspace.add_body_widget(gates, 1)

        acknowledgement = QWidget()
        acknowledgement_layout = QHBoxLayout(acknowledgement)
        acknowledgement_layout.setContentsMargins(0, 0, 0, 0)
        self.acknowledge = QCheckBox(
            "I reviewed the summary, gates and exclusions. I understand that bundle sharing is a separate manual action."
        )
        self.acknowledge.setObjectName("incidentSupportAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge incident support bundle creation")
        acknowledgement_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(acknowledgement)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Incident support status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh gates", self.refresh, "general.refresh", True),
            ("Create support bundle", self.create_bundle, "save", False),
            ("Verify latest bundle", self.verify_latest_bundle, "health", False),
            ("Open support folder", self.open_support_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in actions:
            button = QPushButton(text)
            button.setAccessibleName(text)
            button.setIcon(action_icon(icon_name))
            if primary:
                button.setObjectName("dialogPrimaryAction")
            button.clicked.connect(handler)
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.setAccessibleName("Close production incident support")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _snapshot(self) -> IncidentSupportSnapshot:
        return self.service.snapshot(
            summary=self.summary.toPlainText().strip(),
            severity=self.severity.currentText().casefold(),
            baseline_path=Path(self.baseline.text().strip()),
            include_logs=self.include_logs.isChecked(),
            max_log_age_days=self.max_log_age.value(),
            max_bundle_mb=self.max_bundle_size.value(),
        )

    def refresh(self) -> IncidentSupportSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        tone = (
            "error"
            if snapshot.status == "blocked"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "success"
        )
        self.status_card.update_status(
            snapshot.status_summary,
            (
                f"{snapshot.version}/{snapshot.channel} · {snapshot.severity} · "
                f"{snapshot.crash_count} crash report(s) · {snapshot.eligible_log_count} log(s) · "
                f"{snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)"
            ),
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (
                gate.status.title(),
                gate.severity.title(),
                gate.label,
                gate.detail,
                gate.remediation or "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.status_label.setText(snapshot.status_summary)
        return snapshot

    def create_bundle(self) -> IncidentSupportBundle | None:
        snapshot = self.refresh()
        result = self.service.create_bundle(
            snapshot,
            baseline_path=Path(self.baseline.text().strip()),
            include_logs=self.include_logs.isChecked(),
            max_log_age_days=self.max_log_age.value(),
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, IncidentSupportBundle):
            self.latest_bundle = result
            detail = (
                f"Verified bundle created with {result.report_count} crash report(s) and "
                f"{result.log_count} redacted log(s): {result.path.name}"
            )
            self.status_label.setText(detail)
            QMessageBox.information(self, "Incident support bundle verified", detail)
            return result

        detail = str(result.get("detail") or "Incident support bundle was not created.")
        self.status_label.setText(detail)
        if result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Incident support blocked", detail)
        return None

    def verify_latest_bundle(self) -> None:
        bundle = self.latest_bundle
        if bundle is None:
            candidates = sorted(
                self.service.bundles_dir.glob("S-Talking-incident-support-*.zip"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                QMessageBox.information(self, "No support bundle", "No incident support bundle exists yet.")
                return
            path = candidates[0]
        else:
            path = bundle.path
        ok, detail = self.service.verify_bundle(path)
        self.status_label.setText(detail)
        if ok:
            QMessageBox.information(self, "Support bundle verified", detail)
        else:
            QMessageBox.warning(self, "Support bundle verification failed", detail)

    def open_support_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)
