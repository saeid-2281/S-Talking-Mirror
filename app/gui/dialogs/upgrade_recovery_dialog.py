from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.upgrade_recovery_service import UpgradeRecoveryService


class UpgradeRecoveryDialog(QDialog):
    """Inspect upgrade compatibility and create verified rollback evidence."""

    def __init__(
        self,
        service: UpgradeRecoveryService,
        parent: QWidget | None = None,
        *,
        open_path=None,
        copy_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self.copy_path = copy_path
        self.current_snapshot = None
        self.selected_source_root: Path | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("upgradeRecoveryDialog")
        self.setWindowTitle("Upgrade, rollback and recovery")
        self.resize(1160, 780)
        self.setMinimumSize(860, 620)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Upgrade, rollback and migration validation",
            "Validate schema compatibility, preserve local user state and prepare a verified recovery path before changing application versions.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting upgrade evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addWidget(QLabel("Source version"))
        self.source_version = QLineEdit()
        self.source_version.setObjectName("upgradeSourceVersion")
        self.source_version.setPlaceholderText("Current or previous version")
        controls_layout.addWidget(self.source_version)
        controls_layout.addWidget(QLabel("Mode"))
        self.mode = QComboBox()
        self.mode.setObjectName("upgradeMode")
        self.mode.addItems(["auto", "in_place", "portable_to_installed", "installed_to_portable", "rollback"])
        controls_layout.addWidget(self.mode)
        select_source = QPushButton("Select source")
        select_source.setIcon(action_icon("project.output_folder"))
        select_source.clicked.connect(self.select_source)
        controls_layout.addWidget(select_source)
        controls_layout.addStretch(1)
        self.workspace.add_body_widget(controls)

        self.source_label = QLabel("Source: current application data")
        self.source_label.setObjectName("historyStatusLabel")
        self.source_label.setWordWrap(True)
        self.workspace.add_body_widget(self.source_label)

        gate_section = DialogSection(
            "Upgrade and rollback gates",
            "Blockers protect database compatibility and user data. A missing verified backup remains a warning until one is created.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("upgradeRecoveryGateTable")
        self.gate_table.setHorizontalHeaderLabels(["Status", "Gate", "Severity", "Evidence", "Action"])
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gate_section.add_widget(self.gate_table)
        self.workspace.add_body_widget(gate_section)

        evidence_section = DialogSection(
            "Recovery evidence",
            "Backup manifests and database snapshots are integrity checked. Credential contents are never rendered in this dialog or exported reports.",
        )
        self.artifact_table = QTableWidget(0, 4)
        self.artifact_table.setObjectName("upgradeRecoveryArtifactTable")
        self.artifact_table.setHorizontalHeaderLabels(["Artifact", "Status", "Size", "Path"])
        self.artifact_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.artifact_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        evidence_section.add_widget(self.artifact_table)
        self.workspace.add_body_widget(evidence_section)

        self.acknowledge_restore = QCheckBox("I understand that actual restore must run while S Talking is closed")
        self.acknowledge_restore.setObjectName("upgradeRecoveryAcknowledge")
        self.workspace.add_footer_widget(self.acknowledge_restore)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)

        buttons = (
            ("Refresh", self.refresh, "general.refresh"),
            ("Create backup", self.create_backup, "save"),
            ("Validate migration", self.validate_migration, "health"),
            ("Verify latest backup", self.verify_latest, "health"),
            ("Prepare restore", self.prepare_restore, "history"),
            ("Export snapshot", self.export_snapshot, "save"),
            ("Open recovery folder", self.open_recovery_folder, "project.output_folder"),
        )
        for text, handler, icon_name in buttons:
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.clicked.connect(handler)
            if text == "Create backup":
                button.setObjectName("dialogPrimaryAction")
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def select_source(self) -> None:
        value = QFileDialog.getExistingDirectory(self, "Select previous installation or portable folder")
        if not value:
            return
        self.selected_source_root = Path(value)
        self.source_label.setText(f"Source: {self.selected_source_root}")
        self.refresh()

    def refresh(self) -> None:
        try:
            snapshot = self.service.snapshot(
                source_version=self.source_version.text().strip() or None,
                mode=self.mode.currentText(),
                source_root=self.selected_source_root,
                backup_dir=self._latest_if_valid(),
            )
        except Exception as exc:
            self.status_label.setText(f"Refresh failed: {exc}")
            return
        self._render(snapshot)

    def _render(self, snapshot) -> None:
        self.current_snapshot = snapshot
        tone = "success" if snapshot.status == "ready" else "warning" if snapshot.status == "ready_with_warnings" else "error"
        self.summary.update_status(
            snapshot.summary,
            f"{snapshot.source_version} → {snapshot.target_version} · {snapshot.mode} · schema {snapshot.current_schema}/{snapshot.target_schema} · {snapshot.blocker_count} blocker(s) · {snapshot.warning_count} warning(s)",
            tone=tone,
        )
        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (gate.status.title(), gate.label, gate.severity.title(), gate.detail, gate.remediation or "—")
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.gate_table.resizeColumnsToContents()

        self.artifact_table.setRowCount(len(snapshot.artifacts))
        for row, artifact in enumerate(snapshot.artifacts):
            values = (
                artifact.role.replace("_", " ").title(),
                artifact.status.title(),
                self._size(artifact.size_bytes),
                str(artifact.path),
            )
            for column, value in enumerate(values):
                self.artifact_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.artifact_table.resizeColumnsToContents()
        self.status_label.setText(f"Operation {snapshot.operation_id}")

    def create_backup(self):
        try:
            snapshot = self.service.create_backup(
                source_version=self.source_version.text().strip() or None,
                mode=self.mode.currentText(),
                source_root=self.selected_source_root,
            )
        except Exception as exc:
            self.status_label.setText(f"Backup failed: {exc}")
            return None
        self._render(snapshot)
        self.status_label.setText(f"Backup created and verified: {snapshot.backup_dir}")
        return snapshot

    def validate_migration(self):
        result = self.service.validate_migration(
            source_root=self.selected_source_root,
            source_version=self.source_version.text().strip() or None,
        )
        self.status_label.setText(str(result.get("detail") or result.get("status")))
        return result

    def verify_latest(self) -> bool:
        latest = self.service.latest_backup_dir()
        ok, detail = self.service.verify_backup(latest)
        self.status_label.setText(detail)
        if ok:
            self.refresh()
        return ok

    def prepare_restore(self):
        latest = self.service.latest_backup_dir()
        if not self.acknowledge_restore.isChecked():
            self.status_label.setText("Select the acknowledgement before preparing a restore plan.")
            return None
        try:
            result = self.service.restore_backup(latest, dry_run=True)
        except Exception as exc:
            self.status_label.setText(f"Restore plan failed: {exc}")
            return None
        command = (
            f'"{sys.executable}" --restore-backup "{latest}" --acknowledge-restore'
            if getattr(sys, "frozen", False)
            else f'powershell -ExecutionPolicy Bypass -File .\\scripts\\upgrade-validation.ps1 -RestoreBackup "{latest}" -AcknowledgeRestore'
        )
        if callable(self.copy_path):
            self.copy_path(command)
        self.status_label.setText("Restore plan verified; recovery command copied. Close S Talking before running it.")
        return result

    def export_snapshot(self):
        path = self.service.export_snapshot(self.current_snapshot)
        self.status_label.setText(f"Exported {path.name}")
        return path

    def open_recovery_folder(self) -> None:
        self.service.root.mkdir(parents=True, exist_ok=True)
        if callable(self.open_path):
            self.open_path(self.service.root)
        self.status_label.setText(str(self.service.root))

    def _latest_if_valid(self) -> Path | None:
        latest = self.service.latest_backup_dir()
        return latest if self.service.verify_backup(latest)[0] else None

    @staticmethod
    def _size(value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{value} B"
