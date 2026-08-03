from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_execution_receipt import GenerationExecutionReceipt
from app.services.generation_execution_receipt_service import GenerationExecutionReceiptService


class GenerationExecutionReceiptDialog(QDialog):
    """Audit center for planned-versus-actual execution receipts and output manifests."""

    def __init__(
        self,
        service: GenerationExecutionReceiptService,
        parent: QWidget | None = None,
        *,
        project_name: str = "all-projects",
        export_dir: Path | None = None,
        open_path: Callable[[Path], None] | None = None,
        copy_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = project_name
        self.export_dir = Path(export_dir or service.reports_dir / "execution-receipts")
        self.open_path_callback = open_path
        self.copy_path_callback = copy_path
        self.all_receipts: list[GenerationExecutionReceipt] = []
        self.filtered_receipts: list[GenerationExecutionReceipt] = []
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationExecutionReceiptDialog")
        self.setWindowTitle("Generation execution receipts")
        self.resize(1260, 820)
        self.setMinimumSize(800, 560)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Generation execution receipts",
            "Compare planned work with actual outputs, verify hashes and inspect missing or unexpected files.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        filters_section = DialogSection(
            "Find execution receipts",
            "Filter by project and outcome, or search run IDs, receipts, providers, output paths and filenames.",
        )
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        self.current_project_only = QCheckBox("Current project only")
        has_project = self.project_name not in {"", "all-projects"}
        self.current_project_only.setEnabled(has_project)
        self.current_project_only.setChecked(has_project)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All outcomes", "")
        for label, value in (
            ("Completed", "completed"),
            ("Partial", "partial"),
            ("Failed", "failed"),
            ("Cancelled", "cancelled"),
        ):
            self.status_filter.addItem(label, value)
        self.search = QLineEdit()
        self.search.setObjectName("executionReceiptSearch")
        self.search.setPlaceholderText("Search run, receipt, trace, provider, output or filename…")
        self.search.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(action_icon("general.refresh"))
        filters.addWidget(self.current_project_only, 0, 0)
        filters.addWidget(self.status_filter, 0, 1)
        filters.addWidget(self.search, 1, 0, 1, 2)
        filters.addWidget(self.refresh_button, 1, 2)
        filters.setColumnStretch(1, 1)
        filters_section.add_layout(filters)
        self.workspace.add_body_widget(filters_section)

        self.summary_card = DialogStatusCard(
            "No execution receipts loaded",
            "Planned-versus-actual metrics update after filters are applied.",
            tone="info",
        )
        self.summary_card.setObjectName("executionReceiptSummaryCard")
        self.workspace.add_body_widget(self.summary_card)

        records_section = DialogSection(
            "Execution receipt archive",
            "Each receipt is linked to one run and protects its output manifest with SHA-256 integrity metadata.",
        )
        self.table = QTableWidget(0, 11)
        self.table.setObjectName("generationExecutionReceiptTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Finished",
                "Project",
                "Status",
                "Planned",
                "Actual",
                "Created",
                "Overwritten",
                "Missing",
                "Unexpected",
                "Integrity",
                "Run ID",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(250)
        self.table.horizontalHeader().setStretchLastSection(True)
        records_section.add_widget(self.table, 1)
        self.workspace.add_body_widget(records_section, 1)

        details_section = DialogSection(
            "Selected receipt",
            "Inspect plan variance, linked artifacts and the generated output manifest.",
        )
        self.details = QPlainTextEdit()
        self.details.setObjectName("generationExecutionReceiptDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(115)
        self.details.setMaximumHeight(170)
        details_section.add_widget(self.details)
        self.manifest = QTableWidget(0, 6)
        self.manifest.setObjectName("generationOutputManifestTable")
        self.manifest.setHorizontalHeaderLabels(
            ["Row", "Filename", "Disposition", "Status", "Size", "SHA-256"]
        )
        self.manifest.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.manifest.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.manifest.setAlternatingRowColors(True)
        self.manifest.setShowGrid(False)
        self.manifest.setMinimumHeight(180)
        self.manifest.horizontalHeader().setStretchLastSection(True)
        details_section.add_widget(self.manifest, 1)
        self.workspace.add_body_widget(details_section, 1)

        actions_section = DialogSection(
            "Receipt actions",
            "Open linked evidence or export a secret-free catalog of the filtered receipts.",
        )
        actions = QGridLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_receipt_button = QPushButton("Open receipt JSON")
        self.open_manifest_button = QPushButton("Open output manifest")
        self.open_session_button = QPushButton("Open execution session")
        self.open_launch_button = QPushButton("Open launch receipt")
        self.open_report_button = QPushButton("Open final report")
        self.open_output_button = QPushButton("Open output folder")
        self.copy_run_id_button = QPushButton("Copy run ID")
        self.export_button = QPushButton("Export filtered catalog")
        for index, (button, icon_name) in enumerate(
            (
                (self.open_receipt_button, "report"),
                (self.open_manifest_button, "report"),
                (self.open_session_button, "history"),
                (self.open_launch_button, "report"),
                (self.open_report_button, "report"),
                (self.open_output_button, "project.output_folder"),
                (self.copy_run_id_button, "general.copy"),
                (self.export_button, "save"),
            )
        ):
            button.setObjectName("historyToolAction")
            button.setIcon(action_icon(icon_name))
            button.setMinimumHeight(34)
            actions.addWidget(button, index // 4, index % 4)
        for column in range(4):
            actions.setColumnStretch(column, 1)
        actions_section.add_layout(actions)
        self.workspace.add_body_widget(actions_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        close_button = QPushButton("Close")
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(close_button)

        self.refresh_button.clicked.connect(self.refresh)
        self.current_project_only.toggled.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.update_details)
        self.open_receipt_button.clicked.connect(lambda: self._open_selected("path"))
        self.open_manifest_button.clicked.connect(lambda: self._open_selected("manifest_csv_path"))
        self.open_session_button.clicked.connect(lambda: self._open_selected("execution_session_path"))
        self.open_launch_button.clicked.connect(lambda: self._open_selected("launch_receipt_path"))
        self.open_report_button.clicked.connect(lambda: self._open_selected("report_path"))
        self.open_output_button.clicked.connect(lambda: self._open_selected("output_directory"))
        self.copy_run_id_button.clicked.connect(self.copy_run_id)
        self.export_button.clicked.connect(self.export_filtered)
        close_button.clicked.connect(self.close)
        self._update_action_state()

    def refresh(self) -> None:
        self.all_receipts = self.service.list_receipts(limit=1000)
        self.apply_filters()

    def apply_filters(self) -> None:
        project_name = self.project_name if self.current_project_only.isChecked() else None
        status = str(self.status_filter.currentData() or "")
        search = self.search.text().strip()
        records = self.all_receipts
        if project_name:
            records = [item for item in records if item.project_name == project_name]
        if status:
            records = [item for item in records if item.status == status]
        if search:
            key = search.casefold()
            records = [item for item in records if key in self.service._search_text(item)]
        self.filtered_receipts = records
        self._populate()

    def _populate(self) -> None:
        self.table.setRowCount(len(self.filtered_receipts))
        for row, receipt in enumerate(self.filtered_receipts):
            values = (
                receipt.finished_at.replace("T", " ")[:19],
                receipt.project_name,
                receipt.status.title(),
                str(receipt.planned_files),
                str(receipt.actual_outputs),
                str(receipt.created_outputs),
                str(receipt.overwritten_outputs),
                str(receipt.missing_outputs),
                str(receipt.unexpected_outputs),
                receipt.integrity_status.title(),
                receipt.run_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, receipt.receipt_id)
                self.table.setItem(row, column, item)
        summary = self.service.summary(self.filtered_receipts)
        tone = "warning" if summary.integrity_issue_count or summary.failed_outputs or summary.missing_outputs or summary.unexpected_outputs else "success"
        self.summary_card.update_status(
            f"{summary.total_count:,} receipt(s) · {summary.actual_outputs:,} actual output(s)",
            f"Planned {summary.planned_files:,} · Created {summary.created_outputs:,} · "
            f"Overwritten {summary.overwritten_outputs:,} · Skipped {summary.skipped_outputs:,} · "
            f"Failed {summary.failed_outputs:,} · Missing {summary.missing_outputs:,} · Unexpected {summary.unexpected_outputs:,}",
            tone=tone,
        )
        self.status_label.setText(f"Showing {len(self.filtered_receipts):,} of {len(self.all_receipts):,} receipts")
        if self.filtered_receipts:
            self.table.selectRow(0)
        else:
            self.details.clear()
            self.manifest.setRowCount(0)
            self._update_action_state()

    def selected_receipt(self) -> GenerationExecutionReceipt | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.filtered_receipts):
            return None
        return self.filtered_receipts[row]

    def update_details(self) -> None:
        receipt = self.selected_receipt()
        if receipt is None:
            self.details.clear()
            self.manifest.setRowCount(0)
            self._update_action_state()
            return
        self.details.setPlainText(
            "\n".join(
                (
                    f"Execution receipt: {receipt.receipt_id}",
                    f"Run ID: {receipt.run_id}",
                    f"Status / integrity: {receipt.status} / {receipt.integrity_status}",
                    f"Project: {receipt.project_name} · Launch receipt {receipt.launch_receipt_id or '—'}",
                    f"Provider / model / voice: {receipt.provider} / {receipt.model_id or '—'} / {receipt.voice_id or '—'}",
                    f"Planned files / characters / requests: {receipt.planned_files} / {receipt.planned_characters:,} / {receipt.planned_requests}",
                    f"Created / overwritten / skipped: {receipt.created_outputs} / {receipt.overwritten_outputs} / {receipt.skipped_outputs}",
                    f"Failed / missing / incomplete / unexpected: {receipt.failed_outputs} / {receipt.missing_outputs} / {receipt.incomplete_outputs} / {receipt.unexpected_outputs}",
                    f"Output bytes: {receipt.total_bytes:,} · Elapsed {receipt.elapsed_seconds:.1f}s",
                    f"Output: {receipt.output_directory}",
                )
            )
        )
        self.manifest.setRowCount(len(receipt.entries))
        for row, entry in enumerate(receipt.entries):
            values = (
                str(entry.row_number or "—"),
                entry.filename,
                entry.disposition,
                entry.job_status,
                f"{entry.size_bytes:,}",
                entry.sha256[:16] if entry.sha256 else "—",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(entry.actual_path or entry.expected_path)
                self.manifest.setItem(row, column, item)
        self._update_action_state()

    def _update_action_state(self) -> None:
        receipt = self.selected_receipt()
        paths = {
            self.open_receipt_button: receipt.path if receipt else None,
            self.open_manifest_button: receipt.manifest_csv_path if receipt else None,
            self.open_session_button: Path(receipt.execution_session_path) if receipt and receipt.execution_session_path else None,
            self.open_launch_button: Path(receipt.launch_receipt_path) if receipt and receipt.launch_receipt_path else None,
            self.open_report_button: Path(receipt.report_path) if receipt and receipt.report_path else None,
            self.open_output_button: Path(receipt.output_directory) if receipt and receipt.output_directory else None,
        }
        for button, path in paths.items():
            button.setEnabled(path is not None and path.exists())
        self.copy_run_id_button.setEnabled(receipt is not None)
        self.export_button.setEnabled(bool(self.filtered_receipts))

    def _open_selected(self, attribute: str) -> None:
        receipt = self.selected_receipt()
        if receipt is None:
            return
        value = getattr(receipt, attribute, "")
        path = value if isinstance(value, Path) else Path(str(value))
        if self.open_path_callback is not None and path.exists():
            self.open_path_callback(path)

    def copy_run_id(self) -> None:
        receipt = self.selected_receipt()
        if receipt:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(receipt.run_id)
            self.status_label.setText("Run ID copied.")

    def export_filtered(self) -> None:
        json_path, csv_path = self.service.export(
            self.filtered_receipts,
            self.export_dir,
            project_name=self.project_name,
        )
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}")
        if self.open_path_callback is not None:
            self.open_path_callback(json_path.parent)
