from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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

from app.gui.dialogs.performance_budget_dialog import PerformanceBudgetDialog
from app.models.product_events import BatchSessionRecord
from app.services.generation_history_service import GenerationHistoryService


class GenerationHistoryDialog(QDialog):
    """Searchable session archive with baselines, regression analysis, and export."""

    def __init__(
        self,
        service: GenerationHistoryService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        export_dir: Path,
        open_path: Callable[[Path], None],
        copy_path: Callable[[Path], None],
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.export_dir = Path(export_dir)
        self.open_path_callback = open_path
        self.copy_path_callback = copy_path
        self.all_sessions: list[BatchSessionRecord] = []
        self.filtered_sessions: list[BatchSessionRecord] = []

        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Generation history")
        self.resize(1260, 760)
        root = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.current_project_only = QCheckBox("Current project only")
        self.current_project_only.setChecked(project_id is not None)
        self.current_project_only.setEnabled(project_id is not None)
        self.result_filter = QComboBox()
        self.result_filter.addItem("All results", "")
        for value in ("completed", "failed", "stopped"):
            self.result_filter.addItem(value.title(), value)
        self.provider_filter = QComboBox()
        self.provider_filter.addItem("All providers", "")
        self.regression_filter = QComboBox()
        self.regression_filter.addItem("All performance states", "")
        self.regression_filter.addItem("Critical regressions", "critical")
        self.regression_filter.addItem("Warnings", "warning")
        self.regression_filter.addItem("Healthy", "none")
        self.regression_filter.addItem("Needs baseline", "insufficient_data")
        self.alert_filter = QComboBox()
        self.alert_filter.addItem("All alert states", "")
        self.alert_filter.addItem("Open alerts", "open")
        self.alert_filter.addItem("Acknowledged", "acknowledged")
        self.alert_filter.addItem("Suppressed", "suppressed")
        self.alert_filter.addItem("Silenced", "silenced")
        self.alert_filter.addItem("No alert", "none")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search session, provider, model, voice, scope…")
        self.search.setClearButtonEnabled(True)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        filters.addWidget(self.current_project_only)
        filters.addWidget(self.result_filter)
        filters.addWidget(self.provider_filter)
        filters.addWidget(self.regression_filter)
        filters.addWidget(self.alert_filter)
        filters.addWidget(self.search, 1)
        filters.addWidget(refresh_button)
        root.addLayout(filters)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 16)
        self.table.setHorizontalHeaderLabels(
            [
                "Started",
                "Result",
                "Provider",
                "Scope",
                "Jobs",
                "Completed",
                "Failed",
                "Retries",
                "Health",
                "Regression",
                "Alert",
                "Baseline",
                "Elapsed",
                "Files/min",
                "Chars/min",
                "Report",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.update_details)
        root.addWidget(self.table, 1)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(210)
        self.details.setPlaceholderText("Select one session for details or two sessions to compare.")
        root.addWidget(self.details)

        actions = QHBoxLayout()
        self.compare_button = QPushButton("Compare selected")
        self.reanalyze_button = QPushButton("Recalculate baselines")
        self.acknowledge_button = QPushButton("Acknowledge alerts")
        self.silence_button = QPushButton("Silence 1 hour")
        self.resume_alerts_button = QPushButton("Resume alerts")
        self.budget_button = QPushButton("Performance budgets")
        self.open_report_button = QPushButton("Open report")
        self.open_output_button = QPushButton("Open output")
        self.copy_report_button = QPushButton("Copy report path")
        self.export_button = QPushButton("Export filtered history")
        close_button = QPushButton("Close")
        self.compare_button.clicked.connect(self.compare_selected)
        self.reanalyze_button.clicked.connect(self.reanalyze_all)
        self.acknowledge_button.clicked.connect(self.acknowledge_selected)
        self.silence_button.clicked.connect(self.silence_alerts)
        self.resume_alerts_button.clicked.connect(self.resume_alerts)
        self.budget_button.clicked.connect(self.edit_budget)
        self.open_report_button.clicked.connect(self.open_selected_report)
        self.open_output_button.clicked.connect(self.open_selected_output)
        self.copy_report_button.clicked.connect(self.copy_selected_report)
        self.export_button.clicked.connect(self.export_filtered)
        close_button.clicked.connect(self.close)
        for button in (
            self.compare_button,
            self.reanalyze_button,
            self.acknowledge_button,
            self.silence_button,
            self.resume_alerts_button,
            self.budget_button,
            self.open_report_button,
            self.open_output_button,
            self.copy_report_button,
            self.export_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        root.addLayout(actions)

        self.status_label = QLabel()
        root.addWidget(self.status_label)

        self.current_project_only.toggled.connect(self.refresh)
        self.result_filter.currentIndexChanged.connect(self.apply_filters)
        self.provider_filter.currentIndexChanged.connect(self.apply_filters)
        self.regression_filter.currentIndexChanged.connect(self.apply_filters)
        self.alert_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.refresh()

    def refresh(self) -> None:
        project_id = self.project_id if self.current_project_only.isChecked() else None
        self.all_sessions = self.service.list_sessions(project_id=project_id, limit=500)
        current_provider = str(self.provider_filter.currentData() or "")
        providers = sorted({record.provider for record in self.all_sessions if record.provider})
        self.provider_filter.blockSignals(True)
        self.provider_filter.clear()
        self.provider_filter.addItem("All providers", "")
        for provider in providers:
            self.provider_filter.addItem(provider, provider)
        index = self.provider_filter.findData(current_provider)
        self.provider_filter.setCurrentIndex(index if index >= 0 else 0)
        self.provider_filter.blockSignals(False)
        self.apply_filters()

    def apply_filters(self) -> None:
        result = str(self.result_filter.currentData() or "")
        provider = str(self.provider_filter.currentData() or "")
        regression = str(self.regression_filter.currentData() or "")
        alert_state = str(self.alert_filter.currentData() or "")
        search = self.search.text().strip().casefold()
        self.filtered_sessions = [
            record
            for record in self.all_sessions
            if (not result or record.result == result)
            and (not provider or record.provider == provider)
            and (not regression or record.regression_severity == regression)
            and (not alert_state or record.alert_state == alert_state)
            and (
                not search
                or search
                in " ".join(
                    [
                        record.session_id,
                        record.result,
                        record.provider,
                        record.model,
                        record.voice,
                        record.scope,
                        record.regression_severity,
                        record.alert_state,
                        record.alert_fingerprint or "",
                        " ".join(record.regression_reasons),
                    ]
                ).casefold()
            )
        ]
        self.render_table()
        self.render_summary()
        self.update_details()

    def render_table(self) -> None:
        self.table.setRowCount(len(self.filtered_sessions))
        for row, record in enumerate(self.filtered_sessions):
            health = (
                f"{record.health_score:.0f}"
                if record.health_score > 0 or record.regression_severity != "insufficient_data"
                else "—"
            )
            values = [
                self._short_timestamp(record.started_at),
                record.result.title(),
                record.provider,
                record.scope,
                f"{record.total_jobs:,}",
                f"{record.completed_jobs:,}",
                f"{record.failed_jobs:,}",
                f"{record.retry_events:,}",
                health,
                self._severity_label(record.regression_severity),
                self._alert_label(record.alert_state),
                self._short_session(record.baseline_session_id),
                self._duration(record.elapsed_seconds),
                f"{record.files_per_minute:.2f}",
                f"{record.characters_per_minute:,.0f}",
                Path(record.report_path).name if record.report_path else "—",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, record.session_id)
                if column == 9 and record.regression_reasons:
                    item.setToolTip("\n".join(record.regression_reasons))
                if column == 10 and record.alert_fingerprint:
                    item.setToolTip(record.alert_fingerprint)
                if column == 15 and record.report_path:
                    item.setToolTip(record.report_path)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()

    def render_summary(self) -> None:
        summary = self.service.summary(self.filtered_sessions)
        trend = self.service.trend(self.filtered_sessions)
        self.summary_label.setText(
            " · ".join(
                [
                    f"Sessions {summary.session_count:,}",
                    f"Jobs {summary.total_jobs:,}",
                    f"Completed {summary.completed_jobs:,}",
                    f"Failed {summary.failed_jobs:,}",
                    f"Success {summary.completion_rate:.1f}%",
                    f"Health {summary.average_health_score:.1f}",
                    f"Warnings {summary.warning_regressions:,}",
                    f"Critical {summary.critical_regressions:,}",
                    f"Open alerts {sum(item.alert_state == 'open' for item in self.filtered_sessions):,}",
                    f"Trend {trend.direction.title()} ({trend.health_delta:+.1f})",
                    f"Avg throughput {summary.average_files_per_minute:.2f} files/min",
                ]
            )
        )

    def update_details(self) -> None:
        records = self.selected_records()
        one = len(records) == 1
        two = len(records) == 2
        self.compare_button.setEnabled(two)
        self.open_report_button.setEnabled(one and bool(records[0].report_path))
        self.open_output_button.setEnabled(one and bool(records[0].output_path))
        self.copy_report_button.setEnabled(one and bool(records[0].report_path))
        self.acknowledge_button.setEnabled(
            any(record.alert_state == "open" for record in records)
        )
        if not records:
            self.details.clear()
            return
        if two:
            self.compare_selected()
            return
        record = records[0]
        failure_categories = record.failure_summary.get("categories", {})
        baseline = record.baseline_metrics
        reasons = "; ".join(record.regression_reasons) or "None"
        self.details.setPlainText(
            "\n".join(
                [
                    f"Session: {record.session_id}",
                    f"Started: {record.started_at}",
                    f"Finished: {record.finished_at or '—'}",
                    f"Provider / Model / Voice: {record.provider} / {record.model} / {record.voice}",
                    f"Result: {record.result} · Scope: {record.scope}",
                    f"Jobs: {record.total_jobs} · Completed: {record.completed_jobs} · Failed: {record.failed_jobs} · Skipped: {record.skipped_jobs}",
                    f"Elapsed: {self._duration(record.elapsed_seconds)} · Active: {self._duration(record.active_seconds)} · Paused: {self._duration(record.paused_seconds)}",
                    f"Throughput: {record.files_per_minute:.2f} files/min · {record.characters_per_minute:,.0f} chars/min",
                    f"Retries: {record.retry_events} · Failure categories: {failure_categories or 'None'}",
                    f"Health: {record.health_score:.1f} · Regression: {self._severity_label(record.regression_severity)}",
                    f"Baseline: {record.baseline_session_id or '—'} · Samples: {baseline.get('sample_count', 0)}",
                    f"Regression reasons: {reasons}",
                    f"Alert: {self._alert_label(record.alert_state)} · Fingerprint: {record.alert_fingerprint or '—'}",
                    f"Alert created: {record.alert_created_at or '—'} · Acknowledged: {record.alert_acknowledged_at or '—'}",
                    f"Incident: {record.incident_id or '—'} · Status: {record.incident_status.replace('_', ' ').title() if record.incident_status != 'none' else '—'}",
                    f"Output: {record.output_path or '—'}",
                    f"Report: {record.report_path or '—'}",
                ]
            )
        )

    def compare_selected(self) -> None:
        records = self.selected_records()
        if len(records) != 2:
            self.status_label.setText("Select exactly two sessions to compare.")
            return
        baseline, candidate = sorted(records, key=lambda item: item.started_at)
        comparison = self.service.compare(baseline, candidate)
        self.details.setPlainText(
            "\n".join(
                [
                    f"Baseline: {baseline.started_at} · {baseline.session_id}",
                    f"Candidate: {candidate.started_at} · {candidate.session_id}",
                    f"Completion-rate delta: {comparison.completion_rate_delta:+.1f} percentage points",
                    f"Elapsed-time delta: {comparison.elapsed_seconds_delta:+.1f}s",
                    f"Files/min delta: {comparison.files_per_minute_delta:+.2f}",
                    f"Characters/min delta: {comparison.characters_per_minute_delta:+,.0f}",
                    f"Retry delta: {comparison.retry_events_delta:+d}",
                    f"Failed-job delta: {comparison.failed_jobs_delta:+d}",
                    f"Health-score delta: {comparison.health_score_delta:+.1f}",
                    f"Candidate regression: {self._severity_label(candidate.regression_severity)}",
                ]
            )
        )
        self.status_label.setText("Comparison uses the older session as baseline.")

    def reanalyze_all(self) -> None:
        if not self.all_sessions:
            self.status_label.setText("No sessions are available for baseline analysis.")
            return
        analyses = self.service.reanalyze(self.all_sessions)
        warning_count = sum(item.severity == "warning" for item in analyses)
        critical_count = sum(item.severity == "critical" for item in analyses)
        self.refresh()
        self.status_label.setText(
            f"Recalculated {len(analyses)} sessions · {warning_count} warning · {critical_count} critical"
        )

    def acknowledge_selected(self) -> None:
        # The repository is the authority for whether an alert is still open.
        # Passing every selected session ID also avoids losing the action when
        # the in-memory record is stale after a Qt filter/selection refresh.
        session_ids = self.selected_session_ids()
        count = self.service.acknowledge_alerts(session_ids)
        self.refresh()
        self.status_label.setText(f"Acknowledged {count} performance alert(s).")

    def silence_alerts(self) -> None:
        project_id = self._active_budget_project_id()
        budget = self.service.silence_alerts(project_id, minutes=60)
        self.status_label.setText(f"Alerts silenced until {budget.silence_until}.")

    def resume_alerts(self) -> None:
        project_id = self._active_budget_project_id()
        self.service.resume_alerts(project_id)
        self.status_label.setText("Performance alerts resumed.")

    def edit_budget(self) -> None:
        project_id = self._active_budget_project_id()
        scope_label = self.project_name if project_id is not None else "Global defaults"
        dialog = PerformanceBudgetDialog(
            self.service.performance_budget(project_id),
            self,
            scope_label=scope_label,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.service.save_performance_budget(dialog.budget())
        analyses = self.service.reanalyze(self.all_sessions) if self.all_sessions else []
        self.refresh()
        self.status_label.setText(
            f"Performance budget saved; recalculated {len(analyses)} session(s)."
        )

    def _active_budget_project_id(self) -> int | None:
        if self.project_id is not None and self.current_project_only.isChecked():
            return self.project_id
        return None

    def export_filtered(self) -> tuple[Path, Path] | None:
        if not self.filtered_sessions:
            self.status_label.setText("No sessions match the current filters.")
            return None
        json_path, csv_path = self.service.export(
            self.filtered_sessions,
            self.export_dir,
            project_name=self.project_name if self.current_project_only.isChecked() else "all-projects",
        )
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}")
        return json_path, csv_path

    def selected_session_ids(self) -> list[str]:
        rows = self._selected_rows()
        session_ids: list[str] = []
        for row in rows:
            item = self.table.item(row, 0)
            value = item.data(Qt.UserRole) if item is not None else None
            session_id = str(value or "").strip()
            if not session_id and 0 <= row < len(self.filtered_sessions):
                session_id = self.filtered_sessions[row].session_id
            if session_id and session_id not in session_ids:
                session_ids.append(session_id)
        return session_ids

    def selected_records(self) -> list[BatchSessionRecord]:
        records_by_id = {record.session_id: record for record in self.filtered_sessions}
        return [
            records_by_id[session_id]
            for session_id in self.selected_session_ids()
            if session_id in records_by_id
        ]

    def _selected_rows(self) -> list[int]:
        rows: set[int] = set()
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            rows.update(index.row() for index in selection_model.selectedRows())
            if not rows:
                rows.update(index.row() for index in selection_model.selectedIndexes())
            current_index = selection_model.currentIndex()
            if not rows and current_index.isValid():
                rows.add(current_index.row())

        # QTableWidget.selectRow() can leave selectedRows() empty while the
        # widget is hidden in headless/offscreen Qt tests. currentRow() still
        # identifies the row selected by the caller in that situation.
        current_row = self.table.currentRow()
        if not rows and current_row >= 0:
            rows.add(current_row)

        return sorted(row for row in rows if 0 <= row < self.table.rowCount())

    def open_selected_report(self) -> None:
        records = self.selected_records()
        if len(records) == 1 and records[0].report_path:
            self.open_path_callback(Path(records[0].report_path))

    def open_selected_output(self) -> None:
        records = self.selected_records()
        if len(records) == 1 and records[0].output_path:
            self.open_path_callback(Path(records[0].output_path))

    def copy_selected_report(self) -> None:
        records = self.selected_records()
        if len(records) == 1 and records[0].report_path:
            self.copy_path_callback(Path(records[0].report_path))

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0, int(round(seconds)))
        minutes, remaining = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{remaining:02d}"
        return f"{minutes:d}:{remaining:02d}"

    @staticmethod
    def _short_timestamp(value: str) -> str:
        return value.replace("T", " ")[:19] if value else "—"

    @staticmethod
    def _short_session(value: str | None) -> str:
        if not value:
            return "—"
        return value if len(value) <= 14 else f"{value[:11]}…"

    @staticmethod
    def _alert_label(value: str) -> str:
        labels = {
            "open": "Open",
            "acknowledged": "Acknowledged",
            "suppressed": "Suppressed",
            "silenced": "Silenced",
            "none": "—",
        }
        return labels.get(value, value.replace("_", " ").title())

    @staticmethod
    def _severity_label(value: str) -> str:
        labels = {
            "critical": "Critical",
            "warning": "Warning",
            "none": "Healthy",
            "insufficient_data": "Needs baseline",
        }
        return labels.get(value, value.replace("_", " ").title())
