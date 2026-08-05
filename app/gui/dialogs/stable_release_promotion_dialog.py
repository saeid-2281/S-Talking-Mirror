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
from app.models.stable_release_promotion import StablePromotionSnapshot
from app.services.stable_release_promotion_service import StableReleasePromotionService


class StableReleasePromotionDialog(QDialog):
    """Human-controlled stable release promotion, rollback and receipt workspace."""

    def __init__(
        self,
        service: StableReleasePromotionService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.current_snapshot: StablePromotionSnapshot | None = None
        self.rollback_manifest: Path | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("stableReleasePromotionDialog")
        self.setWindowTitle("Stable 1.0 release promotion")
        self.resize(1260, 820)
        self.setMinimumSize(960, 660)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Production promotion & stable 1.0 release",
            "Verify the approved attestation, stable source lineage, rollback point, locally built artifacts, SPDX SBOM and stable update feed. No tag, push, upload, install or restart is automatic.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        identity = DialogSection(
            "Promotion inputs",
            "The stable commit must directly follow the Phase 60 attested commit and the working tree must be clean.",
        )
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        self.attestation = QLineEdit(str(self.service.default_attestation_path()))
        self.attestation.setObjectName("stablePromotionAttestation")
        self.attestation.setAccessibleName("Production attestation path")
        form.addRow("Production attestation", self.attestation)
        self.rollout = QSpinBox()
        self.rollout.setObjectName("stablePromotionRollout")
        self.rollout.setAccessibleName("Stable rollout percentage")
        self.rollout.setRange(1, 100)
        self.rollout.setValue(100)
        self.rollout.setSuffix("%")
        form.addRow("Stable rollout", self.rollout)
        self.require_installer = QCheckBox("Require a compiled Windows installer")
        self.require_installer.setObjectName("stablePromotionRequireInstaller")
        self.require_installer.setAccessibleName("Require compiled Windows installer")
        form.addRow("Installer policy", self.require_installer)
        self.require_signatures = QCheckBox("Require timestamped Authenticode evidence")
        self.require_signatures.setObjectName("stablePromotionRequireSignatures")
        self.require_signatures.setAccessibleName("Require timestamped Authenticode signatures")
        form.addRow("Signing policy", self.require_signatures)
        identity.add_widget(form_widget)
        self.workspace.add_body_widget(identity)

        self.summary = DialogStatusCard("Checking stable promotion gates", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        gates = DialogSection(
            "Promotion and artifact gates",
            "Refresh checks source identity and lineage. Verify artifacts additionally checks the stable bundle, feed and SBOM.",
        )
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("stablePromotionGateTable")
        self.table.setAccessibleName("Stable release promotion gates")
        self.table.setHorizontalHeaderLabels(["Status", "Severity", "Gate", "Evidence", "Remediation"])
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
            "I reviewed the attestation and warnings. I understand that publication, Git tag, push, upload and installation remain separate manual actions."
        )
        self.acknowledge.setObjectName("stablePromotionAcknowledgement")
        self.acknowledge.setAccessibleName("Acknowledge stable promotion evidence")
        acknowledgement_layout.addWidget(self.acknowledge, 1)
        self.workspace.add_body_widget(acknowledgement)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setAccessibleName("Stable release promotion status")
        self.workspace.add_footer_widget(self.status_label, 1)

        actions = (
            ("Refresh preflight", self.refresh, "general.refresh", True),
            ("Prepare rollback point", self.prepare_rollback, "history", False),
            ("Verify stable artifacts", self.verify_artifacts, "health", False),
            ("Write promotion receipt", self.write_receipt, "report", False),
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
        close.setAccessibleName("Close stable release promotion")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _snapshot(self, *, artifacts: bool = False) -> StablePromotionSnapshot:
        return self.service.snapshot(
            attestation_path=Path(self.attestation.text().strip()),
            rollout_percentage=self.rollout.value(),
            include_artifact_gates=artifacts,
            require_installer=self.require_installer.isChecked(),
            require_signatures=self.require_signatures.isChecked(),
        )

    def refresh(self) -> StablePromotionSnapshot:
        snapshot = self._snapshot()
        self._render(snapshot)
        return snapshot

    def verify_artifacts(self) -> StablePromotionSnapshot:
        snapshot = self._snapshot(artifacts=True)
        self._render(snapshot)
        return snapshot

    def _render(self, snapshot: StablePromotionSnapshot) -> None:
        self.current_snapshot = snapshot
        tone = "error" if snapshot.status == "blocked" else "warning" if snapshot.status == "ready_with_warnings" else "success"
        self.summary.update_status(
            snapshot.summary,
            (
                f"{snapshot.version}/{snapshot.channel} · commit {snapshot.source_commit[:12] or 'unresolved'} · "
                f"parent {snapshot.attested_commit[:12] or 'unresolved'} · "
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

    def prepare_rollback(self) -> None:
        snapshot = self.current_snapshot or self.refresh()
        result = self.service.create_rollback_point(
            snapshot,
            attestation_path=Path(self.attestation.text().strip()),
            acknowledge=self.acknowledge.isChecked(),
        )
        detail = str(result.get("detail") or "")
        path = str(result.get("path") or "")
        if path:
            self.rollback_manifest = Path(path)
        self.status_label.setText(detail)
        if result.get("status") == "prepared":
            QMessageBox.information(self, "Rollback point prepared", detail)
        elif result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Rollback point blocked", detail)

    def write_receipt(self) -> None:
        snapshot = self.verify_artifacts()
        if self.rollback_manifest is None:
            QMessageBox.warning(self, "Rollback point required", "Prepare and verify a rollback point first.")
            return
        result = self.service.write_promotion_receipt(
            snapshot,
            rollback_manifest=self.rollback_manifest,
            attestation_path=Path(self.attestation.text().strip()),
            acknowledge=self.acknowledge.isChecked(),
            require_installer=self.require_installer.isChecked(),
            require_signatures=self.require_signatures.isChecked(),
        )
        detail = str(result.get("detail") or "")
        self.status_label.setText(detail)
        if result.get("status") == "verified":
            QMessageBox.information(self, "Promotion receipt verified", detail)
        elif result.get("status") == "dry_run":
            QMessageBox.information(self, "Acknowledgement required", detail)
        else:
            QMessageBox.warning(self, "Promotion receipt blocked", detail)

    def open_evidence_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(self.service.root)
