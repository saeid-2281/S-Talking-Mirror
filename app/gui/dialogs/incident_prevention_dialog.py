from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.incident_prevention import (
    IncidentPreventionRecord,
    IncidentPreventionSnapshot,
)
from app.services.incident_prevention_service import IncidentPreventionService


class IncidentPreventionDialog(QDialog):
    """Human-controlled incident recurrence analysis and preventive action planning."""

    def __init__(
        self,
        service: IncidentPreventionService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: IncidentPreventionSnapshot | None = None
        self.latest_record: IncidentPreventionRecord | None = None
        self.selected_closures = list(service.default_closure_paths())
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("incidentPreventionDialog")
        self.setWindowTitle("Incident prevention & recurrence control")
        self.resize(1340, 900)
        self.setMinimumSize(1040, 720)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Problem management, recurrence analysis & preventive actions",
            "Aggregate verified Phase 65 closures into a privacy-safe trend baseline and an open manual action register. No ticket, schedule, patch, deployment, restart or publication is automatic.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        scope = DialogSection(
            "Verified closure scope",
            "Only integrity-verified Phase 65 closure chains inside the selected lookback window are analyzed. Incident narratives are never copied.",
        )
        scope_widget = QWidget()
        form = QFormLayout(scope_widget)
        form.setContentsMargins(0, 0, 0, 0)
        closure_row = QWidget()
        closure_layout = QHBoxLayout(closure_row)
        closure_layout.setContentsMargins(0, 0, 0, 0)
        self.closure_summary = QLineEdit()
        self.closure_summary.setObjectName("incidentPreventionClosureSummary")
        self.closure_summary.setAccessibleName("Selected incident closure certificates")
        self.closure_summary.setReadOnly(True)
        closure_layout.addWidget(self.closure_summary, 1)
        select = QPushButton("Select closures")
        select.setIcon(action_icon("project.open"))
        select.clicked.connect(self.select_closures)
        closure_layout.addWidget(select)
        form.addRow("Closures", closure_row)

        self.lookback_days = QSpinBox()
        self.lookback_days.setObjectName("incidentPreventionLookbackDays")
        self.lookback_days.setRange(
            self.service.MIN_LOOKBACK_DAYS,
            self.service.MAX_LOOKBACK_DAYS,
        )
        self.lookback_days.setValue(self.service.DEFAULT_LOOKBACK_DAYS)
        form.addRow("Lookback days", self.lookback_days)
        self.recurrence_threshold = QSpinBox()
        self.recurrence_threshold.setObjectName("incidentPreventionRecurrenceThreshold")
        self.recurrence_threshold.setRange(
            self.service.MIN_RECURRENCE_THRESHOLD,
            self.service.MAX_RECURRENCE_THRESHOLD,
        )
        self.recurrence_threshold.setValue(self.service.DEFAULT_RECURRENCE_THRESHOLD)
        form.addRow("Recurrence threshold", self.recurrence_threshold)
        self.high_risk_threshold = QSpinBox()
        self.high_risk_threshold.setObjectName("incidentPreventionHighRiskThreshold")
        self.high_risk_threshold.setRange(
            self.service.MIN_HIGH_RISK_THRESHOLD,
            self.service.MAX_HIGH_RISK_THRESHOLD,
        )
        self.high_risk_threshold.setValue(self.service.DEFAULT_HIGH_RISK_THRESHOLD)
        form.addRow("High-risk score", self.high_risk_threshold)
        scope.add_widget(scope_widget)
        self.workspace.add_body_widget(scope)

        self.status_card = DialogStatusCard("Checking prevention gates", "", tone="info")
        self.workspace.add_body_widget(self.status_card)

        patterns = DialogSection(
            "Verified recurrence patterns",
            "Fingerprints are deterministic hashes. Rows contain categorical metadata only and remain local.",
        )
        self.pattern_table = QTableWidget(0, 8)
        self.pattern_table.setObjectName("incidentPreventionPatternTable")
        self.pattern_table.setAccessibleName("Incident recurrence patterns")
        self.pattern_table.setHorizontalHeaderLabels(
            [
                "Risk",
                "Recurring",
                "Component",
                "Resolution",
                "Occurrences",
                "Priorities",
                "Last closure",
                "Fingerprint",
            ]
        )
        self.pattern_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pattern_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.pattern_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.pattern_table.setAlternatingRowColors(True)
        self.pattern_table.setShowGrid(False)
        self.pattern_table.verticalHeader().setVisible(False)
        patterns.add_widget(self.pattern_table)
        self.workspace.add_body_widget(patterns, 1)

        gates = DialogSection(
            "Prevention gates",
            "A baseline requires verified source custody, privacy-safe aggregation and explicit human acknowledgement.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("incidentPreventionGateTable")
        self.gate_table.setAccessibleName("Incident prevention gates")
        self.gate_table.setHorizontalHeaderLabels(
            ["Status", "Severity", "Gate", "Evidence", "Remediation"]
        )
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.gate_table.setAlternatingRowColors(True)
        self.gate_table.setShowGrid(False)
        self.gate_table.verticalHeader().setVisible(False)
        gates.add_widget(self.gate_table)
        self.workspace.add_body_widget(gates)

        acknowledgement = QWidget()
        acknowledgement_layout = QHBoxLayout(acknowledgement)
        acknowledgement_layout.setContentsMargins(0, 0, 0, 0)
        self.acknowledge = QCheckBox(
            "I reviewed the source closures, recurrence thresholds, risk scores and every proposed manual preventive action."
        )
        self.acknowledge.setObjectName("incidentPreventionAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge incident prevention baseline")
        acknowledgement_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(acknowledgement)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Incident prevention status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh analysis", self.refresh, "general.refresh", True),
            ("Export snapshot", self.export_snapshot, "save", False),
            ("Create prevention baseline", self.create_baseline, "health", False),
            ("Verify latest baseline", self.verify_latest, "report", False),
            ("Open prevention folder", self.open_prevention_folder, "project.output_folder", False),
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
        close.setAccessibleName("Close incident prevention")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def select_closures(self) -> None:
        start = self.service.incident_resolution_service.closures_dir
        files, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Select verified incident closure certificates",
            str(start),
            "Incident closures (*-closure.json);;JSON files (*.json)",
        )
        if files:
            self.selected_closures = [Path(path) for path in files]
            self.refresh()

    def _snapshot(self) -> IncidentPreventionSnapshot:
        return self.service.snapshot(
            closure_paths=tuple(self.selected_closures),
            lookback_days=self.lookback_days.value(),
            recurrence_threshold=self.recurrence_threshold.value(),
            high_risk_threshold=self.high_risk_threshold.value(),
        )

    def refresh(self) -> IncidentPreventionSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        self.closure_summary.setText(
            f"{snapshot.selected_count} selected · {snapshot.verified_count} verified · "
            f"{snapshot.rejected_count} rejected · {snapshot.ignored_count} outside lookback"
        )
        tone = (
            "error"
            if snapshot.status == "blocked"
            else "warning"
            if snapshot.warning_count
            else "success"
        )
        self.status_card.update_status(
            snapshot.status_summary,
            (
                f"{snapshot.version}/{snapshot.channel} · {len(snapshot.patterns)} pattern(s) · "
                f"{snapshot.recurring_pattern_count} recurring · "
                f"{snapshot.high_risk_pattern_count} high-risk · "
                f"{snapshot.blocker_count} blocker(s)"
            ),
            tone=tone,
        )
        self.pattern_table.setRowCount(len(snapshot.patterns))
        for row, pattern in enumerate(snapshot.patterns):
            values = (
                pattern.risk_score,
                "Yes" if pattern.recurring else "No",
                pattern.component,
                pattern.resolution_type.replace("_", " ").title(),
                pattern.occurrence_count,
                ", ".join(pattern.priorities),
                pattern.last_closed_at,
                pattern.fingerprint[:16],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(
                    pattern.fingerprint if column == 7 else str(value)
                )
                self.pattern_table.setItem(row, column, item)
        self.pattern_table.resizeColumnsToContents()

        self.gate_table.setRowCount(len(snapshot.gates))
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
                self.gate_table.setItem(row, column, item)
        self.gate_table.resizeColumnsToContents()
        self.status_label.setText(snapshot.status_summary)
        return snapshot

    def export_snapshot(self) -> None:
        snapshot = self.refresh()
        path = self.service.export_snapshot(snapshot)
        self.status_label.setText(f"Snapshot exported: {path.name}")
        QMessageBox.information(self, "Prevention snapshot exported", str(path))

    def create_baseline(self) -> IncidentPreventionRecord | None:
        snapshot = self.refresh()
        result = self.service.create_baseline(
            snapshot,
            acknowledge=self.acknowledge.isChecked(),
        )
        if isinstance(result, IncidentPreventionRecord):
            self.latest_record = result
            detail = (
                f"Verified baseline {result.baseline_id} created with "
                f"{result.pattern_count} pattern(s)."
            )
            self.status_label.setText(detail)
            QMessageBox.information(self, "Incident prevention baseline", detail)
            return result
        detail = str(result.get("detail") or "Incident prevention baseline was not created.")
        self.status_label.setText(detail)
        if result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Incident prevention blocked", detail)
        return None

    def verify_latest(self) -> None:
        if self.latest_record is not None:
            baseline = self.latest_record.baseline_path
            register = self.latest_record.register_path
        else:
            candidates = sorted(
                self.service.baselines_dir.glob("baseline-*.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                QMessageBox.information(
                    self,
                    "No prevention baseline",
                    "No incident prevention baseline exists yet.",
                )
                return
            baseline = candidates[0]
            register = self.service.registers_dir / f"{baseline.stem}-action-register.json"
        checks = (
            self.service.verify_baseline(baseline),
            self.service.verify_register(register),
        )
        ok = all(item[0] for item in checks)
        detail = " ".join(item[1] for item in checks)
        self.status_label.setText(detail)
        if ok:
            QMessageBox.information(self, "Prevention records verified", detail)
        else:
            QMessageBox.warning(self, "Prevention verification failed", detail)

    def open_prevention_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)
