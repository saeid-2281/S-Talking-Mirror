from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_maintenance import GenerationHardeningDashboard
from app.services.generation_maintenance_service import GenerationMaintenanceService


class GenerationMaintenanceDialog(QDialog):
    """Release-hardening center for database health, backups, and retention."""

    def __init__(
        self,
        service: GenerationMaintenanceService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.export_dir = export_dir or Path.cwd() / "reports" / "hardening"
        self.dashboard_data: GenerationHardeningDashboard | None = None
        self.setWindowTitle("Generation Hardening & Maintenance")
        self.resize(1120, 780)

        root = QVBoxLayout(self)
        title = QLabel(f"Database hardening scope: {project_name}")
        title.setObjectName("generationMaintenanceTitle")
        root.addWidget(title)

        health_group = QGroupBox("Database health and release gate")
        health_layout = QVBoxLayout(health_group)
        self.health_label = QLabel()
        self.health_label.setWordWrap(True)
        health_layout.addWidget(self.health_label)
        health_buttons = QHBoxLayout()
        quick_button = QPushButton("Run quick check")
        quick_button.clicked.connect(lambda: self.run_health_check(full=False))
        full_button = QPushButton("Run full integrity check")
        full_button.clicked.connect(lambda: self.run_health_check(full=True))
        backup_button = QPushButton("Create verified backup")
        backup_button.clicked.connect(self.create_backup)
        restore_button = QPushButton("Restore backup…")
        restore_button.clicked.connect(self.restore_backup)
        export_button = QPushButton("Export hardening report")
        export_button.clicked.connect(self.export_report)
        for button in (
            quick_button,
            full_button,
            backup_button,
            restore_button,
            export_button,
        ):
            health_buttons.addWidget(button)
        health_layout.addLayout(health_buttons)
        root.addWidget(health_group)

        policy_group = QGroupBox("Retention and backup policy")
        policy_layout = QFormLayout(policy_group)
        self.enabled = QCheckBox("Allow retention cleanup")
        self.session_days = self._days()
        self.notification_days = self._days()
        self.activity_days = self._days()
        self.snapshot_days = self._days()
        self.run_days = self._days()
        self.backup_count = QSpinBox()
        self.backup_count.setRange(1, 1000)
        self.startup_check = QCheckBox("Run quick database check during startup")
        policy_layout.addRow("Enabled", self.enabled)
        policy_layout.addRow("Generation sessions", self.session_days)
        policy_layout.addRow("Read notifications", self.notification_days)
        policy_layout.addRow("Activity timeline", self.activity_days)
        policy_layout.addRow("Reliability/cost snapshots", self.snapshot_days)
        policy_layout.addRow("Maintenance audit runs", self.run_days)
        policy_layout.addRow("Verified backups to retain", self.backup_count)
        policy_layout.addRow("Startup validation", self.startup_check)
        policy_buttons = QHBoxLayout()
        save_policy = QPushButton("Save policy")
        save_policy.clicked.connect(self.save_policy)
        preview_button = QPushButton("Refresh cleanup preview")
        preview_button.clicked.connect(self.refresh)
        apply_button = QPushButton("Apply retention cleanup")
        apply_button.clicked.connect(self.apply_retention)
        policy_buttons.addWidget(save_policy)
        policy_buttons.addWidget(preview_button)
        policy_buttons.addWidget(apply_button)
        policy_layout.addRow(policy_buttons)
        root.addWidget(policy_group)

        self.retention_label = QLabel()
        self.retention_label.setWordWrap(True)
        root.addWidget(self.retention_label)

        self.backup_table = QTableWidget(0, 5)
        self.backup_table.setHorizontalHeaderLabels(
            ["Created", "Schema", "Size", "SHA-256", "Path"]
        )
        self.backup_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.backup_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.backup_table, 1)

        self.run_table = QTableWidget(0, 5)
        self.run_table.setHorizontalHeaderLabels(
            ["Started", "Operation", "Status", "Artifact", "Summary"]
        )
        self.run_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.run_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.run_table, 1)

        self.status_label = QLabel()
        root.addWidget(self.status_label)
        self.refresh()

    @staticmethod
    def _days() -> QSpinBox:
        control = QSpinBox()
        control.setRange(1, 36500)
        control.setSuffix(" days")
        return control

    def refresh(self) -> None:
        self.dashboard_data = self.service.dashboard(project_id=self.project_id)
        dashboard = self.dashboard_data
        health = dashboard.health
        state = "READY" if health.ready else "NEEDS ATTENTION"
        self.health_label.setText(
            f"{state} — schema {health.schema_version}/"
            f"{health.expected_schema_version}; quick_check={health.quick_check}; "
            f"foreign-key violations={len(health.foreign_key_violations)}; "
            f"database size={health.database_size_bytes:,} bytes"
        )
        policy = dashboard.policy
        self.enabled.setChecked(policy.enabled)
        self.session_days.setValue(policy.session_retention_days)
        self.notification_days.setValue(policy.notification_retention_days)
        self.activity_days.setValue(policy.activity_retention_days)
        self.snapshot_days.setValue(policy.snapshot_retention_days)
        self.run_days.setValue(policy.maintenance_run_retention_days)
        self.backup_count.setValue(policy.backup_retention_count)
        self.startup_check.setChecked(policy.run_quick_check_on_startup)
        preview = dashboard.retention
        details = ", ".join(
            f"{name}={count}"
            for name, count in preview.candidate_counts.items()
        )
        self.retention_label.setText(
            f"Cleanup preview: {preview.total_candidates} record(s). {details}"
        )
        self._populate_backups(dashboard)
        self._populate_runs(dashboard)
        self.status_label.setText("Hardening dashboard refreshed.")

    def save_policy(self) -> None:
        current = self.service.get_policy(self.project_id)
        self.service.save_policy(
            replace(
                current,
                enabled=self.enabled.isChecked(),
                session_retention_days=self.session_days.value(),
                notification_retention_days=self.notification_days.value(),
                activity_retention_days=self.activity_days.value(),
                snapshot_retention_days=self.snapshot_days.value(),
                maintenance_run_retention_days=self.run_days.value(),
                backup_retention_count=self.backup_count.value(),
                run_quick_check_on_startup=self.startup_check.isChecked(),
            )
        )
        self.refresh()
        self.status_label.setText("Maintenance policy saved.")

    def run_health_check(self, *, full: bool) -> None:
        health = self.service.run_health_check(
            project_id=self.project_id,
            full=full,
        )
        self.refresh()
        self.status_label.setText(
            "Integrity check passed." if health.ready else "Integrity check found issues."
        )

    def create_backup(self) -> None:
        artifact = self.service.create_backup(project_id=self.project_id)
        self.refresh()
        self.status_label.setText(
            f"Verified backup created: {artifact.path.name} ({artifact.sha256[:12]}…)"
        )

    def restore_backup(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "Restore verified S-Talking database backup",
            str(self.service.backup_dir),
            "SQLite database (*.db *.bak);;All files (*)",
        )
        if not selected:
            return
        confirmation = QMessageBox.question(
            self,
            "Restore database backup",
            "The current database will be backed up before restore. Continue?",
        )
        if confirmation != QMessageBox.Yes:
            return
        try:
            pre_restore = self.service.restore_backup(
                Path(selected),
                project_id=self.project_id,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        self.refresh()
        self.status_label.setText(
            f"Restore completed. Pre-restore backup: {pre_restore.path.name}"
        )

    def apply_retention(self) -> None:
        preview = self.service.retention_preview(project_id=self.project_id)
        if preview.total_candidates == 0:
            self.status_label.setText("No records match the retention policy.")
            return
        answer = QMessageBox.question(
            self,
            "Apply retention cleanup",
            f"Delete {preview.total_candidates} eligible record(s)? "
            "Incident-linked sessions are always preserved.",
        )
        if answer != QMessageBox.Yes:
            return
        deleted = self.service.apply_retention(project_id=self.project_id)
        self.refresh()
        self.status_label.setText(
            f"Retention cleanup deleted {deleted.total_candidates} record(s)."
        )

    def export_report(self) -> None:
        json_path, csv_path = self.service.export_report(
            self.export_dir,
            project_id=self.project_id,
        )
        self.status_label.setText(
            f"Exported {json_path.name} and {csv_path.name}."
        )

    def _populate_backups(self, dashboard: GenerationHardeningDashboard) -> None:
        self.backup_table.setRowCount(len(dashboard.backups))
        for row, artifact in enumerate(dashboard.backups):
            values = (
                artifact.created_at,
                str(artifact.schema_version),
                f"{artifact.size_bytes:,}",
                artifact.sha256,
                str(artifact.path),
            )
            for column, value in enumerate(values):
                self.backup_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_runs(self, dashboard: GenerationHardeningDashboard) -> None:
        self.run_table.setRowCount(len(dashboard.recent_runs))
        for row, run in enumerate(dashboard.recent_runs):
            values = (
                run.started_at,
                run.operation,
                run.status,
                run.artifact_path or "—",
                str(run.summary),
            )
            for column, value in enumerate(values):
                self.run_table.setItem(row, column, QTableWidgetItem(value))
