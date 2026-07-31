from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_reliability import (
    GenerationReliabilityDashboard,
    GenerationSloPolicy,
)
from app.services.generation_reliability_service import GenerationReliabilityService


class GenerationSloPolicyDialog(QDialog):
    def __init__(
        self,
        service: GenerationReliabilityService,
        policy: GenerationSloPolicy,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.policy = policy
        self.saved_policy: GenerationSloPolicy | None = None
        self.setWindowTitle("Reliability SLO Policy")
        self.resize(620, 650)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox("Evaluate and alert on this SLO")
        self.window_days = self._integer(1, 3650)
        self.minimum_sessions = self._integer(1, 10000)
        self.target_success = self._percentage()
        self.max_retry = self._percentage()
        self.max_mtta = self._decimal(1.0, 525600.0, " min")
        self.max_mttr = self._decimal(1.0, 525600.0, " min")
        self.max_recurrence = self._percentage()
        self.min_runbook = self._percentage()
        self.min_actions = self._percentage()
        self.warning_burn = self._decimal(0.1, 100.0, "x")
        self.critical_burn = self._decimal(0.1, 100.0, "x")
        self.cooldown = self._integer(0, 525600, " min")
        form.addRow("Enabled", self.enabled)
        form.addRow("Rolling window", self.window_days)
        form.addRow("Minimum sessions", self.minimum_sessions)
        form.addRow("Job success target", self.target_success)
        form.addRow("Maximum retry rate", self.max_retry)
        form.addRow("Maximum MTTA", self.max_mtta)
        form.addRow("Maximum MTTR", self.max_mttr)
        form.addRow("Maximum incident recurrence", self.max_recurrence)
        form.addRow("Minimum runbook success", self.min_runbook)
        form.addRow("Minimum corrective-action completion", self.min_actions)
        form.addRow("Warning burn rate", self.warning_burn)
        form.addRow("Critical burn rate", self.critical_burn)
        form.addRow("Alert cooldown", self.cooldown)
        root.addLayout(form)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _integer(minimum: int, maximum: int, suffix: str = "") -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setSuffix(suffix)
        return control

    @staticmethod
    def _decimal(minimum: float, maximum: float, suffix: str = "") -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(2)
        control.setSuffix(suffix)
        return control

    @classmethod
    def _percentage(cls) -> QDoubleSpinBox:
        return cls._decimal(0.0, 100.0, "%")

    def _load(self) -> None:
        policy = self.policy
        self.enabled.setChecked(policy.enabled)
        self.window_days.setValue(policy.window_days)
        self.minimum_sessions.setValue(policy.minimum_sessions)
        self.target_success.setValue(policy.target_job_success_rate)
        self.max_retry.setValue(policy.max_retry_rate)
        self.max_mtta.setValue(policy.max_mtta_minutes)
        self.max_mttr.setValue(policy.max_mttr_minutes)
        self.max_recurrence.setValue(policy.max_incident_recurrence_rate)
        self.min_runbook.setValue(policy.min_runbook_success_rate)
        self.min_actions.setValue(policy.min_corrective_action_completion_rate)
        self.warning_burn.setValue(policy.warning_burn_rate)
        self.critical_burn.setValue(policy.critical_burn_rate)
        self.cooldown.setValue(policy.alert_cooldown_minutes)

    def save(self) -> None:
        if self.critical_burn.value() < self.warning_burn.value():
            self.status_label.setText(
                "Critical burn rate must be greater than or equal to warning burn rate."
            )
            return
        self.saved_policy = self.service.save_policy(
            replace(
                self.policy,
                enabled=self.enabled.isChecked(),
                window_days=self.window_days.value(),
                minimum_sessions=self.minimum_sessions.value(),
                target_job_success_rate=self.target_success.value(),
                max_retry_rate=self.max_retry.value(),
                max_mtta_minutes=self.max_mtta.value(),
                max_mttr_minutes=self.max_mttr.value(),
                max_incident_recurrence_rate=self.max_recurrence.value(),
                min_runbook_success_rate=self.min_runbook.value(),
                min_corrective_action_completion_rate=self.min_actions.value(),
                warning_burn_rate=self.warning_burn.value(),
                critical_burn_rate=self.critical_burn.value(),
                alert_cooldown_minutes=self.cooldown.value(),
            )
        )
        self.accept()


class GenerationReliabilityDialog(QDialog):
    """Operational SLO dashboard for generation reliability and error budgets."""

    def __init__(
        self,
        service: GenerationReliabilityService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        export_dir: Path | None = None,
        open_history: Callable[[], None] | None = None,
        open_incidents: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.export_dir = export_dir or Path.cwd() / "reports" / "reliability"
        self.open_history_callback = open_history
        self.open_incidents_callback = open_incidents
        self.dashboard_data: GenerationReliabilityDashboard | None = None
        self.setWindowTitle("Generation Reliability Dashboard")
        self.resize(1240, 780)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Reliability Dashboard & SLO")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        heading.addWidget(title)
        heading.addStretch(1)
        self.project_label = QLabel(self.project_name)
        heading.addWidget(self.project_label)
        root.addLayout(heading)

        summary = QHBoxLayout()
        self.state_label = self._metric_label("State", "—")
        self.success_label = self._metric_label("Job success", "—")
        self.budget_label = self._metric_label("Error budget", "—")
        self.burn_label = self._metric_label("Burn rate", "—")
        self.mttr_label = self._metric_label("MTTR", "—")
        self.trend_label = self._metric_label("Trend", "—")
        for widget in (
            self.state_label,
            self.success_label,
            self.budget_label,
            self.burn_label,
            self.mttr_label,
            self.trend_label,
        ):
            summary.addWidget(widget, 1)
        root.addLayout(summary)

        self.error_budget = QProgressBar()
        self.error_budget.setRange(0, 100)
        self.error_budget.setFormat("Error budget remaining: %p%")
        root.addWidget(self.error_budget)

        tabs = QTabWidget()
        metrics_page = QWidget()
        metrics_layout = QVBoxLayout(metrics_page)
        self.metrics_table = QTableWidget(0, 4)
        self.metrics_table.setHorizontalHeaderLabels(
            ["Reliability objective", "Current", "Target", "Status"]
        )
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        metrics_layout.addWidget(self.metrics_table)
        tabs.addTab(metrics_page, "SLO objectives")

        providers_page = QWidget()
        providers_layout = QVBoxLayout(providers_page)
        self.provider_table = QTableWidget(0, 8)
        self.provider_table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Sessions",
                "Jobs",
                "Success",
                "Failure",
                "Retry",
                "Files/min",
                "Health",
            ]
        )
        self.provider_table.verticalHeader().setVisible(False)
        self.provider_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.provider_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.provider_table.horizontalHeader().setStretchLastSection(True)
        providers_layout.addWidget(self.provider_table)
        tabs.addTab(providers_page, "Provider reliability")

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        self.history_table = QTableWidget(0, 8)
        self.history_table.setHorizontalHeaderLabels(
            [
                "Created",
                "State",
                "Trend",
                "Sessions",
                "Success",
                "Budget",
                "Burn",
                "MTTR",
            ]
        )
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.history_table.horizontalHeader().setStretchLastSection(True)
        history_layout.addWidget(self.history_table)
        tabs.addTab(history_page, "Snapshot history")
        root.addWidget(tabs, 1)

        self.reasons_label = QLabel()
        self.reasons_label.setWordWrap(True)
        root.addWidget(self.reasons_label)
        self.status_label = QLabel()
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        for text, handler in (
            ("Edit SLO policy", self.edit_policy),
            ("Recalculate snapshot", self.recalculate),
            ("Export", self.export_dashboard),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            actions.addWidget(button)
        if self.open_history_callback is not None:
            history = QPushButton("Open Generation History")
            history.clicked.connect(self.open_history_callback)
            actions.addWidget(history)
        if self.open_incidents_callback is not None:
            incidents = QPushButton("Open Incident Center")
            incidents.clicked.connect(self.open_incidents_callback)
            actions.addWidget(incidents)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

    @staticmethod
    def _metric_label(title: str, value: str) -> QLabel:
        label = QLabel(f"{title}\n{value}")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            "QLabel{border:1px solid palette(mid);border-radius:6px;padding:10px;}"
        )
        label.setProperty("metric_title", title)
        return label

    @staticmethod
    def _set_metric(label: QLabel, value: str) -> None:
        label.setText(f"{label.property('metric_title')}\n{value}")

    def refresh(self) -> None:
        self.dashboard_data = self.service.dashboard(project_id=self.project_id)
        dashboard = self.dashboard_data
        snapshot = dashboard.snapshot
        self._set_metric(self.state_label, self._label(snapshot.state))
        self._set_metric(self.success_label, f"{snapshot.job_success_rate:.2f}%")
        self._set_metric(
            self.budget_label,
            f"{snapshot.error_budget_remaining_percent:.1f}%",
        )
        self._set_metric(self.burn_label, f"{snapshot.burn_rate:.2f}x")
        self._set_metric(self.mttr_label, f"{snapshot.mttr_minutes:.1f} min")
        self._set_metric(self.trend_label, self._label(snapshot.trend))
        self.error_budget.setValue(round(snapshot.error_budget_remaining_percent))
        self.reasons_label.setText(
            " · ".join(snapshot.reasons) if snapshot.reasons else "All configured SLO targets are met."
        )
        self._populate_metrics(dashboard)
        self._populate_providers(dashboard)
        self._populate_history(dashboard)
        self.status_label.setText(
            f"Window: {dashboard.policy.window_days} day(s) · "
            f"{snapshot.session_count} session(s) · {snapshot.total_jobs} job(s)"
        )

    def _populate_metrics(self, dashboard: GenerationReliabilityDashboard) -> None:
        snapshot = dashboard.snapshot
        policy = dashboard.policy
        recurrence = (
            snapshot.recurring_incident_count / snapshot.incident_count * 100.0
            if snapshot.incident_count
            else 0.0
        )
        rows = (
            (
                "Job success rate",
                f"{snapshot.job_success_rate:.2f}%",
                f"≥ {policy.target_job_success_rate:.2f}%",
                dashboard.target_status.get("job_success_rate", "—"),
            ),
            (
                "Retry rate",
                f"{snapshot.retry_rate:.2f}%",
                f"≤ {policy.max_retry_rate:.2f}%",
                dashboard.target_status.get("retry_rate", "—"),
            ),
            (
                "Mean time to acknowledge",
                f"{snapshot.mtta_minutes:.1f} min",
                f"≤ {policy.max_mtta_minutes:.1f} min",
                dashboard.target_status.get("mtta", "—"),
            ),
            (
                "Mean time to resolve",
                f"{snapshot.mttr_minutes:.1f} min",
                f"≤ {policy.max_mttr_minutes:.1f} min",
                dashboard.target_status.get("mttr", "—"),
            ),
            (
                "Incident recurrence",
                f"{recurrence:.2f}%",
                f"≤ {policy.max_incident_recurrence_rate:.2f}%",
                dashboard.target_status.get("incident_recurrence", "—"),
            ),
            (
                "Runbook success",
                f"{snapshot.runbook_success_rate:.2f}%",
                f"≥ {policy.min_runbook_success_rate:.2f}%",
                dashboard.target_status.get("runbook_success", "—"),
            ),
            (
                "Corrective-action completion",
                f"{snapshot.corrective_action_completion_rate:.2f}%",
                f"≥ {policy.min_corrective_action_completion_rate:.2f}%",
                dashboard.target_status.get("corrective_actions", "—"),
            ),
            (
                "Error-budget burn rate",
                f"{snapshot.burn_rate:.2f}x",
                f"Warning {policy.warning_burn_rate:.2f}x · Critical {policy.critical_burn_rate:.2f}x",
                snapshot.state,
            ),
        )
        self.metrics_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.metrics_table.setItem(row, column, QTableWidgetItem(self._label(value)))

    def _populate_providers(self, dashboard: GenerationReliabilityDashboard) -> None:
        providers = dashboard.snapshot.provider_metrics
        self.provider_table.setRowCount(len(providers))
        for row, item in enumerate(providers):
            values = (
                item.provider,
                str(item.session_count),
                str(item.total_jobs),
                f"{item.job_success_rate:.2f}%",
                f"{item.failure_rate:.2f}%",
                f"{item.retry_rate:.2f}%",
                f"{item.average_files_per_minute:.2f}",
                f"{item.average_health_score:.1f}",
            )
            for column, value in enumerate(values):
                self.provider_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_history(self, dashboard: GenerationReliabilityDashboard) -> None:
        history = dashboard.history
        self.history_table.setRowCount(len(history))
        for row, item in enumerate(history):
            values = (
                self._short_timestamp(item.created_at),
                self._label(item.state),
                self._label(item.trend),
                str(item.session_count),
                f"{item.job_success_rate:.2f}%",
                f"{item.error_budget_remaining_percent:.1f}%",
                f"{item.burn_rate:.2f}x",
                f"{item.mttr_minutes:.1f} min",
            )
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))

    def edit_policy(self) -> None:
        policy = self.service.get_policy(self.project_id)
        dialog = GenerationSloPolicyDialog(self.service, policy, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            self.status_label.setText("Reliability SLO policy saved.")

    def recalculate(self) -> None:
        snapshot = self.service.recalculate(project_id=self.project_id)
        self.refresh()
        self.status_label.setText(
            f"Snapshot {snapshot.snapshot_id[:8]} saved with state {self._label(snapshot.state)}."
        )

    def export_dashboard(self) -> tuple[Path, Path] | None:
        if self.dashboard_data is None:
            return None
        json_path, csv_path = self.service.export(
            self.dashboard_data,
            self.export_dir,
            project_name=self.project_name,
        )
        self.status_label.setText(
            f"Exported {json_path.name} and {csv_path.name}."
        )
        return json_path, csv_path

    @staticmethod
    def _label(value: object) -> str:
        text = str(value or "—")
        return text.replace("_", " ").title()

    @staticmethod
    def _short_timestamp(value: str) -> str:
        return value.replace("T", " ")[:19] if value else "—"
