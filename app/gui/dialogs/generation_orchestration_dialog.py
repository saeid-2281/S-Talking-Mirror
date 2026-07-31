from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.domain import AppSettings
from app.models.generation_orchestration import RoutingMode, SchedulingMode
from app.services.generation_orchestration_service import GenerationOrchestrationService


class GenerationOrchestrationDialog(QDialog):
    """Provider routing policy, health, circuit state and failover audit center."""

    def __init__(
        self,
        service: GenerationOrchestrationService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        settings_provider: Callable[[], AppSettings] | None = None,
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.settings_provider = settings_provider
        self.export_dir = export_dir or Path.cwd() / "reports" / "orchestration"
        self.setWindowTitle("Generation Orchestration & Adaptive Routing")
        self.resize(1240, 800)
        self._circuits = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Queue Orchestration, Adaptive Routing & Provider Failover")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(QLabel(self.project_name))
        root.addLayout(heading)

        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        root.addWidget(self.plan_label)

        tabs = QTabWidget()
        policy_page = QWidget()
        policy_layout = QVBoxLayout(policy_page)
        form = QFormLayout()
        self.enabled = QCheckBox("Enable orchestration telemetry")
        self.auto_failover = QCheckBox("Allow automatic account failover")
        self.failure_threshold = QSpinBox()
        self.failure_threshold.setRange(1, 100)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 86400)
        self.cooldown.setSuffix(" s")
        self.max_switches = QSpinBox()
        self.max_switches.setRange(0, 20)
        self.sticky = QCheckBox("Keep the successful backup for remaining jobs")
        self.notify = QCheckBox("Notify when an account circuit opens")
        form.addRow("Enabled", self.enabled)
        form.addRow("Automatic failover", self.auto_failover)
        form.addRow("Failures before circuit opens", self.failure_threshold)
        form.addRow("Circuit cooldown", self.cooldown)
        form.addRow("Maximum switches per run", self.max_switches)
        form.addRow("Sticky successful account", self.sticky)
        form.addRow("Circuit notification", self.notify)
        policy_layout.addLayout(form)
        save = QPushButton("Save failover policy")
        save.clicked.connect(self.save_policy)
        policy_layout.addWidget(save)
        policy_layout.addStretch(1)
        tabs.addTab(policy_page, "Failover policy")

        routing_page = QWidget()
        routing_layout = QVBoxLayout(routing_page)
        routing_form = QFormLayout()
        self.routing_enabled = QCheckBox("Distribute queued jobs across healthy accounts")
        self.routing_mode = QComboBox()
        self.routing_mode.addItem("Legacy priority", RoutingMode.PRIORITY.value)
        self.routing_mode.addItem("Configured weights", RoutingMode.WEIGHTED.value)
        self.routing_mode.addItem("Adaptive health + capacity", RoutingMode.ADAPTIVE.value)
        self.health_weight = self._weight_spin()
        self.capacity_weight = self._weight_spin()
        self.latency_weight = self._weight_spin()
        self.priority_weight = self._weight_spin()
        self.quota_reserve = QSpinBox()
        self.quota_reserve.setRange(0, 2_000_000_000)
        self.quota_reserve.setSuffix(" chars")
        self.max_share = QSpinBox()
        self.max_share.setRange(1, 100)
        self.max_share.setSuffix(" %")
        self.sample_window = QSpinBox()
        self.sample_window.setRange(5, 1000)
        routing_form.addRow("Adaptive routing", self.routing_enabled)
        routing_form.addRow("Routing mode", self.routing_mode)
        routing_form.addRow("Health weight", self.health_weight)
        routing_form.addRow("Capacity weight", self.capacity_weight)
        routing_form.addRow("Latency weight", self.latency_weight)
        routing_form.addRow("Priority weight", self.priority_weight)
        routing_form.addRow("Minimum quota reserve", self.quota_reserve)
        routing_form.addRow("Maximum share per account", self.max_share)
        routing_form.addRow("Telemetry sample window", self.sample_window)
        routing_layout.addLayout(routing_form)
        save_routing = QPushButton("Save adaptive routing policy")
        save_routing.clicked.connect(self.save_routing_policy)
        routing_layout.addWidget(save_routing)
        routing_layout.addStretch(1)
        tabs.addTab(routing_page, "Adaptive routing")

        scheduling_page = QWidget()
        scheduling_layout = QVBoxLayout(scheduling_page)
        scheduling_form = QFormLayout()
        self.scheduling_enabled = QCheckBox(
            "Run independent generation requests concurrently"
        )
        self.scheduling_mode = QComboBox()
        self.scheduling_mode.addItem("Static concurrency", SchedulingMode.STATIC.value)
        self.scheduling_mode.addItem(
            "Adaptive backpressure", SchedulingMode.ADAPTIVE.value
        )
        self.minimum_concurrency = QSpinBox()
        self.minimum_concurrency.setRange(1, 32)
        self.initial_concurrency = QSpinBox()
        self.initial_concurrency.setRange(1, 32)
        self.maximum_concurrency = QSpinBox()
        self.maximum_concurrency.setRange(1, 32)
        self.per_profile_concurrency = QSpinBox()
        self.per_profile_concurrency.setRange(1, 32)
        self.success_window = QSpinBox()
        self.success_window.setRange(1, 1000)
        self.error_window = QSpinBox()
        self.error_window.setRange(1, 1000)
        self.increase_step = QSpinBox()
        self.increase_step.setRange(1, 16)
        self.decrease_factor = QDoubleSpinBox()
        self.decrease_factor.setRange(0.1, 1.0)
        self.decrease_factor.setDecimals(2)
        self.decrease_factor.setSingleStep(0.1)
        self.rate_limit_cooldown = QSpinBox()
        self.rate_limit_cooldown.setRange(0, 86400)
        self.rate_limit_cooldown.setSuffix(" s")
        scheduling_form.addRow("Concurrent scheduler", self.scheduling_enabled)
        scheduling_form.addRow("Scheduling mode", self.scheduling_mode)
        scheduling_form.addRow("Minimum concurrency", self.minimum_concurrency)
        scheduling_form.addRow("Initial concurrency", self.initial_concurrency)
        scheduling_form.addRow("Maximum concurrency", self.maximum_concurrency)
        scheduling_form.addRow("Per-account concurrency", self.per_profile_concurrency)
        scheduling_form.addRow("Success window", self.success_window)
        scheduling_form.addRow("Error window", self.error_window)
        scheduling_form.addRow("Increase step", self.increase_step)
        scheduling_form.addRow("Decrease factor", self.decrease_factor)
        scheduling_form.addRow("Rate-limit cooldown", self.rate_limit_cooldown)
        scheduling_layout.addLayout(scheduling_form)
        save_scheduling = QPushButton("Save scheduling policy")
        save_scheduling.clicked.connect(self.save_scheduling_policy)
        scheduling_layout.addWidget(save_scheduling)
        scheduling_layout.addStretch(1)
        tabs.addTab(scheduling_page, "Concurrency & backpressure")

        metrics_page = QWidget()
        metrics_layout = QVBoxLayout(metrics_page)
        self.metrics_table = QTableWidget(0, 10)
        self.metrics_table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Account",
                "Health",
                "Attempts",
                "Success",
                "Failure",
                "Success rate",
                "EWMA latency",
                "Characters",
                "Last selected",
            ]
        )
        self.metrics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.metrics_table.horizontalHeader().setStretchLastSection(True)
        metrics_layout.addWidget(self.metrics_table)
        tabs.addTab(metrics_page, "Routing health")

        circuits_page = QWidget()
        circuits_layout = QVBoxLayout(circuits_page)
        self.circuit_table = QTableWidget(0, 8)
        self.circuit_table.setHorizontalHeaderLabels(
            ["Provider", "Account", "State", "Failures", "Retry after", "Last category", "Last code", "Updated"]
        )
        self.circuit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.circuit_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.circuit_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.circuit_table.verticalHeader().setVisible(False)
        self.circuit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.circuit_table.horizontalHeader().setStretchLastSection(True)
        circuits_layout.addWidget(self.circuit_table)
        reset = QPushButton("Reset selected circuit")
        reset.clicked.connect(self.reset_selected_circuit)
        circuits_layout.addWidget(reset)
        tabs.addTab(circuits_page, "Circuit breaker")

        decisions_page = QWidget()
        decisions_layout = QVBoxLayout(decisions_page)
        self.decision_table = QTableWidget(0, 8)
        self.decision_table.setHorizontalHeaderLabels(
            ["Created", "File", "Account", "Mode", "Score", "Weight", "Characters", "Reason"]
        )
        self.decision_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.decision_table.verticalHeader().setVisible(False)
        self.decision_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.decision_table.horizontalHeader().setStretchLastSection(True)
        decisions_layout.addWidget(self.decision_table)
        tabs.addTab(decisions_page, "Routing decisions")

        scheduler_page = QWidget()
        scheduler_layout = QVBoxLayout(scheduler_page)
        self.throttle_table = QTableWidget(0, 8)
        self.throttle_table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Account",
                "Concurrency",
                "Rate limits",
                "Cooldown until",
                "Last rate limit",
                "Recovered",
                "Updated",
            ]
        )
        self.throttle_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.throttle_table.verticalHeader().setVisible(False)
        self.throttle_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.throttle_table.horizontalHeader().setStretchLastSection(True)
        scheduler_layout.addWidget(self.throttle_table)
        self.scheduler_event_table = QTableWidget(0, 8)
        self.scheduler_event_table.setHorizontalHeaderLabels(
            [
                "Created",
                "Account",
                "Event",
                "From",
                "To",
                "Pending",
                "Active",
                "Reason",
            ]
        )
        self.scheduler_event_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scheduler_event_table.verticalHeader().setVisible(False)
        self.scheduler_event_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.scheduler_event_table.horizontalHeader().setStretchLastSection(True)
        scheduler_layout.addWidget(self.scheduler_event_table)
        tabs.addTab(scheduler_page, "Scheduler telemetry")

        events_page = QWidget()
        events_layout = QVBoxLayout(events_page)
        self.event_table = QTableWidget(0, 9)
        self.event_table.setHorizontalHeaderLabels(
            ["Created", "File", "Provider", "From", "To", "Category", "Code", "Outcome", "Switch"]
        )
        self.event_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.event_table.verticalHeader().setVisible(False)
        self.event_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.event_table.horizontalHeader().setStretchLastSection(True)
        events_layout.addWidget(self.event_table)
        tabs.addTab(events_page, "Provider events")
        root.addWidget(tabs, 1)

        self.status_label = QLabel()
        root.addWidget(self.status_label)
        actions = QHBoxLayout()
        export = QPushButton("Export JSON + CSV")
        export.clicked.connect(self.export_report)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(export)
        actions.addWidget(refresh)
        actions.addStretch(1)
        actions.addWidget(close)
        root.addLayout(actions)

    @staticmethod
    def _weight_spin() -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(0.0, 1.0)
        control.setDecimals(2)
        control.setSingleStep(0.05)
        return control

    def refresh(self) -> None:
        policy = self.service.get_policy(self.project_id)
        self.enabled.setChecked(policy.enabled)
        self.auto_failover.setChecked(policy.auto_failover)
        self.failure_threshold.setValue(policy.failure_threshold)
        self.cooldown.setValue(policy.circuit_cooldown_seconds)
        self.max_switches.setValue(policy.max_switches_per_run)
        self.sticky.setChecked(policy.sticky_successful_profile)
        self.notify.setChecked(policy.notify_on_circuit_open)

        routing = self.service.get_routing_policy(self.project_id)
        self.routing_enabled.setChecked(routing.enabled)
        index = self.routing_mode.findData(str(routing.mode))
        self.routing_mode.setCurrentIndex(max(0, index))
        self.health_weight.setValue(routing.health_weight)
        self.capacity_weight.setValue(routing.capacity_weight)
        self.latency_weight.setValue(routing.latency_weight)
        self.priority_weight.setValue(routing.priority_weight)
        self.quota_reserve.setValue(routing.minimum_quota_reserve)
        self.max_share.setValue(routing.max_profile_share_percent)
        self.sample_window.setValue(routing.sample_window)

        scheduling = self.service.get_scheduling_policy(self.project_id)
        self.scheduling_enabled.setChecked(scheduling.enabled)
        scheduling_index = self.scheduling_mode.findData(str(scheduling.mode))
        self.scheduling_mode.setCurrentIndex(max(0, scheduling_index))
        self.minimum_concurrency.setValue(scheduling.minimum_concurrency)
        self.initial_concurrency.setValue(scheduling.initial_concurrency)
        self.maximum_concurrency.setValue(scheduling.maximum_concurrency)
        self.per_profile_concurrency.setValue(scheduling.per_profile_concurrency)
        self.success_window.setValue(scheduling.success_window)
        self.error_window.setValue(scheduling.error_window)
        self.increase_step.setValue(scheduling.increase_step)
        self.decrease_factor.setValue(scheduling.decrease_factor)
        self.rate_limit_cooldown.setValue(scheduling.rate_limit_cooldown_seconds)

        if self.settings_provider is not None:
            plan = self.service.build_plan(project_id=self.project_id, settings=self.settings_provider())
            excluded = ", ".join(f"{item['profile']}: {item['reason']}" for item in plan.excluded)
            distribution = ", ".join(
                f"{item['profile_name']} {item['share_percent']}%"
                for item in plan.predicted_distribution
                if int(item["jobs"]) > 0
            )
            self.plan_label.setText(
                f"Current plan: {len(plan.candidates)} account(s), {plan.backup_count} backup(s), "
                f"failover={plan.mode}, routing={plan.routing_mode}, "
                f"adaptive={'ready' if plan.routing_enabled else 'inactive'}, "
                f"scheduler={'enabled' if plan.scheduling_enabled else 'serial'}, "
                f"concurrency={plan.initial_concurrency}/{plan.maximum_concurrency}, "
                f"maximum switches={plan.max_switches}."
                + (f" Preview distribution: {distribution}." if distribution else "")
                + (f" Excluded: {excluded}." if excluded else "")
            )
        else:
            self.plan_label.setText("Current execution plan is available when a project window supplies provider settings.")

        metrics = self.service.repository.list_routing_metrics(project_id=self.project_id)
        self.metrics_table.setRowCount(len(metrics))
        for row_index, item in enumerate(metrics):
            values = (
                item.provider,
                item.profile_name or item.profile_id or "Temporary key",
                f"{item.health_score:.1f}",
                str(item.attempts),
                str(item.successes),
                str(item.failures),
                f"{item.success_rate * 100:.1f}%",
                "—" if item.ewma_latency_seconds is None else f"{item.ewma_latency_seconds:.3f}s",
                str(item.total_characters),
                item.last_selected_at or "—",
            )
            for column, value in enumerate(values):
                self.metrics_table.setItem(row_index, column, QTableWidgetItem(value))

        self._circuits = self.service.repository.list_circuits(project_id=self.project_id)
        self.circuit_table.setRowCount(len(self._circuits))
        for row_index, item in enumerate(self._circuits):
            values = (
                item.provider,
                item.profile_name or item.profile_id or "Temporary key",
                str(item.status),
                str(item.consecutive_failures),
                item.retry_after or "—",
                item.last_failure_category or "—",
                item.last_failure_code or "—",
                item.updated_at,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(Qt.UserRole, item.state_key)
                self.circuit_table.setItem(row_index, column, cell)

        decisions = self.service.repository.list_decisions(project_id=self.project_id)
        self.decision_table.setRowCount(len(decisions))
        for row_index, item in enumerate(decisions):
            values = (
                item.created_at,
                item.filename,
                item.profile_name,
                str(item.routing_mode),
                f"{item.routing_score:.2f}",
                str(item.routing_weight),
                str(item.estimated_characters),
                item.reason,
            )
            for column, value in enumerate(values):
                self.decision_table.setItem(row_index, column, QTableWidgetItem(value))

        throttle_states = self.service.repository.list_throttle_states(
            project_id=self.project_id
        )
        self.throttle_table.setRowCount(len(throttle_states))
        for row_index, item in enumerate(throttle_states):
            values = (
                item.provider,
                item.profile_name or item.profile_id or "Temporary key",
                str(item.current_concurrency),
                str(item.recent_rate_limits),
                item.cooldown_until or "—",
                item.last_rate_limit_at or "—",
                item.last_recovered_at or "—",
                item.updated_at,
            )
            for column, value in enumerate(values):
                self.throttle_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )

        scheduler_events = self.service.repository.list_scheduler_events(
            project_id=self.project_id
        )
        self.scheduler_event_table.setRowCount(len(scheduler_events))
        for row_index, event in enumerate(scheduler_events):
            values = (
                event.created_at,
                event.profile_name,
                event.event_type,
                str(event.from_concurrency),
                str(event.to_concurrency),
                str(event.pending_jobs),
                str(event.active_jobs),
                event.reason,
            )
            for column, value in enumerate(values):
                self.scheduler_event_table.setItem(
                    row_index, column, QTableWidgetItem(value)
                )

        events = self.service.repository.list_events(project_id=self.project_id)
        self.event_table.setRowCount(len(events))
        for row_index, event in enumerate(events):
            values = (
                event.created_at,
                event.filename,
                event.provider,
                event.from_profile_name,
                event.to_profile_name or "—",
                event.failure_category,
                event.error_code,
                event.outcome,
                str(event.switch_number),
            )
            for column, value in enumerate(values):
                self.event_table.setItem(row_index, column, QTableWidgetItem(value))
        self.status_label.setText(
            f"{len(metrics)} routing metric(s), {len(decisions)} decision(s), "
            f"{len(self._circuits)} circuit state(s), {len(events)} provider event(s), "
            f"{len(scheduler_events)} scheduler event(s)."
        )

    def save_policy(self) -> None:
        policy = self.service.get_policy(self.project_id)
        self.service.save_policy(
            replace(
                policy,
                enabled=self.enabled.isChecked(),
                auto_failover=self.auto_failover.isChecked(),
                failure_threshold=self.failure_threshold.value(),
                circuit_cooldown_seconds=self.cooldown.value(),
                max_switches_per_run=self.max_switches.value(),
                sticky_successful_profile=self.sticky.isChecked(),
                notify_on_circuit_open=self.notify.isChecked(),
            )
        )
        self.status_label.setText("Orchestration policy saved.")
        self.refresh()

    def save_routing_policy(self) -> None:
        policy = self.service.get_routing_policy(self.project_id)
        self.service.save_routing_policy(
            replace(
                policy,
                enabled=self.routing_enabled.isChecked(),
                mode=RoutingMode(str(self.routing_mode.currentData() or RoutingMode.PRIORITY)),
                health_weight=self.health_weight.value(),
                capacity_weight=self.capacity_weight.value(),
                latency_weight=self.latency_weight.value(),
                priority_weight=self.priority_weight.value(),
                minimum_quota_reserve=self.quota_reserve.value(),
                max_profile_share_percent=self.max_share.value(),
                sample_window=self.sample_window.value(),
            )
        )
        self.status_label.setText("Adaptive routing policy saved.")
        self.refresh()

    def save_scheduling_policy(self) -> None:
        policy = self.service.get_scheduling_policy(self.project_id)
        self.service.save_scheduling_policy(
            replace(
                policy,
                enabled=self.scheduling_enabled.isChecked(),
                mode=SchedulingMode(
                    str(self.scheduling_mode.currentData() or SchedulingMode.ADAPTIVE)
                ),
                minimum_concurrency=self.minimum_concurrency.value(),
                initial_concurrency=self.initial_concurrency.value(),
                maximum_concurrency=self.maximum_concurrency.value(),
                per_profile_concurrency=self.per_profile_concurrency.value(),
                success_window=self.success_window.value(),
                error_window=self.error_window.value(),
                increase_step=self.increase_step.value(),
                decrease_factor=self.decrease_factor.value(),
                rate_limit_cooldown_seconds=self.rate_limit_cooldown.value(),
            )
        )
        self.status_label.setText("Dynamic scheduling policy saved.")
        self.refresh()

    def reset_selected_circuit(self) -> None:
        row = self.circuit_table.currentRow()
        if row < 0 or row >= len(self._circuits):
            self.status_label.setText("Select one circuit state first.")
            return
        item = self._circuits[row]
        self.service.reset_circuit(
            project_id=item.project_id,
            provider=item.provider,
            profile_id=item.profile_id,
            profile_name=item.profile_name,
        )
        self.status_label.setText(f"Reset circuit for {item.profile_name or item.provider}.")
        self.refresh()

    def export_report(self) -> None:
        json_path, csv_path = self.service.export_report(
            self.export_dir,
            project_id=self.project_id,
            project_name=self.project_name,
        )
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}.")
