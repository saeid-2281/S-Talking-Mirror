from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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
from app.gui.dialogs.generation_launch_guard_approval_dialog import (
    GenerationLaunchGuardApprovalDialog,
)
from app.gui.dialogs.generation_launch_guard_policy_dialog import (
    GenerationLaunchGuardPolicyDialog,
)
from app.gui.dialogs.generation_launch_receipt_drift_dialog import GenerationLaunchReceiptDriftDialog
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_launch_receipt import GenerationLaunchReceipt
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationLaunchReceiptDialog(QDialog):
    """Searchable audit center for generation launch receipts."""

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
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
        self.export_dir = Path(export_dir or service.reports_dir / "launch-receipts")
        self.open_path_callback = open_path
        self.copy_path_callback = copy_path
        self.all_receipts: list[GenerationLaunchReceipt] = []
        self.filtered_receipts: list[GenerationLaunchReceipt] = []
        self.drift_dialogs: list[GenerationLaunchReceiptDriftDialog] = []
        self.guard_policy_dialogs: list[GenerationLaunchGuardPolicyDialog] = []
        self.guard_approval_dialogs: list[GenerationLaunchGuardApprovalDialog] = []
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchReceiptDialog")
        self.setWindowTitle("Generation launch receipts")
        self.resize(1220, 780)
        self.setMinimumSize(720, 520)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Generation launch receipts",
            "Verify launch decisions, inspect risk acknowledgements and open the exact receipt behind a generation run.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        filters_section = DialogSection(
            "Find launch receipts",
            "Filter by project, provider, risk or integrity. Search checks IDs, fingerprints, models, voices and output paths.",
        )
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(8)
        self.current_project_only = QCheckBox("Current project only")
        has_project = self.project_name not in {"", "all-projects"}
        self.current_project_only.setEnabled(has_project)
        self.current_project_only.setChecked(has_project)
        self.provider_filter = QComboBox()
        self.provider_filter.addItem("All providers", "")
        self.risk_filter = QComboBox()
        self.risk_filter.addItem("All risk levels", "")
        for label, value in (("High risk", "high"), ("Medium risk", "medium"), ("Low risk", "low"), ("Unknown risk", "unknown")):
            self.risk_filter.addItem(label, value)
        self.integrity_filter = QComboBox()
        self.integrity_filter.addItem("All integrity states", "")
        for label, value in (("Verified", "verified"), ("Legacy", "legacy"), ("Mismatch", "mismatch"), ("Unreadable", "unreadable")):
            self.integrity_filter.addItem(label, value)
        self.search = QLineEdit()
        self.search.setObjectName("launchReceiptSearch")
        self.search.setPlaceholderText("Search receipt, fingerprint, provider, model, voice or output…")
        self.search.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("launchReceiptRefreshButton")
        self.refresh_button.setIcon(action_icon("general.refresh"))
        filters.addWidget(self.current_project_only, 0, 0)
        filters.addWidget(self.provider_filter, 0, 1)
        filters.addWidget(self.risk_filter, 0, 2)
        filters.addWidget(self.integrity_filter, 0, 3)
        filters.addWidget(self.search, 1, 0, 1, 3)
        filters.addWidget(self.refresh_button, 1, 3)
        filters.setColumnStretch(2, 1)
        filters_section.add_layout(filters)
        self.workspace.add_body_widget(filters_section)

        self.summary_card = DialogStatusCard(
            "No launch receipts loaded",
            "Launch audit metrics update after filters are applied.",
            tone="info",
        )
        self.summary_card.setObjectName("launchReceiptSummaryCard")
        metric_row = QHBoxLayout()
        metric_row.setContentsMargins(0, 7, 0, 0)
        metric_row.setSpacing(7)
        self.metric_values: dict[str, QLabel] = {}
        for key, caption in (
            ("receipts", "Receipts"),
            ("verified", "Verified"),
            ("legacy", "Legacy"),
            ("issues", "Integrity issues"),
            ("risk", "High risk"),
        ):
            card = QFrame()
            card.setObjectName("historyMetricCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(10, 7, 10, 7)
            layout.setSpacing(1)
            label = QLabel(caption)
            label.setObjectName("historyMetricCaption")
            value = QLabel("—")
            value.setObjectName("historyMetricValue")
            layout.addWidget(label)
            layout.addWidget(value)
            self.metric_values[key] = value
            metric_row.addWidget(card, 1)
        self.summary_card.layout().addLayout(metric_row)
        self.summary_text = QLabel()
        self.summary_text.setObjectName("historySummaryText")
        self.summary_text.setWordWrap(True)
        self.summary_card.layout().addWidget(self.summary_text)
        self.workspace.add_body_widget(self.summary_card)

        records_section = DialogSection(
            "Launch audit archive",
            "Integrity mismatch means the JSON content changed after the receipt was written. Legacy receipts remain readable but are not cryptographically verifiable.",
        )
        self.table = QTableWidget(0, 12)
        self.table.setObjectName("generationLaunchReceiptTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Created",
                "Project",
                "Integrity",
                "Review",
                "Risk",
                "Provider",
                "Model",
                "Files",
                "Characters",
                "Cost",
                "Acknowledged",
                "Receipt ID",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(300)
        self.table.horizontalHeader().setStretchLastSection(True)
        records_section.add_widget(self.table, 1)
        self.workspace.add_body_widget(records_section, 1)

        details_section = DialogSection(
            "Selected receipt",
            "Review the immutable decision context before opening files or output locations.",
        )
        self.details = QPlainTextEdit()
        self.details.setObjectName("generationLaunchReceiptDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(125)
        self.details.setMaximumHeight(190)
        self.details.setPlaceholderText("Select a launch receipt to inspect its audit details.")
        details_section.add_widget(self.details)
        self.workspace.add_body_widget(details_section)

        actions_section = DialogSection(
            "Receipt actions",
            "Open or copy only the selected receipt. Export creates a secret-free JSON and CSV catalog of the filtered rows.",
        )
        self.baseline_label = QLabel("No project baseline selected.")
        self.baseline_label.setObjectName("historySummaryText")
        self.baseline_label.setWordWrap(True)
        actions_section.add_widget(self.baseline_label)
        self.guard_policy_label = QLabel("Baseline guard policy is not available.")
        self.guard_policy_label.setObjectName("historySummaryText")
        self.guard_policy_label.setWordWrap(True)
        actions_section.add_widget(self.guard_policy_label)
        self.guard_approval_label = QLabel("No exception approvals loaded.")
        self.guard_approval_label.setObjectName("historySummaryText")
        self.guard_approval_label.setWordWrap(True)
        actions_section.add_widget(self.guard_approval_label)

        actions = QGridLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        self.set_baseline_button = QPushButton("Set as project baseline")
        self.clear_baseline_button = QPushButton("Clear project baseline")
        self.compare_baseline_button = QPushButton("Compare to baseline")
        self.guard_policy_button = QPushButton("Baseline guard policy")
        self.guard_approval_button = QPushButton("Approval operations")
        self.open_json_button = QPushButton("Open JSON receipt")
        self.open_markdown_button = QPushButton("Open Markdown receipt")
        self.open_output_button = QPushButton("Open output")
        self.copy_path_button = QPushButton("Copy receipt path")
        self.copy_fingerprint_button = QPushButton("Copy fingerprint")
        self.export_button = QPushButton("Export filtered catalog")
        action_specs = (
            (self.set_baseline_button, "save"),
            (self.clear_baseline_button, "general.clear"),
            (self.compare_baseline_button, "report"),
            (self.guard_policy_button, "settings"),
            (self.guard_approval_button, "report"),
            (self.open_json_button, "report"),
            (self.open_markdown_button, "report"),
            (self.open_output_button, "project.output_folder"),
            (self.copy_path_button, "general.copy"),
            (self.copy_fingerprint_button, "general.copy"),
            (self.export_button, "save"),
        )
        for index, (button, icon_name) in enumerate(action_specs):
            button.setObjectName("historyToolAction")
            button.setIcon(action_icon(icon_name))
            button.setMinimumHeight(34)
            actions.addWidget(button, index // 3, index % 3)
        for column in range(3):
            actions.setColumnStretch(column, 1)
        actions_section.add_layout(actions)
        self.workspace.add_body_widget(actions_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setWordWrap(True)
        close_button = QPushButton("Close")
        close_button.setObjectName("launchReceiptCloseButton")
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(close_button)

        self.refresh_button.clicked.connect(self.refresh)
        self.current_project_only.toggled.connect(self.apply_filters)
        self.provider_filter.currentIndexChanged.connect(self.apply_filters)
        self.risk_filter.currentIndexChanged.connect(self.apply_filters)
        self.integrity_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.update_details)
        self.set_baseline_button.clicked.connect(self.set_selected_baseline)
        self.clear_baseline_button.clicked.connect(self.clear_selected_baseline)
        self.compare_baseline_button.clicked.connect(self.compare_selected_to_baseline)
        self.guard_policy_button.clicked.connect(self.open_guard_policy)
        self.guard_approval_button.clicked.connect(self.open_guard_approvals)
        self.open_json_button.clicked.connect(self.open_json)
        self.open_markdown_button.clicked.connect(self.open_markdown)
        self.open_output_button.clicked.connect(self.open_output)
        self.copy_path_button.clicked.connect(self.copy_receipt_path)
        self.copy_fingerprint_button.clicked.connect(self.copy_fingerprint)
        self.export_button.clicked.connect(self.export_filtered)
        close_button.clicked.connect(self.close)
        self._update_action_state()

    def refresh(self) -> None:
        self.all_receipts = self.service.list_receipts(limit=1000)
        current_provider = self.provider_filter.currentData()
        providers = sorted({item.provider for item in self.all_receipts if item.provider})
        self.provider_filter.blockSignals(True)
        self.provider_filter.clear()
        self.provider_filter.addItem("All providers", "")
        for provider in providers:
            self.provider_filter.addItem(provider, provider)
        provider_index = self.provider_filter.findData(current_provider)
        self.provider_filter.setCurrentIndex(max(0, provider_index))
        self.provider_filter.blockSignals(False)
        self.apply_filters()
        self.refresh_baseline_status()
        self.refresh_guard_policy_status()
        self.refresh_guard_approval_status()

    def apply_filters(self) -> None:
        project_name = self.project_name if self.current_project_only.isChecked() else None
        provider = str(self.provider_filter.currentData() or "")
        risk = str(self.risk_filter.currentData() or "")
        integrity = str(self.integrity_filter.currentData() or "")
        search = self.search.text()
        records = self.all_receipts
        if project_name:
            records = [item for item in records if item.project_name.casefold() == project_name.casefold()]
        if provider:
            records = [item for item in records if item.provider.casefold() == provider.casefold()]
        if risk:
            records = [item for item in records if item.risk_level.casefold() == risk.casefold()]
        if integrity:
            records = [item for item in records if item.integrity_status.casefold() == integrity.casefold()]
        if search.strip():
            key = search.strip().casefold()
            records = [
                item
                for item in records
                if key
                in " ".join(
                    (
                        item.receipt_id,
                        item.project_name,
                        item.launch_fingerprint,
                        item.provider,
                        item.model_id,
                        item.voice_id,
                        item.output_directory,
                    )
                ).casefold()
            ]
        self.filtered_receipts = list(records)
        self._render_table()
        self._render_summary()
        self.update_details()

    def selected_receipt(self) -> GenerationLaunchReceipt | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        return self.filtered_receipts[index] if 0 <= index < len(self.filtered_receipts) else None

    def update_details(self) -> None:
        receipt = self.selected_receipt()
        project = receipt.project_name if receipt else None
        self.refresh_baseline_status(project)
        self.refresh_guard_policy_status(project)
        self.refresh_guard_approval_status(project)
        if receipt is None:
            self.details.clear()
            self._update_action_state()
            return
        acknowledgement = ", ".join(receipt.acknowledged_codes) or "None required"
        required = ", ".join(receipt.required_acknowledgements) or "None"
        self.details.setPlainText(
            "\n".join(
                (
                    f"Receipt ID: {receipt.receipt_id or 'Legacy receipt'}",
                    f"Created: {receipt.created_at}",
                    f"Project: {receipt.project_name}",
                    f"Integrity: {receipt.integrity_status} — {receipt.integrity_message}",
                    f"Launch fingerprint: {receipt.launch_fingerprint or 'Unavailable'}",
                    f"Preflight / review: {receipt.preflight_status} / {receipt.review_status}",
                    f"Provider: {receipt.provider} · Model: {receipt.model_id or 'Default'} · Voice: {receipt.voice_id or 'Default'}",
                    f"Scope: {receipt.files:,} files · {receipt.characters:,} characters · {receipt.provider_requests:,} requests",
                    f"Risk / cost: {receipt.risk_level} · {receipt.currency} {receipt.estimated_cost:,.4f}",
                    f"Acknowledged: {acknowledgement}",
                    f"Required acknowledgements: {required}",
                    f"Guard exception approval: {receipt.guard_approval_id or 'None'}",
                    f"Output: {receipt.output_directory or 'Unavailable'}",
                    f"JSON: {receipt.path}",
                )
            )
        )
        self._update_action_state()

    def refresh_baseline_status(self, project_name: str | None = None) -> None:
        project = project_name or (
            self.project_name if self.project_name not in {"", "all-projects"} else ""
        )
        if not project:
            receipt = self.selected_receipt()
            project = receipt.project_name if receipt is not None else ""
        baseline = self.service.baseline(project) if project else None
        if baseline is None:
            self.baseline_label.setText(
                "No project baseline selected. Choose a trusted receipt to enable drift comparison."
            )
            return
        self.baseline_label.setText(
            f"Baseline for {baseline.project_name}: "
            f"{baseline.receipt_id or baseline.launch_fingerprint[:12] or baseline.path.name} "
            f"· {baseline.integrity_status.title()} · {baseline.created_at}"
        )

    def refresh_guard_policy_status(self, project_name: str | None = None) -> None:
        project = project_name or (
            self.project_name if self.project_name not in {"", "all-projects"} else ""
        )
        if not project:
            receipt = self.selected_receipt()
            project = receipt.project_name if receipt is not None else ""
        if not project:
            self.guard_policy_label.setText(
                "Select a project receipt to review its baseline guard policy."
            )
            return
        policy = self.service.guard_policy(project)
        mode_label = {
            "off": "Off",
            "warn": "Warn and acknowledge",
            "enforce": "Enforce critical drift",
        }.get(policy.mode, policy.mode.title())
        self.guard_policy_label.setText(
            f"Baseline guard for {project}: {mode_label} · "
            f"{len(policy.protected_categories):,} protected category group(s)."
        )

    def refresh_guard_approval_status(self, project_name: str | None = None) -> None:
        project = project_name or (
            self.project_name if self.project_name not in {"", "all-projects"} else ""
        )
        if not project:
            receipt = self.selected_receipt()
            project = receipt.project_name if receipt is not None else ""
        if not project:
            self.guard_approval_label.setText(
                "Select a project receipt to review exception approvals."
            )
            return
        approvals = self.service.list_guard_approvals(
            project_name=project,
            include_expired=True,
        )
        active = sum(item.status == "approved" for item in approvals)
        self.guard_approval_label.setText(
            f"Guard exceptions for {project}: {active:,} active · "
            f"{len(approvals):,} total audit record(s)."
        )

    def open_guard_approvals(self) -> GenerationLaunchGuardApprovalDialog | None:
        receipt = self.selected_receipt()
        project = receipt.project_name if receipt is not None else self.project_name
        project = project or "all-projects"
        dialog = GenerationLaunchGuardApprovalDialog(
            self.service,
            project,
            self,
            export_dir=self.export_dir / "approvals",
        )
        self.guard_approval_dialogs.append(dialog)
        dialog.finished.connect(self._guard_approval_dialog_finished)
        dialog.show()
        return dialog

    def _guard_approval_dialog_finished(self, _result: int) -> None:
        dialog = self.sender()
        project = getattr(dialog, "project_name", "")
        if dialog in self.guard_approval_dialogs:
            self.guard_approval_dialogs.remove(dialog)
        self.refresh_guard_approval_status(project)

    def open_guard_policy(self) -> GenerationLaunchGuardPolicyDialog | None:
        receipt = self.selected_receipt()
        project = receipt.project_name if receipt is not None else self.project_name
        if not project or project == "all-projects":
            self.status_label.setText(
                "Select a project receipt before editing its baseline guard policy."
            )
            return None
        dialog = GenerationLaunchGuardPolicyDialog(self.service, project, self)
        self.guard_policy_dialogs.append(dialog)
        dialog.finished.connect(self._guard_policy_dialog_finished)
        dialog.show()
        return dialog

    def _guard_policy_dialog_finished(self, _result: int) -> None:
        dialog = self.sender()
        project = getattr(dialog, "project_name", "")
        if dialog in self.guard_policy_dialogs:
            self.guard_policy_dialogs.remove(dialog)
        self.refresh_guard_policy_status(project)

    def set_selected_baseline(self) -> Path | None:
        receipt = self.selected_receipt()
        if receipt is None:
            return None
        try:
            path = self.service.set_baseline(receipt)
        except (ValueError, FileNotFoundError) as exc:
            self.status_label.setText(str(exc))
            return None
        self.refresh_baseline_status(receipt.project_name)
        self.refresh_guard_policy_status(receipt.project_name)
        self.refresh_guard_approval_status(receipt.project_name)
        self._update_action_state()
        self.status_label.setText(
            f"Project baseline set to {receipt.receipt_id or receipt.path.name}."
        )
        return path

    def clear_selected_baseline(self) -> bool:
        receipt = self.selected_receipt()
        project = receipt.project_name if receipt is not None else self.project_name
        if not project or project == "all-projects":
            return False
        cleared = self.service.clear_baseline(project)
        self.refresh_baseline_status(project)
        self.refresh_guard_policy_status(project)
        self.refresh_guard_approval_status(project)
        self._update_action_state()
        self.status_label.setText(
            "Project baseline cleared." if cleared else "No project baseline was set."
        )
        return cleared

    def compare_selected_to_baseline(self) -> GenerationLaunchReceiptDriftDialog | None:
        receipt = self.selected_receipt()
        if receipt is None:
            return None
        baseline = self.service.baseline(receipt.project_name)
        if baseline is None:
            self.status_label.setText(
                "Set a trusted receipt as the project baseline before comparing drift."
            )
            return None
        comparison = self.service.compare(baseline, receipt)
        dialog = GenerationLaunchReceiptDriftDialog(
            self.service,
            comparison,
            self,
            export_dir=self.export_dir / "drift",
        )
        self.drift_dialogs.append(dialog)
        dialog.finished.connect(self._release_drift_dialog)
        dialog.show()
        self.status_label.setText(comparison.summary)
        return dialog

    def _release_drift_dialog(self, _result: int) -> None:
        """Release closed child dialogs before deferred Qt deletion runs."""
        dialog = self.sender()
        if dialog in self.drift_dialogs:
            self.drift_dialogs.remove(dialog)

    def open_json(self) -> None:
        receipt = self.selected_receipt()
        if receipt is not None:
            self._open(receipt.path)

    def open_markdown(self) -> None:
        receipt = self.selected_receipt()
        if receipt is not None and receipt.markdown_path.exists():
            self._open(receipt.markdown_path)

    def open_output(self) -> None:
        receipt = self.selected_receipt()
        if receipt is not None and receipt.output_directory:
            self._open(Path(receipt.output_directory))

    def copy_receipt_path(self) -> None:
        receipt = self.selected_receipt()
        if receipt is not None:
            self._copy(receipt.path)

    def copy_fingerprint(self) -> None:
        receipt = self.selected_receipt()
        if receipt is None or not receipt.launch_fingerprint:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(receipt.launch_fingerprint)
        self.status_label.setText("Launch fingerprint copied.")

    def export_filtered(self) -> tuple[Path, Path] | None:
        if not self.filtered_receipts:
            self.status_label.setText("No filtered launch receipts to export.")
            return None
        json_path, csv_path = self.service.export(
            self.filtered_receipts,
            self.export_dir,
            project_name=self.project_name,
        )
        self.status_label.setText(
            f"Exported {len(self.filtered_receipts):,} receipt(s): {json_path.name} and {csv_path.name}"
        )
        return json_path, csv_path

    def _render_table(self) -> None:
        self.table.setRowCount(len(self.filtered_receipts))
        for row, receipt in enumerate(self.filtered_receipts):
            values = (
                self._display_time(receipt.created_at),
                receipt.project_name,
                receipt.integrity_status.title(),
                receipt.review_status.replace("_", " ").title(),
                receipt.risk_level.title(),
                receipt.provider,
                receipt.model_id or "Default",
                f"{receipt.files:,}",
                f"{receipt.characters:,}",
                f"{receipt.currency} {receipt.estimated_cost:,.4f}",
                f"{len(receipt.acknowledged_codes):,}",
                receipt.receipt_id or receipt.launch_fingerprint[:12] or "Legacy",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column in {2, 4}:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setData(
                        Qt.UserRole,
                        receipt.integrity_status if column == 2 else receipt.risk_level,
                    )
                if column in {7, 8, 9, 10}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _render_summary(self) -> None:
        summary = self.service.summary(self.filtered_receipts)
        issues = summary.mismatch_count + summary.unreadable_count
        self.metric_values["receipts"].setText(f"{summary.receipt_count:,}")
        self.metric_values["verified"].setText(f"{summary.verified_count:,}")
        self.metric_values["legacy"].setText(f"{summary.legacy_count:,}")
        self.metric_values["issues"].setText(f"{issues:,}")
        self.metric_values["risk"].setText(f"{summary.high_risk_count:,}")
        tone = "error" if issues else ("warning" if summary.legacy_count or summary.high_risk_count else "success")
        if not summary.receipt_count:
            tone = "info"
        self.summary_card.update_status(
            f"{summary.receipt_count:,} launch receipt(s)",
            f"{summary.total_files:,} planned files · {summary.total_characters:,} characters · "
            f"{summary.confirmation_required_count:,} launch(es) required acknowledgement.",
            tone=tone,
        )
        self.summary_text.setText(
            "Integrity issues require investigation before relying on the affected receipt. "
            "Legacy receipts remain available for historical context."
        )
        self.status_label.setText(f"Showing {summary.receipt_count:,} launch receipt(s).")

    def _update_action_state(self) -> None:
        receipt = self.selected_receipt()
        has_receipt = receipt is not None
        self.open_json_button.setEnabled(has_receipt and receipt.path.exists() if receipt else False)
        self.open_markdown_button.setEnabled(
            has_receipt and receipt.markdown_path.exists() if receipt else False
        )
        self.open_output_button.setEnabled(
            bool(receipt and receipt.output_directory and Path(receipt.output_directory).exists())
        )
        baseline = self.service.baseline(receipt.project_name) if receipt else None
        self.set_baseline_button.setEnabled(bool(receipt and receipt.integrity_ok))
        self.clear_baseline_button.setEnabled(baseline is not None)
        self.compare_baseline_button.setEnabled(bool(receipt and baseline is not None))
        project = receipt.project_name if receipt is not None else self.project_name
        self.guard_policy_button.setEnabled(bool(project and project != "all-projects"))
        self.guard_approval_button.setEnabled(True)
        self.copy_path_button.setEnabled(has_receipt)
        self.copy_fingerprint_button.setEnabled(bool(receipt and receipt.launch_fingerprint))
        self.export_button.setEnabled(bool(self.filtered_receipts))

    def _open(self, path: Path) -> None:
        if self.open_path_callback is not None:
            self.open_path_callback(Path(path))
        self.status_label.setText(f"Opened: {Path(path).name}")

    def _copy(self, path: Path) -> None:
        if self.copy_path_callback is not None:
            self.copy_path_callback(Path(path))
        else:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(str(path))
        self.status_label.setText(f"Copied: {path}")

    @staticmethod
    def _display_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return value or "Unknown"
