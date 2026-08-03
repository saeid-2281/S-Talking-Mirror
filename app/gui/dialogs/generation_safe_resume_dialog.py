from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models import AppSettings, TTSJob
from app.models.generation_execution_receipt import GenerationExecutionReceipt
from app.models.generation_safe_resume import GenerationResumePreview
from app.services.generation_safe_resume_service import GenerationSafeResumeService


class GenerationSafeResumeDialog(QDialog):
    """Preview a historical run recovery without bypassing normal launch preflight."""

    def __init__(
        self,
        service: GenerationSafeResumeService,
        receipt: GenerationExecutionReceipt,
        current_jobs: list[TTSJob],
        settings: AppSettings,
        output_directory: Path,
        project_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.receipt = receipt
        self.current_jobs = current_jobs
        self.settings = settings
        self.output_directory = Path(output_directory)
        self.project_name = project_name
        self.preview: GenerationResumePreview | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationSafeResumeDialog")
        self.setWindowTitle("Safe resume and recovery")
        self.resize(860, 720)
        self.setMinimumSize(680, 520)
        self._build()
        self.refresh_preview()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Safe resume and recovery",
            "Recover only the required jobs from a verified execution receipt, then run the normal preflight and baseline guard again.",
            icon_name="history",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.status_card = DialogStatusCard(
            "Evaluating parent run",
            f"Parent run {self.receipt.run_id or '—'}",
            tone="info",
        )
        self.workspace.add_body_widget(self.status_card)

        scope_section = DialogSection(
            "Recovery scope",
            "The recommended scope retries failed, missing, and incomplete outputs only. Entire run remains protected by the current file policy.",
        )
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("generationSafeResumeScope")
        for key, label in self.service.SCOPES.items():
            self.scope_combo.addItem(label, key)
        scope_section.add_widget(self.scope_combo)
        self.workspace.add_body_widget(scope_section)

        details_section = DialogSection("Compatibility and safeguards")
        self.details = QPlainTextEdit()
        self.details.setObjectName("generationSafeResumeDetails")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(170)
        details_section.add_widget(self.details)
        self.workspace.add_body_widget(details_section)

        jobs_section = DialogSection(
            "Recovery candidates",
            "Only selected and matched rows will be prepared. Current source text is used; historical receipts never store source text.",
        )
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("generationSafeResumeTable")
        self.table.setHorizontalHeaderLabels(("Row", "Filename", "Parent result", "Selected", "Output exists", "Reason"))
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        jobs_section.add_widget(self.table)
        self.workspace.add_body_widget(jobs_section, 1)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setWordWrap(True)
        cancel_button = QPushButton("Cancel")
        self.prepare_button = QPushButton("Prepare recovery queue")
        self.prepare_button.setObjectName("dialogPrimaryAction")
        self.prepare_button.setIcon(action_icon("general.refresh"))
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(cancel_button)
        self.workspace.add_footer_widget(self.prepare_button)

        self.scope_combo.currentIndexChanged.connect(self.refresh_preview)
        cancel_button.clicked.connect(self.reject)
        self.prepare_button.clicked.connect(self.accept)

    def refresh_preview(self) -> GenerationResumePreview:
        scope = str(self.scope_combo.currentData() or "unresolved")
        self.preview = self.service.preview(
            receipt=self.receipt,
            current_jobs=self.current_jobs,
            settings=self.settings,
            output_directory=self.output_directory,
            project_name=self.project_name,
            scope=scope,
        )
        preview = self.preview
        tone = "success" if preview.allowed and not preview.warnings else "warning" if preview.allowed else "error"
        title = "Recovery queue can be prepared" if preview.allowed else "Recovery is blocked"
        self.status_card.update_status(
            title,
            f"{preview.selected_count} selected job(s) · {preview.matched_count} current queue match(es) · parent run {preview.parent_run_id}",
            tone=tone,
        )
        sections: list[str] = []
        if preview.blockers:
            sections.append("BLOCKERS\n" + "\n".join(f"• {item}" for item in preview.blockers))
        if preview.warnings:
            sections.append("WARNINGS\n" + "\n".join(f"• {item}" for item in preview.warnings))
        if preview.recommendations:
            sections.append("NEXT SAFETY CHECKS\n" + "\n".join(f"• {item}" for item in preview.recommendations))
        self.details.setPlainText("\n\n".join(sections) or "No compatibility issues detected.")
        self.table.setRowCount(len(preview.candidates))
        for row, item in enumerate(preview.candidates):
            values = (
                str(item.row_number),
                item.filename,
                item.parent_disposition,
                "Yes" if item.selected else "No",
                "Yes" if item.output_exists else "No",
                item.reason,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(item.actual_path or item.expected_path)
                self.table.setItem(row, column, cell)
        self.prepare_button.setEnabled(preview.allowed)
        self.status_label.setText(
            "Normal Unified Preflight, baseline guard, quota, provider readiness, and output conflict checks will run again when Start Generation is pressed."
        )
        return preview
