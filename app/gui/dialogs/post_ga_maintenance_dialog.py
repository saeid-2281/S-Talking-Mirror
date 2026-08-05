from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.post_ga_maintenance import PostGaMaintenanceSnapshot
from app.services.post_ga_maintenance_service import PostGaMaintenanceService


class PostGaMaintenanceDialog(QDialog):
    """Post-GA reliability and maintenance evidence workspace."""

    def __init__(
        self,
        service: PostGaMaintenanceService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: PostGaMaintenanceSnapshot | None = None
        self.baseline_path: Path | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("postGaMaintenanceDialog")
        self.setWindowTitle("Post-GA reliability & maintenance")
        self.resize(1260, 820)
        self.setMinimumSize(960, 660)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Post-GA reliability & maintenance operations",
            "Verify the stable promotion receipt, update feed, rollback point, evidence freshness, runtime writability and disk reserve. No cleanup, publication, update or restart is automatic.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        inputs = DialogSection(
            "Maintenance baseline inputs",
            "Use the canonical stable evidence unless an operator is intentionally reviewing a different verified path.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.receipt = QLineEdit(str(self.service.default_promotion_receipt_path()))
        self.receipt.setObjectName("postGaPromotionReceipt")
        self.receipt.setAccessibleName("Stable promotion receipt path")
        form.addRow("Promotion receipt", self.receipt)
        self.feed = QLineEdit(str(self.service.default_stable_feed_path()))
        self.feed.setObjectName("postGaStableFeed")
        self.feed.setAccessibleName("Stable update feed path")
        form.addRow("Stable update feed", self.feed)
        self.max_age = QSpinBox()
        self.max_age.setObjectName("postGaEvidenceMaxAge")
        self.max_age.setAccessibleName("Maximum evidence age in days")
        self.max_age.setRange(1, 365)
        self.max_age.setValue(30)
        self.max_age.setSuffix(" days")
        form.addRow("Evidence review interval", self.max_age)
        self.minimum_free_space = QSpinBox()
        self.minimum_free_space.setObjectName("postGaMinimumFreeSpace")
        self.minimum_free_space.setAccessibleName("Minimum free disk space in megabytes")
        self.minimum_free_space.setRange(64, 1_000_000)
        self.minimum_free_space.setValue(512)
        self.minimum_free_space.setSuffix(" MB")
        form.addRow("Minimum free space", self.minimum_free_space)
        inputs.add_widget(form_widget)
        self.workspace.add_body_widget(inputs)

        self.summary = DialogStatusCard("Checking post-GA maintenance gates", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        gates = DialogSection(
            "Reliability and maintenance gates",
            "Blocking gates prevent a baseline. Warnings require review but never trigger an automatic action.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("postGaMaintenanceGateTable")
        self.table.setAccessibleName("Post-GA maintenance gates")
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
            "I reviewed every blocker and warning. I understand that backups, cleanup, publication, updates and restarts remain separate manual actions."
        )
        self.acknowledge.setObjectName("postGaMaintenanceAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge post-GA maintenance evidence")
        acknowledgement_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(acknowledgement)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Post-GA maintenance status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh gates", self.refresh, "general.refresh", True),
            ("Write baseline", self.write_baseline, "save", False),
            ("Prepare maintenance plan", self.prepare_plan, "report", False),
            ("Open evidence folder", self.open_evidence_folder, "project.output_folder", False),
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
        close.setAccessibleName("Close post-GA maintenance")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _snapshot(self) -> PostGaMaintenanceSnapshot:
        return self.service.snapshot(
            promotion_receipt_path=Path(self.receipt.text().strip()),
            stable_feed_path=Path(self.feed.text().strip()),
            max_evidence_age_days=self.max_age.value(),
            minimum_free_space_mb=self.minimum_free_space.value(),
            expected_rollout_percentage=100,
        )

    def refresh(self) -> PostGaMaintenanceSnapshot:
        snapshot = self._snapshot()
        self.current_snapshot = snapshot
        tone = (
            "error"
            if snapshot.status == "blocked"
            else "warning"
            if snapshot.status == "ready_with_warnings"
            else "success"
        )
        self.summary.update_status(
            snapshot.summary,
            (
                f"{snapshot.version}/{snapshot.channel} · rollout {snapshot.rollout_percentage}% · "
                f"evidence {snapshot.evidence_age_days} day(s) old · "
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
        self.status_label.setText(snapshot.summary)
        return snapshot

    def write_baseline(self) -> None:
        snapshot = self.refresh()
        result = self.service.write_baseline(
            snapshot,
            acknowledge=self.acknowledge.isChecked(),
        )
        detail = str(result.get("detail") or "")
        path = str(result.get("path") or "")
        if path:
            self.baseline_path = Path(path)
        self.status_label.setText(detail)
        if result.get("status") == "verified":
            QMessageBox.information(self, "Maintenance baseline verified", detail)
        elif result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Maintenance baseline blocked", detail)

    def prepare_plan(self) -> None:
        snapshot = self.current_snapshot or self.refresh()
        baseline = self.baseline_path or self.service.default_baseline_path()
        result = self.service.prepare_maintenance_plan(
            snapshot,
            baseline_path=baseline,
            acknowledge=self.acknowledge.isChecked(),
        )
        detail = str(result.get("detail") or "")
        self.status_label.setText(detail)
        if result.get("status") == "prepared":
            QMessageBox.information(self, "Maintenance plan prepared", detail)
        elif result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Maintenance plan blocked", detail)

    def open_evidence_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)
