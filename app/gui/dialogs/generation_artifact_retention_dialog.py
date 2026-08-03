from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
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
from app.models.generation_artifact_retention import GenerationArtifactRetentionPolicy
from app.services.generation_artifact_retention_service import GenerationArtifactRetentionService


class GenerationArtifactRetentionDialog(QDialog):
    """Dry-run, archive, and clean stale governance artifacts safely."""

    def __init__(
        self,
        service: GenerationArtifactRetentionService,
        parent: QWidget | None = None,
        *,
        project_name: str = "",
        export_dir: Path | None = None,
        open_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.export_dir = Path(export_dir or service.reports_dir / "artifact-retention")
        self.open_path = open_path
        self.current_preview = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationArtifactRetentionDialog")
        self.setWindowTitle("Artifact retention")
        self.resize(1180, 800)
        self.setMinimumSize(820, 580)
        self._build()
        self._load_policy()
        self.refresh_preview()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Receipt, approval and run retention",
            "Preview every action, archive immutable evidence, and remove only known governance artifacts.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Loading retention preview", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        policy_section = DialogSection(
            "Retention policy",
            "Audio outputs, project sources, credentials and database files are never cleanup candidates.",
        )
        form = QFormLayout()
        self.enabled = QCheckBox("Enable artifact retention")
        self.launch_days = self._days_spin()
        self.run_days = self._days_spin()
        self.recovery_days = self._days_spin()
        self.approval_days = self._days_spin()
        self.budget_days = self._days_spin()
        self.orphan_days = self._days_spin(maximum=365)
        self.archive_first = QCheckBox("Create a verified ZIP archive before deletion")
        self.keep_integrity = QCheckBox("Keep mismatched or unreadable artifacts for manual review")
        form.addRow("Status", self.enabled)
        form.addRow("Launch receipts", self.launch_days)
        form.addRow("Execution runs", self.run_days)
        form.addRow("Recovery receipts", self.recovery_days)
        form.addRow("Guard approvals", self.approval_days)
        form.addRow("Budget records", self.budget_days)
        form.addRow("Orphan grace period", self.orphan_days)
        form.addRow("Archive", self.archive_first)
        form.addRow("Integrity issues", self.keep_integrity)
        policy_section.add_layout(form)
        row = QHBoxLayout()
        save = QPushButton("Save policy")
        save.setObjectName("dialogPrimaryAction")
        save.setIcon(action_icon("save"))
        save.clicked.connect(self.save_policy)
        row.addWidget(save)
        row.addStretch(1)
        policy_section.add_layout(row)
        self.workspace.add_body_widget(policy_section)

        candidates = DialogSection(
            "Cleanup preview",
            "Review items marked Archive/Delete. Protected integrity issues remain Review-only.",
        )
        self.candidate_table = QTableWidget(0, 8)
        self.candidate_table.setObjectName("artifactRetentionCandidateTable")
        self.candidate_table.setHorizontalHeaderLabels(
            ["Action", "Type", "Project", "Age", "Size", "Integrity", "Identifier", "Reason"]
        )
        self.candidate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.candidate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        candidates.add_widget(self.candidate_table)
        self.workspace.add_body_widget(candidates)

        runs = DialogSection(
            "Recent retention runs",
            "Every dry-run and applied cleanup is recorded with archive SHA-256 and reclaimed bytes.",
        )
        self.run_table = QTableWidget(0, 7)
        self.run_table.setObjectName("artifactRetentionRunTable")
        self.run_table.setHorizontalHeaderLabels(
            ["Started", "Status", "Mode", "Candidates", "Archived", "Deleted", "Run ID"]
        )
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.run_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        runs.add_widget(self.run_table)
        self.workspace.add_body_widget(runs)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        refresh = QPushButton("Refresh preview")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh_preview)
        dry_run = QPushButton("Record dry run")
        dry_run.clicked.connect(self.record_dry_run)
        export = QPushButton("Export preview")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_preview)
        apply_button = QPushButton("Archive and clean")
        apply_button.setObjectName("dialogPrimaryAction")
        apply_button.setIcon(action_icon("warning"))
        apply_button.clicked.connect(self.apply_cleanup)
        archives = QPushButton("Open archives")
        archives.clicked.connect(self.open_archives)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for widget in (refresh, dry_run, export, archives, apply_button, close):
            self.workspace.add_footer_widget(widget)

    @staticmethod
    def _days_spin(*, maximum: int = 3650) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(1, maximum)
        spin.setSuffix(" days")
        return spin

    def _load_policy(self) -> None:
        policy = self.service.get_policy(self.project_name)
        self.enabled.setChecked(policy.enabled)
        self.launch_days.setValue(policy.launch_receipt_days)
        self.run_days.setValue(policy.execution_run_days)
        self.recovery_days.setValue(policy.recovery_receipt_days)
        self.approval_days.setValue(policy.approval_record_days)
        self.budget_days.setValue(policy.budget_record_days)
        self.orphan_days.setValue(policy.orphan_grace_days)
        self.archive_first.setChecked(policy.archive_before_delete)
        self.keep_integrity.setChecked(policy.keep_integrity_issues)

    def _policy_from_form(self) -> GenerationArtifactRetentionPolicy:
        return GenerationArtifactRetentionPolicy(
            project_name=self.project_name,
            enabled=self.enabled.isChecked(),
            launch_receipt_days=self.launch_days.value(),
            execution_run_days=self.run_days.value(),
            recovery_receipt_days=self.recovery_days.value(),
            approval_record_days=self.approval_days.value(),
            budget_record_days=self.budget_days.value(),
            orphan_grace_days=self.orphan_days.value(),
            archive_before_delete=self.archive_first.isChecked(),
            keep_integrity_issues=self.keep_integrity.isChecked(),
        )

    def save_policy(self) -> GenerationArtifactRetentionPolicy:
        policy = self.service.save_policy(self._policy_from_form())
        self.status_label.setText("Retention policy saved.")
        self.refresh_preview()
        return policy

    def refresh_preview(self) -> None:
        self.current_preview = self.service.preview(
            project_name=self.project_name,
            policy=self._policy_from_form(),
        )
        preview = self.current_preview
        self.summary.update_status(
            f"{preview.actionable_count:,} actionable artifact(s)",
            f"{self._format_bytes(preview.total_bytes)} · {preview.archive_count:,} archive · "
            f"{preview.delete_count:,} delete · {preview.review_count:,} manual review",
            tone="warning" if preview.actionable_count else "success",
        )
        self.candidate_table.setRowCount(len(preview.candidates))
        for row, item in enumerate(preview.candidates):
            values = (
                item.action.title(),
                item.artifact_type.replace("_", " ").title(),
                item.project_name,
                f"{item.age_days:,} d",
                self._format_bytes(item.size_bytes),
                item.integrity_status.title(),
                item.identifier,
                item.reason,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if column == 0:
                    cell.setData(Qt.UserRole, item.candidate_id)
                self.candidate_table.setItem(row, column, cell)
        self.candidate_table.resizeColumnsToContents()
        self._refresh_runs()
        self.status_label.setText(
            f"Preview {preview.preview_id[:12]} contains {len(preview.candidates):,} candidate(s)."
        )

    def _refresh_runs(self) -> None:
        records = self.service.list_runs(limit=50)
        self.run_table.setRowCount(len(records))
        for row, item in enumerate(records):
            values = (
                item.started_at,
                item.status.title(),
                "Dry run" if item.dry_run else "Applied",
                item.candidate_count,
                item.archived_count,
                item.deleted_count,
                item.run_id,
            )
            for column, value in enumerate(values):
                self.run_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.run_table.resizeColumnsToContents()

    def record_dry_run(self):
        if self.current_preview is None:
            self.refresh_preview()
        result = self.service.apply(self.current_preview, dry_run=True)
        self.status_label.setText(f"Recorded dry run {result.run_id}.")
        self._refresh_runs()
        return result

    def export_preview(self):
        if self.current_preview is None:
            self.refresh_preview()
        result = self.service.export_preview(self.current_preview, self.export_dir)
        self.status_label.setText(f"Exported {result[0].name} and {result[1].name}.")
        return result

    def apply_cleanup(self):
        if self.current_preview is None:
            self.refresh_preview()
        if self.current_preview.actionable_count <= 0:
            self.status_label.setText("No actionable artifacts match the retention policy.")
            return None
        answer = QMessageBox.question(
            self,
            "Archive and clean artifacts",
            f"Archive and remove {self.current_preview.actionable_count:,} stale artifact(s)?\n\n"
            "Audio outputs and project files are outside this cleanup scope.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return None
        try:
            result = self.service.apply(self.current_preview)
        except ValueError as exc:
            self.status_label.setText(str(exc))
            self.refresh_preview()
            return None
        self.status_label.setText(
            f"{result.status.title()}: deleted {result.deleted_count:,}, "
            f"archived {result.archived_count:,}, reclaimed {self._format_bytes(result.reclaimed_bytes)}."
        )
        self.refresh_preview()
        return result

    def open_archives(self) -> None:
        folder = self.service.reports_dir / self.service.ARCHIVE_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        if self.open_path is not None:
            self.open_path(folder)
        self.status_label.setText(str(folder))

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = max(0, int(value))
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.2f} MB"
