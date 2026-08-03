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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_estimate_actual import GenerationEstimateActualRun
from app.services.generation_estimate_actual_service import GenerationEstimateActualService


class GenerationEstimateActualDialog(QDialog):
    """Operational analytics for estimate accuracy and provider calibration."""

    def __init__(
        self,
        service: GenerationEstimateActualService,
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
        self.export_dir = Path(export_dir or service.reports_dir / "estimate-actual")
        self.open_path_callback = open_path
        self.copy_path_callback = copy_path
        self.all_records: list[GenerationEstimateActualRun] = []
        self.filtered_records: list[GenerationEstimateActualRun] = []
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationEstimateActualDialog")
        self.setWindowTitle("Estimate vs actual analytics")
        self.resize(1320, 850)
        self.setMinimumSize(820, 580)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Estimate vs actual analytics",
            "Measure launch estimate accuracy, identify overruns and review advisory calibration by provider, model and voice.",
            icon_name="history",
            parent=self,
        )
        root.addWidget(self.workspace)

        filters_section = DialogSection(
            "Analysis scope",
            "Filter completed execution evidence without exposing source text or provider credentials.",
        )
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        self.current_project_only = QCheckBox("Current project only")
        has_project = self.project_name not in {"", "all-projects"}
        self.current_project_only.setEnabled(has_project)
        self.current_project_only.setChecked(has_project)
        self.provider_filter = QComboBox()
        self.provider_filter.addItem("All providers", "")
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
        self.search.setObjectName("estimateActualSearch")
        self.search.setPlaceholderText("Search run, project, provider, model, voice or receipt…")
        self.search.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(action_icon("general.refresh"))
        filters.addWidget(self.current_project_only, 0, 0)
        filters.addWidget(self.provider_filter, 0, 1)
        filters.addWidget(self.status_filter, 0, 2)
        filters.addWidget(self.search, 1, 0, 1, 2)
        filters.addWidget(self.refresh_button, 1, 2)
        filters.setColumnStretch(1, 1)
        filters_section.add_layout(filters)
        self.workspace.add_body_widget(filters_section)

        self.summary_card = DialogStatusCard(
            "No execution evidence loaded",
            "Accuracy, overrun and calibration metrics update after filters are applied.",
            tone="info",
        )
        self.summary_card.setObjectName("estimateActualSummaryCard")
        self.workspace.add_body_widget(self.summary_card)

        tabs_section = DialogSection(
            "Estimate evidence",
            "Run-level variance and provider-level calibration are shown separately to keep the workspace readable.",
        )
        self.tabs = QTabWidget()
        self.tabs.setObjectName("estimateActualTabs")
        self.run_table = QTableWidget(0, 13)
        self.run_table.setObjectName("estimateActualRunTable")
        self.run_table.setHorizontalHeaderLabels(
            [
                "Finished",
                "Project",
                "Provider / model",
                "Status",
                "Files E/A",
                "Characters E/A",
                "Requests E/A",
                "Duration E/A",
                "Cost E/A",
                "Duration accuracy",
                "Cost accuracy",
                "Accuracy score",
                "Confidence",
            ]
        )
        self._configure_table(self.run_table)
        self.provider_table = QTableWidget(0, 12)
        self.provider_table.setObjectName("estimateActualProviderTable")
        self.provider_table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Model",
                "Voice",
                "Runs",
                "Success",
                "Duration accuracy",
                "Cost accuracy",
                "Accuracy score",
                "ETA multiplier",
                "Cost multiplier",
                "Chars/min",
                "Confidence",
            ]
        )
        self._configure_table(self.provider_table)
        self.tabs.addTab(self.run_table, "Runs")
        self.tabs.addTab(self.provider_table, "Provider calibration")
        tabs_section.add_widget(self.tabs, 1)
        self.workspace.add_body_widget(tabs_section, 1)

        details_section = DialogSection(
            "Selected analysis",
            "Variance reasons and calibration guidance are advisory; no pricing or planning settings are changed automatically.",
        )
        self.details = QPlainTextEdit()
        self.details.setObjectName("estimateActualDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(125)
        self.details.setMaximumHeight(180)
        details_section.add_widget(self.details)
        self.workspace.add_body_widget(details_section)

        actions_section = DialogSection(
            "Evidence actions",
            "Open linked receipts and sessions, copy the Run ID or export a secret-free analytics package.",
        )
        actions = QGridLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_execution_receipt_button = QPushButton("Open execution receipt")
        self.open_session_button = QPushButton("Open execution session")
        self.open_launch_button = QPushButton("Open launch receipt")
        self.copy_run_id_button = QPushButton("Copy run ID")
        self.export_button = QPushButton("Export analytics and calibration")
        buttons = (
            (self.open_execution_receipt_button, "report"),
            (self.open_session_button, "history"),
            (self.open_launch_button, "report"),
            (self.copy_run_id_button, "general.copy"),
            (self.export_button, "save"),
        )
        for index, (button, icon_name) in enumerate(buttons):
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
        close_button = QPushButton("Close")
        self.workspace.add_footer_widget(self.status_label, 1)
        self.workspace.add_footer_widget(close_button)

        self.refresh_button.clicked.connect(self.refresh)
        self.current_project_only.toggled.connect(self.apply_filters)
        self.provider_filter.currentIndexChanged.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.run_table.itemSelectionChanged.connect(self.update_details)
        self.provider_table.itemSelectionChanged.connect(self.update_provider_details)
        self.open_execution_receipt_button.clicked.connect(
            lambda: self._open_selected("execution_receipt_path")
        )
        self.open_session_button.clicked.connect(
            lambda: self._open_selected("execution_session_path")
        )
        self.open_launch_button.clicked.connect(lambda: self._open_selected("launch_receipt_path"))
        self.copy_run_id_button.clicked.connect(self.copy_run_id)
        self.export_button.clicked.connect(self.export_filtered)
        close_button.clicked.connect(self.close)
        self._update_action_state()

    @staticmethod
    def _configure_table(table: QTableWidget) -> None:
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setMinimumHeight(270)
        table.horizontalHeader().setStretchLastSection(True)

    def refresh(self) -> None:
        self.all_records = self.service.list_runs(limit=1000)
        providers = sorted({item.provider for item in self.all_records if item.provider}, key=str.casefold)
        current = str(self.provider_filter.currentData() or "")
        self.provider_filter.blockSignals(True)
        self.provider_filter.clear()
        self.provider_filter.addItem("All providers", "")
        for provider in providers:
            self.provider_filter.addItem(provider, provider)
        index = self.provider_filter.findData(current)
        self.provider_filter.setCurrentIndex(index if index >= 0 else 0)
        self.provider_filter.blockSignals(False)
        self.apply_filters()

    def apply_filters(self) -> None:
        project = self.project_name if self.current_project_only.isChecked() else None
        provider = str(self.provider_filter.currentData() or "")
        status = str(self.status_filter.currentData() or "")
        search = self.search.text().strip().casefold()
        records = self.all_records
        if project:
            records = [item for item in records if item.project_name == project]
        if provider:
            records = [item for item in records if item.provider == provider]
        if status:
            records = [item for item in records if item.status == status]
        if search:
            records = [
                item
                for item in records
                if search
                in " ".join(
                    (
                        item.run_id,
                        item.project_name,
                        item.provider,
                        item.model_id,
                        item.voice_id,
                        item.execution_receipt_id,
                    )
                ).casefold()
            ]
        self.filtered_records = list(records)
        self._populate_runs()
        self._populate_providers()
        self._update_summary()
        self._update_action_state()

    def _populate_runs(self) -> None:
        self.run_table.setRowCount(len(self.filtered_records))
        for row, record in enumerate(self.filtered_records):
            values = (
                self._short_timestamp(record.finished_at),
                record.project_name,
                self._provider_label(record.provider, record.model_id),
                record.status.title(),
                f"{record.estimated_files:,} / {record.actual_files:,}",
                f"{record.estimated_characters:,} / {record.actual_characters:,}",
                f"{record.estimated_requests:,} / {record.actual_requests:,}",
                f"{self._duration(record.estimated_duration_seconds)} / {self._duration(record.actual_duration_seconds)}",
                self._cost_pair(record),
                f"{record.duration_accuracy_percent:.1f}%" if record.estimated_duration_seconds > 0 else "Unavailable",
                f"{record.cost_accuracy_percent:.1f}%" if record.estimated_cost > 0 else "Unavailable",
                f"{record.estimate_accuracy_score:.1f}%",
                record.confidence.title(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, row)
                self.run_table.setItem(row, column, item)
        if self.filtered_records:
            self.run_table.selectRow(0)
        else:
            self.details.setPlainText("No runs match the current filters.")

    def _populate_providers(self) -> None:
        summaries = self.service.provider_summaries(self.filtered_records)
        self.provider_table.setRowCount(len(summaries))
        for row, item in enumerate(summaries):
            values = (
                item.provider,
                item.model_id or "—",
                item.voice_id or "—",
                item.run_count,
                f"{item.success_rate_percent:.1f}%",
                f"{item.average_duration_accuracy_percent:.1f}%",
                f"{item.average_cost_accuracy_percent:.1f}%",
                f"{item.estimate_accuracy_score:.1f}%",
                f"{item.duration_multiplier:.3f}×",
                f"{item.cost_multiplier:.3f}×",
                f"{item.characters_per_minute:,.0f}",
                item.confidence.title(),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if column == 0:
                    table_item.setData(Qt.UserRole, item)
                self.provider_table.setItem(row, column, table_item)

    def _update_summary(self) -> None:
        summary = self.service.summary(self.filtered_records)
        currency = self.filtered_records[0].currency if self.filtered_records else "USD"
        tone = "warning" if summary.high_variance_count else "success" if summary.total_runs else "info"
        self.summary_card.update_status(
            f"{summary.total_runs:,} run(s) · {summary.average_accuracy_score:.1f}% estimate accuracy · {summary.average_duration_accuracy_percent:.1f}% ETA accuracy",
            (
                f"Files {summary.estimated_files:,} estimated / {summary.actual_files:,} actual · "
                f"Duration {self._duration(summary.estimated_duration_seconds)} estimated / {self._duration(summary.actual_duration_seconds)} actual · "
                f"Cost {currency} {summary.estimated_cost:,.4f} estimated / {currency} {summary.actual_cost:,.4f} derived · "
                f"{summary.duration_overrun_count} duration overrun(s), {summary.cost_overrun_count} cost overrun(s), "
                f"{summary.total_retry_events} retry event(s)."
            ),
            tone=tone,
        )
        self.status_label.setText(f"{summary.total_runs:,} run(s) in current analysis")

    def update_details(self) -> None:
        record = self.selected_record()
        if record is None:
            self.details.setPlainText("Select a run to inspect variance details.")
            self._update_action_state()
            return
        lines = [
            f"Run ID: {record.run_id}",
            f"Project: {record.project_name}",
            f"Provider / model / voice: {record.provider} / {record.model_id or '—'} / {record.voice_id or '—'}",
            f"Outcome: {record.status.title()} · Estimate accuracy score: {record.estimate_accuracy_score:.1f}% · Success rate: {record.success_rate_percent:.1f}% · Confidence: {record.confidence.title()}",
            f"Files variance: {record.file_variance:+,} · Accuracy: {record.file_accuracy_percent:.1f}%",
            f"Characters variance: {record.character_variance:+,} · Accuracy: {record.character_accuracy_percent:.1f}% · Retry characters: {record.retry_characters:,}",
            f"Requests variance: {record.request_variance:+,} · Accuracy: {record.request_accuracy_percent:.1f}% · Retry events: {record.retry_events:,}",
            f"Duration variance: {self._signed_duration(record.duration_variance_seconds)} · Multiplier: {record.duration_multiplier:.3f}×",
            f"Cost variance: {record.currency} {record.cost_variance:+,.4f} · Multiplier: {record.cost_multiplier:.3f}× · Source: {record.cost_source}",
            f"Integrity: {record.integrity_status.title()}",
        ]
        if record.attention_reasons:
            lines.extend(("", "Attention:"))
            lines.extend(f"- {reason}" for reason in record.attention_reasons)
        else:
            lines.extend(("", "No material variance or integrity issue was detected."))
        self.details.setPlainText("\n".join(lines))
        self._update_action_state()

    def update_provider_details(self) -> None:
        row = self.provider_table.currentRow()
        item = self.provider_table.item(row, 0) if row >= 0 else None
        summary = item.data(Qt.UserRole) if item is not None else None
        if summary is None:
            return
        lines = [
            f"Provider: {summary.provider}",
            f"Model / voice: {summary.model_id or '—'} / {summary.voice_id or '—'}",
            f"Runs: {summary.run_count} · Completed: {summary.completed_run_count} · Confidence: {summary.confidence.title()}",
            f"Estimate accuracy score: {summary.estimate_accuracy_score:.1f}% · Success rate: {summary.success_rate_percent:.1f}% · Retry events: {summary.total_retry_events}",
            f"ETA multiplier: {summary.duration_multiplier:.3f}× · Cost multiplier: {summary.cost_multiplier:.3f}×",
            f"Throughput: {summary.characters_per_minute:,.0f} characters/minute",
            "",
            "Advisory recommendations:",
        ]
        lines.extend(f"- {text}" for text in summary.recommendations)
        self.details.setPlainText("\n".join(lines))

    def selected_record(self) -> GenerationEstimateActualRun | None:
        row = self.run_table.currentRow()
        if row < 0 or row >= len(self.filtered_records):
            return None
        return self.filtered_records[row]

    def _open_selected(self, attribute: str) -> None:
        record = self.selected_record()
        value = str(getattr(record, attribute, "") or "") if record is not None else ""
        path = Path(value) if value else None
        if path is None or not path.exists():
            self.status_label.setText("The selected linked artifact is unavailable.")
            return
        if self.open_path_callback is not None:
            self.open_path_callback(path)
        self.status_label.setText(f"Opened {path.name}")

    def copy_run_id(self) -> None:
        record = self.selected_record()
        if record is None or not record.run_id:
            return
        if self.copy_path_callback is not None:
            self.copy_path_callback(Path(record.run_id))
        else:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(record.run_id)
        self.status_label.setText("Run ID copied.")

    def export_filtered(self) -> None:
        if not self.filtered_records:
            self.status_label.setText("No filtered runs are available to export.")
            return
        project = self.project_name if self.current_project_only.isChecked() else "all-projects"
        json_path, csv_path, calibration_path = self.service.export(
            self.filtered_records,
            self.export_dir,
            project_name=project,
        )
        self.status_label.setText(
            f"Exported {json_path.name}, {csv_path.name} and {calibration_path.name}"
        )

    def _update_action_state(self) -> None:
        record = self.selected_record()
        self.open_execution_receipt_button.setEnabled(
            record is not None and Path(record.execution_receipt_path).is_file()
        )
        self.open_session_button.setEnabled(
            record is not None and Path(record.execution_session_path).is_file()
        )
        self.open_launch_button.setEnabled(
            record is not None and Path(record.launch_receipt_path).is_file()
        )
        self.copy_run_id_button.setEnabled(record is not None and bool(record.run_id))
        self.export_button.setEnabled(bool(self.filtered_records))

    @staticmethod
    def _provider_label(provider: str, model: str) -> str:
        return f"{provider} / {model}" if model else provider

    @staticmethod
    def _duration(seconds: float) -> str:
        value = max(0, int(round(seconds or 0.0)))
        hours, remainder = divmod(value, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    @classmethod
    def _signed_duration(cls, seconds: float) -> str:
        sign = "+" if seconds >= 0 else "−"
        return f"{sign}{cls._duration(abs(seconds))}"

    @staticmethod
    def _cost_pair(record: GenerationEstimateActualRun) -> str:
        if record.estimated_cost <= 0:
            return "Unavailable"
        return f"{record.currency} {record.estimated_cost:,.4f} / {record.actual_cost:,.4f}"

    @staticmethod
    def _short_timestamp(value: str) -> str:
        return str(value or "").replace("T", " ")[:19]
