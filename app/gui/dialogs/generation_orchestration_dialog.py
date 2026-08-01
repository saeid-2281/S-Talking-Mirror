from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import icon
from app.gui.widgets.orchestration_dashboard import (
    OrchestrationMetricCard,
    apply_table_density,
    configure_orchestration_table,
    filter_table,
)
from app.models.domain import AppSettings
from app.models.generation_orchestration import (
    DeadlineRiskLevel,
    GenerationOrchestrationSavedView,
    GenerationOrchestrationViewPreferences,
    OrchestrationAttentionSeverity,
    OrchestrationPreset,
    ProviderCircuitStatus,
    RoutingMode,
    SchedulingMode,
)
from app.services.generation_orchestration_service import GenerationOrchestrationService


class GenerationOrchestrationDialog(QDialog):
    """Operational control center for routing, scheduling and provider health."""

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
        self.setObjectName("generationOrchestrationDialog")
        self.resize(1320, 840)
        self.setMinimumSize(1040, 680)
        self._circuits = []
        self._attention_items = []
        self._saved_views = []
        self._tables: list[QTableWidget] = []
        self._loading_preferences = True
        self._loading_saved_views = True
        self._build_ui()
        self._load_view_preferences()
        self._load_saved_views(apply_default=True)
        self._loading_preferences = False
        self._loading_saved_views = False
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("orchestrationHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 9, 12, 9)
        header_layout.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(1)
        title = QLabel("Queue operations center")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Control failover, adaptive routing, concurrency, deadlines and provider health from one workspace."
        )
        subtitle.setObjectName("dialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        project_badge = QLabel(self.project_name)
        project_badge.setObjectName("orchestrationProjectBadge")
        header_layout.addWidget(project_badge)
        root.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("orchestrationToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 5, 8, 5)
        toolbar_layout.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search accounts, files, events or recommendations")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        self.search.setObjectName("orchestrationSearch")
        toolbar_layout.addWidget(self.search, 1)
        self.status_filter = QComboBox()
        self.status_filter.addItem("All states", "all")
        self.status_filter.addItem("Needs attention", "attention")
        self.status_filter.addItem("Healthy", "healthy")
        self.status_filter.addItem("Failures / switches", "failures")
        self.status_filter.addItem("Rate limited", "rate_limited")
        self.status_filter.addItem("Deadline risk", "at_risk")
        toolbar_layout.addWidget(self.status_filter)
        self.density = QComboBox()
        self.density.addItem("Comfortable", "comfortable")
        self.density.addItem("Compact", "compact")
        toolbar_layout.addWidget(self.density)
        self.auto_refresh = QCheckBox("Auto-refresh")
        toolbar_layout.addWidget(self.auto_refresh)
        self.refresh_interval = QSpinBox()
        self.refresh_interval.setRange(3, 300)
        self.refresh_interval.setSuffix(" s")
        self.refresh_interval.setMaximumWidth(86)
        toolbar_layout.addWidget(self.refresh_interval)
        refresh_button = QPushButton("Refresh")
        refresh_button.setIcon(icon("refresh"))
        refresh_button.clicked.connect(self.refresh)
        toolbar_layout.addWidget(refresh_button)
        export_button = QPushButton("Export")
        export_button.setIcon(icon("report"))
        export_button.clicked.connect(self.export_report)
        toolbar_layout.addWidget(export_button)
        root.addWidget(toolbar)

        view_bar = QFrame()
        view_bar.setObjectName("orchestrationViewBar")
        view_layout = QHBoxLayout(view_bar)
        view_layout.setContentsMargins(8, 5, 8, 5)
        view_layout.setSpacing(6)
        view_title = QLabel("Saved workspace")
        view_title.setObjectName("summaryStrong")
        view_layout.addWidget(view_title)
        self.saved_view_combo = QComboBox()
        self.saved_view_combo.setMinimumWidth(220)
        self.saved_view_combo.setToolTip(
            "Recall a named combination of page, search, filter and table density."
        )
        view_layout.addWidget(self.saved_view_combo, 1)
        self.save_view_button = QPushButton("Save current")
        self.save_view_button.clicked.connect(self.save_current_view)
        view_layout.addWidget(self.save_view_button)
        self.default_view_button = QPushButton("Make default")
        self.default_view_button.clicked.connect(self.make_current_view_default)
        view_layout.addWidget(self.default_view_button)
        self.delete_view_button = QPushButton("Delete")
        self.delete_view_button.clicked.connect(self.delete_current_saved_view)
        view_layout.addWidget(self.delete_view_button)
        self.view_hint = QLabel("Ctrl+Shift+S saves a reusable workspace")
        self.view_hint.setObjectName("summaryMuted")
        view_layout.addWidget(self.view_hint)
        root.addWidget(view_bar)

        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        self.health_card = OrchestrationMetricCard("Healthy accounts")
        self.circuit_card = OrchestrationMetricCard("Circuit breaker")
        self.concurrency_card = OrchestrationMetricCard("Concurrency")
        self.deadline_card = OrchestrationMetricCard("Deadline")
        for card in (
            self.health_card,
            self.circuit_card,
            self.concurrency_card,
            self.deadline_card,
        ):
            metrics.addWidget(card, 1)
        root.addLayout(metrics)

        recommendation = QFrame()
        recommendation.setObjectName("orchestrationRecommendation")
        recommendation_layout = QHBoxLayout(recommendation)
        recommendation_layout.setContentsMargins(10, 7, 10, 7)
        recommendation_title = QLabel("Recommended action")
        recommendation_title.setObjectName("summaryStrong")
        self.recommendation_label = QLabel()
        self.recommendation_label.setObjectName("summaryMuted")
        self.recommendation_label.setWordWrap(True)
        recommendation_layout.addWidget(recommendation_title)
        recommendation_layout.addWidget(self.recommendation_label, 1)
        self.open_attention_button = QPushButton("Review attention")
        self.open_attention_button.clicked.connect(self.open_attention_page)
        recommendation_layout.addWidget(self.open_attention_button)
        root.addWidget(recommendation)

        plan = QFrame()
        plan.setObjectName("orchestrationPlanCard")
        plan_layout = QVBoxLayout(plan)
        plan_layout.setContentsMargins(10, 7, 10, 7)
        plan_title = QLabel("Current execution plan")
        plan_title.setObjectName("summaryStrong")
        self.plan_label = QLabel()
        self.plan_label.setObjectName("summaryMuted")
        self.plan_label.setWordWrap(True)
        plan_layout.addWidget(plan_title)
        plan_layout.addWidget(self.plan_label)
        root.addWidget(plan)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("orchestrationTabs")
        self.tabs.setTabPosition(QTabWidget.West)
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        self._build_overview_page()
        self._build_attention_page()
        self._build_failover_page()
        self._build_routing_page()
        self._build_scheduling_page()
        self._build_deadline_page()
        self._build_health_page()
        self._build_circuit_page()
        self._build_decision_page()
        self._build_scheduler_page()
        self._build_event_page()

        footer = QFrame()
        footer.setObjectName("orchestrationFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 5, 8, 5)
        self.status_label = QLabel()
        self.status_label.setObjectName("summaryMuted")
        footer_layout.addWidget(self.status_label, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer_layout.addWidget(close)
        root.addWidget(footer)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self.apply_filters)
        self.search.editingFinished.connect(self.save_view_preferences)
        self.status_filter.currentIndexChanged.connect(self._view_control_changed)
        self.density.currentIndexChanged.connect(self._view_control_changed)
        self.auto_refresh.toggled.connect(self._view_control_changed)
        self.refresh_interval.valueChanged.connect(self._view_control_changed)
        self.tabs.currentChanged.connect(self._view_control_changed)
        self.saved_view_combo.currentIndexChanged.connect(self.apply_selected_saved_view)

        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self._focus_search)
        self.refresh_shortcut = QShortcut(QKeySequence("F5"), self)
        self.refresh_shortcut.activated.connect(self.refresh)
        self.save_view_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self.save_view_shortcut.activated.connect(self.save_current_view)

    def _build_overview_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        preset_card = QFrame()
        preset_card.setObjectName("orchestrationPresetCard")
        preset_layout = QHBoxLayout(preset_card)
        preset_layout.setContentsMargins(10, 7, 10, 7)
        preset_text = QVBoxLayout()
        preset_title = QLabel("Operational preset")
        preset_title.setObjectName("summaryStrong")
        preset_help = QLabel(
            "Apply a tested baseline, then fine-tune individual policies in the pages below."
        )
        preset_help.setObjectName("summaryMuted")
        preset_text.addWidget(preset_title)
        preset_text.addWidget(preset_help)
        preset_layout.addLayout(preset_text, 1)
        self.preset = QComboBox()
        self.preset.addItem("Safe / serial", OrchestrationPreset.SAFE.value)
        self.preset.addItem("Balanced", OrchestrationPreset.BALANCED.value)
        self.preset.addItem("High throughput", OrchestrationPreset.THROUGHPUT.value)
        self.preset.addItem("Deadline protection", OrchestrationPreset.DEADLINE.value)
        self.preset.setCurrentIndex(1)
        preset_layout.addWidget(self.preset)
        apply_preset = QPushButton("Apply preset")
        apply_preset.setObjectName("primaryButton")
        apply_preset.clicked.connect(self.apply_selected_preset)
        preset_layout.addWidget(apply_preset)
        layout.addWidget(preset_card)

        self.overview_table = configure_orchestration_table(QTableWidget(0, 6))
        self.overview_table.setHorizontalHeaderLabels(
            ["Provider", "Account", "Health", "Circuit", "Concurrency", "Operator note"]
        )
        layout.addWidget(self.overview_table, 1)
        self._tables.append(self.overview_table)
        self.tabs.addTab(page, "Overview")

    def _build_attention_page(self) -> None:
        self.attention_page = QWidget()
        layout = QVBoxLayout(self.attention_page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        summary = QFrame()
        summary.setObjectName("orchestrationAttentionSummary")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(10, 7, 10, 7)
        summary_text = QVBoxLayout()
        title = QLabel("Operator attention queue")
        title.setObjectName("summaryStrong")
        self.attention_summary_label = QLabel(
            "Only actionable circuit, rate-limit and deadline risks appear here."
        )
        self.attention_summary_label.setObjectName("summaryMuted")
        summary_text.addWidget(title)
        summary_text.addWidget(self.attention_summary_label)
        summary_layout.addLayout(summary_text, 1)
        self.run_selected_attention = QPushButton("Run selected action")
        self.run_selected_attention.setObjectName("primaryButton")
        self.run_selected_attention.clicked.connect(self.execute_selected_attention)
        summary_layout.addWidget(self.run_selected_attention)
        self.run_safe_attention = QPushButton("Run all safe fixes")
        self.run_safe_attention.clicked.connect(self.execute_all_safe_attention)
        summary_layout.addWidget(self.run_safe_attention)
        layout.addWidget(summary)

        self.attention_table = configure_orchestration_table(QTableWidget(0, 8))
        self.attention_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.attention_table.setHorizontalHeaderLabels(
            [
                "Severity",
                "Type",
                "Provider",
                "Account / scope",
                "Issue",
                "Recommendation",
                "Action",
                "Updated",
            ]
        )
        layout.addWidget(self.attention_table, 2)

        history_title = QLabel("Recent operator actions")
        history_title.setObjectName("summaryStrong")
        layout.addWidget(history_title)
        self.operator_action_table = configure_orchestration_table(QTableWidget(0, 5))
        self.operator_action_table.setHorizontalHeaderLabels(
            ["Created", "Action", "Targets", "Summary", "Details"]
        )
        layout.addWidget(self.operator_action_table, 1)
        self._tables.extend((self.attention_table, self.operator_action_table))
        self.tabs.addTab(self.attention_page, "Attention")

    def _build_failover_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
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
        layout.addLayout(form)
        save = QPushButton("Save failover policy")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_policy)
        layout.addWidget(save, 0, Qt.AlignLeft)
        layout.addStretch(1)
        self.tabs.addTab(page, "Failover")

    def _build_routing_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
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
        form.addRow("Adaptive routing", self.routing_enabled)
        form.addRow("Routing mode", self.routing_mode)
        form.addRow("Health weight", self.health_weight)
        form.addRow("Capacity weight", self.capacity_weight)
        form.addRow("Latency weight", self.latency_weight)
        form.addRow("Priority weight", self.priority_weight)
        form.addRow("Minimum quota reserve", self.quota_reserve)
        form.addRow("Maximum share per account", self.max_share)
        form.addRow("Telemetry sample window", self.sample_window)
        layout.addLayout(form)
        save = QPushButton("Save adaptive routing policy")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_routing_policy)
        layout.addWidget(save, 0, Qt.AlignLeft)
        layout.addStretch(1)
        self.tabs.addTab(page, "Routing")

    def _build_scheduling_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.scheduling_enabled = QCheckBox("Run independent generation requests concurrently")
        self.scheduling_mode = QComboBox()
        self.scheduling_mode.addItem("Static concurrency", SchedulingMode.STATIC.value)
        self.scheduling_mode.addItem("Adaptive backpressure", SchedulingMode.ADAPTIVE.value)
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
        form.addRow("Concurrent scheduler", self.scheduling_enabled)
        form.addRow("Scheduling mode", self.scheduling_mode)
        form.addRow("Minimum concurrency", self.minimum_concurrency)
        form.addRow("Initial concurrency", self.initial_concurrency)
        form.addRow("Maximum concurrency", self.maximum_concurrency)
        form.addRow("Per-account concurrency", self.per_profile_concurrency)
        form.addRow("Success window", self.success_window)
        form.addRow("Error window", self.error_window)
        form.addRow("Increase step", self.increase_step)
        form.addRow("Decrease factor", self.decrease_factor)
        form.addRow("Rate-limit cooldown", self.rate_limit_cooldown)
        layout.addLayout(form)
        save = QPushButton("Save scheduling policy")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_scheduling_policy)
        layout.addWidget(save, 0, Qt.AlignLeft)
        layout.addStretch(1)
        self.tabs.addTab(page, "Concurrency")

    def _build_deadline_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.deadline_enabled = QCheckBox("Forecast queue completion and protect the configured deadline")
        self.target_completion_minutes = QSpinBox()
        self.target_completion_minutes.setRange(1, 10080)
        self.target_completion_minutes.setSuffix(" min")
        self.warning_slack_minutes = QSpinBox()
        self.warning_slack_minutes.setRange(0, 1440)
        self.warning_slack_minutes.setSuffix(" min")
        self.allow_deadline_boost = QCheckBox("Increase initial concurrency when the queue is at risk")
        self.maximum_deadline_concurrency = QSpinBox()
        self.maximum_deadline_concurrency.setRange(1, 32)
        self.fallback_characters_per_minute = QSpinBox()
        self.fallback_characters_per_minute.setRange(1, 1_000_000)
        self.fallback_characters_per_minute.setSuffix(" chars/min")
        self.deadline_safety_margin = QSpinBox()
        self.deadline_safety_margin.setRange(0, 90)
        self.deadline_safety_margin.setSuffix(" %")
        self.persist_forecasts = QCheckBox("Store queue forecasts for audit and comparison")
        form.addRow("Deadline planning", self.deadline_enabled)
        form.addRow("Target completion window", self.target_completion_minutes)
        form.addRow("Warning slack", self.warning_slack_minutes)
        form.addRow("Automatic concurrency boost", self.allow_deadline_boost)
        form.addRow("Deadline concurrency cap", self.maximum_deadline_concurrency)
        form.addRow("Fallback throughput", self.fallback_characters_per_minute)
        form.addRow("Forecast safety margin", self.deadline_safety_margin)
        form.addRow("Forecast retention", self.persist_forecasts)
        layout.addLayout(form)
        save = QPushButton("Save deadline policy")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_deadline_policy)
        layout.addWidget(save, 0, Qt.AlignLeft)
        self.forecast_table = configure_orchestration_table(QTableWidget(0, 12))
        self.forecast_table.setHorizontalHeaderLabels(
            [
                "Created", "Jobs", "Characters", "Current", "Recommended", "Chars/min",
                "Duration", "Finish", "Deadline", "Slack", "Risk", "Recommendation",
            ]
        )
        layout.addWidget(self.forecast_table, 1)
        self._tables.append(self.forecast_table)
        self.tabs.addTab(page, "Deadline")

    def _build_health_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.metrics_table = configure_orchestration_table(QTableWidget(0, 10))
        self.metrics_table.setHorizontalHeaderLabels(
            [
                "Provider", "Account", "Health", "Attempts", "Success", "Failure",
                "Success rate", "EWMA latency", "Characters", "Last selected",
            ]
        )
        layout.addWidget(self.metrics_table)
        self._tables.append(self.metrics_table)
        self.tabs.addTab(page, "Health")

    def _build_circuit_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.circuit_table = configure_orchestration_table(QTableWidget(0, 8))
        self.circuit_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.circuit_table.setHorizontalHeaderLabels(
            ["Provider", "Account", "State", "Failures", "Retry after", "Last category", "Last code", "Updated"]
        )
        layout.addWidget(self.circuit_table)
        reset = QPushButton("Reset selected circuit")
        reset.setIcon(icon("reset"))
        reset.clicked.connect(self.reset_selected_circuit)
        layout.addWidget(reset, 0, Qt.AlignLeft)
        self._tables.append(self.circuit_table)
        self.tabs.addTab(page, "Circuits")

    def _build_decision_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.decision_table = configure_orchestration_table(QTableWidget(0, 8))
        self.decision_table.setHorizontalHeaderLabels(
            ["Created", "File", "Account", "Mode", "Score", "Weight", "Characters", "Reason"]
        )
        layout.addWidget(self.decision_table)
        self._tables.append(self.decision_table)
        self.tabs.addTab(page, "Decisions")

    def _build_scheduler_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.throttle_table = configure_orchestration_table(QTableWidget(0, 8))
        self.throttle_table.setHorizontalHeaderLabels(
            ["Provider", "Account", "Concurrency", "Rate limits", "Cooldown until", "Last rate limit", "Recovered", "Updated"]
        )
        layout.addWidget(self.throttle_table)
        self.scheduler_event_table = configure_orchestration_table(QTableWidget(0, 8))
        self.scheduler_event_table.setHorizontalHeaderLabels(
            ["Created", "Account", "Event", "From", "To", "Pending", "Active", "Reason"]
        )
        layout.addWidget(self.scheduler_event_table)
        self._tables.extend((self.throttle_table, self.scheduler_event_table))
        self.tabs.addTab(page, "Scheduler")

    def _build_event_page(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.event_table = configure_orchestration_table(QTableWidget(0, 9))
        self.event_table.setHorizontalHeaderLabels(
            ["Created", "File", "Provider", "From", "To", "Category", "Code", "Outcome", "Switch"]
        )
        layout.addWidget(self.event_table)
        self._tables.append(self.event_table)
        self.tabs.addTab(page, "Events")

    @staticmethod
    def _weight_spin() -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(0.0, 1.0)
        control.setDecimals(2)
        control.setSingleStep(0.05)
        return control

    def _load_view_preferences(self) -> None:
        preferences = self.service.get_view_preferences(self.project_id)
        self.search.setText(preferences.search_text)
        filter_index = self.status_filter.findData(preferences.status_filter)
        self.status_filter.setCurrentIndex(max(0, filter_index))
        density_index = self.density.findData(preferences.table_density)
        self.density.setCurrentIndex(max(0, density_index))
        self.auto_refresh.setChecked(preferences.auto_refresh)
        self.refresh_interval.setValue(preferences.refresh_interval_seconds)
        self.tabs.setCurrentIndex(min(preferences.selected_tab, self.tabs.count() - 1))
        self._update_refresh_timer()
        apply_table_density(self._tables, preferences.table_density)

    def _load_saved_views(self, *, apply_default: bool = False) -> None:
        self._loading_saved_views = True
        self._saved_views = self.service.list_saved_views(self.project_id)
        self.saved_view_combo.clear()
        self.saved_view_combo.addItem("Current workspace", None)
        default_index = 0
        for view in self._saved_views:
            label = f"★ {view.name}" if view.is_default else view.name
            self.saved_view_combo.addItem(label, view.view_id)
            if view.is_default:
                default_index = self.saved_view_combo.count() - 1
        self.saved_view_combo.setCurrentIndex(default_index if apply_default else 0)
        self.default_view_button.setEnabled(bool(self._saved_views))
        self.delete_view_button.setEnabled(bool(self._saved_views))
        self._loading_saved_views = False
        if apply_default and default_index > 0:
            self.apply_selected_saved_view(default_index)

    def _apply_preferences_to_controls(
        self,
        preferences: GenerationOrchestrationViewPreferences,
    ) -> None:
        self._loading_preferences = True
        self.search.setText(preferences.search_text)
        filter_index = self.status_filter.findData(preferences.status_filter)
        self.status_filter.setCurrentIndex(max(0, filter_index))
        density_index = self.density.findData(preferences.table_density)
        self.density.setCurrentIndex(max(0, density_index))
        self.tabs.setCurrentIndex(min(preferences.selected_tab, self.tabs.count() - 1))
        apply_table_density(self._tables, preferences.table_density)
        self._loading_preferences = False
        self.apply_filters()

    def apply_selected_saved_view(self, _index: int = -1) -> None:
        if self._loading_saved_views:
            return
        view_id = self.saved_view_combo.currentData()
        if not view_id:
            return
        preferences = self.service.apply_saved_view(str(view_id))
        self._apply_preferences_to_controls(preferences)
        self.status_label.setText(
            f"Applied saved workspace: {self.saved_view_combo.currentText().lstrip('★ ')}."
        )

    def save_current_view(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "Save orchestration workspace",
            "Workspace name",
        )
        if not accepted:
            return
        try:
            saved = self.service.save_saved_view(
                GenerationOrchestrationSavedView(
                    view_id="",
                    project_id=self.project_id,
                    name=name,
                    selected_tab=self.tabs.currentIndex(),
                    table_density=str(self.density.currentData() or "comfortable"),
                    search_text=self.search.text(),
                    status_filter=str(self.status_filter.currentData() or "all"),
                )
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self._load_saved_views()
        index = self.saved_view_combo.findData(saved.view_id)
        self.saved_view_combo.setCurrentIndex(max(0, index))
        self.status_label.setText(f"Saved workspace: {saved.name}.")

    def make_current_view_default(self) -> None:
        view_id = self.saved_view_combo.currentData()
        if not view_id:
            self.status_label.setText("Select a saved workspace first.")
            return
        saved = self.service.set_default_saved_view(str(view_id))
        self._load_saved_views()
        index = self.saved_view_combo.findData(saved.view_id)
        self.saved_view_combo.setCurrentIndex(max(0, index))
        self.status_label.setText(f"Default workspace set to {saved.name}.")

    def delete_current_saved_view(self) -> None:
        view_id = self.saved_view_combo.currentData()
        if not view_id:
            self.status_label.setText("Select a saved workspace first.")
            return
        deleted = self.service.delete_saved_view(str(view_id))
        self._load_saved_views()
        self.status_label.setText(
            "Saved workspace deleted." if deleted else "Saved workspace was not found."
        )

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def open_attention_page(self) -> None:
        self.tabs.setCurrentWidget(self.attention_page)
        self.attention_table.setFocus()

    def _view_control_changed(self, *_args) -> None:
        if self._loading_preferences:
            return
        self._update_refresh_timer()
        apply_table_density(self._tables, str(self.density.currentData() or "comfortable"))
        self.apply_filters()
        self.save_view_preferences()

    def _update_refresh_timer(self) -> None:
        self.refresh_timer.setInterval(self.refresh_interval.value() * 1000)
        if self.auto_refresh.isChecked():
            self.refresh_timer.start()
        else:
            self.refresh_timer.stop()

    def save_view_preferences(self) -> None:
        if self._loading_preferences:
            return
        self.service.save_view_preferences(
            GenerationOrchestrationViewPreferences(
                project_id=self.project_id,
                selected_tab=self.tabs.currentIndex(),
                auto_refresh=self.auto_refresh.isChecked(),
                refresh_interval_seconds=self.refresh_interval.value(),
                table_density=str(self.density.currentData() or "comfortable"),
                search_text=self.search.text(),
                status_filter=str(self.status_filter.currentData() or "all"),
            )
        )

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
        self.routing_mode.setCurrentIndex(max(0, self.routing_mode.findData(str(routing.mode))))
        self.health_weight.setValue(routing.health_weight)
        self.capacity_weight.setValue(routing.capacity_weight)
        self.latency_weight.setValue(routing.latency_weight)
        self.priority_weight.setValue(routing.priority_weight)
        self.quota_reserve.setValue(routing.minimum_quota_reserve)
        self.max_share.setValue(routing.max_profile_share_percent)
        self.sample_window.setValue(routing.sample_window)

        scheduling = self.service.get_scheduling_policy(self.project_id)
        self.scheduling_enabled.setChecked(scheduling.enabled)
        self.scheduling_mode.setCurrentIndex(max(0, self.scheduling_mode.findData(str(scheduling.mode))))
        self.minimum_concurrency.setValue(scheduling.minimum_concurrency)
        self.initial_concurrency.setValue(scheduling.initial_concurrency)
        self.maximum_concurrency.setValue(scheduling.maximum_concurrency)
        self.per_profile_concurrency.setValue(scheduling.per_profile_concurrency)
        self.success_window.setValue(scheduling.success_window)
        self.error_window.setValue(scheduling.error_window)
        self.increase_step.setValue(scheduling.increase_step)
        self.decrease_factor.setValue(scheduling.decrease_factor)
        self.rate_limit_cooldown.setValue(scheduling.rate_limit_cooldown_seconds)

        deadline = self.service.get_deadline_policy(self.project_id)
        self.deadline_enabled.setChecked(deadline.enabled)
        self.target_completion_minutes.setValue(deadline.target_completion_minutes)
        self.warning_slack_minutes.setValue(deadline.warning_slack_minutes)
        self.allow_deadline_boost.setChecked(deadline.allow_concurrency_boost)
        self.maximum_deadline_concurrency.setValue(deadline.maximum_deadline_concurrency)
        self.fallback_characters_per_minute.setValue(deadline.fallback_characters_per_minute)
        self.deadline_safety_margin.setValue(deadline.safety_margin_percent)
        self.persist_forecasts.setChecked(deadline.persist_forecasts)

        forecasts = self.service.repository.list_queue_forecasts(project_id=self.project_id)
        self.forecast_table.setRowCount(len(forecasts))
        for row_index, forecast in enumerate(forecasts):
            values = (
                forecast.created_at,
                str(forecast.job_count),
                str(forecast.total_characters),
                str(forecast.current_concurrency),
                str(forecast.recommended_concurrency),
                f"{forecast.characters_per_minute:.1f}",
                f"{forecast.estimated_duration_seconds / 60.0:.1f} min",
                forecast.estimated_finish_at,
                forecast.deadline_at,
                f"{forecast.slack_seconds / 60.0:.1f} min",
                f"{forecast.risk_level} ({forecast.risk_score:.2f})",
                forecast.recommendation,
            )
            self._set_row(self.forecast_table, row_index, values)

        if self.settings_provider is not None:
            plan = self.service.build_plan(
                project_id=self.project_id,
                settings=self.settings_provider(),
            )
            excluded = ", ".join(
                f"{item['profile']}: {item['reason']}" for item in plan.excluded
            )
            distribution = ", ".join(
                f"{item['profile_name']} {item['share_percent']}%"
                for item in plan.predicted_distribution
                if int(item["jobs"]) > 0
            )
            self.plan_label.setText(
                f"{len(plan.candidates)} account(s), {plan.backup_count} backup(s); "
                f"failover={plan.mode}, routing={plan.routing_mode}, "
                f"adaptive={'ready' if plan.routing_enabled else 'inactive'}, "
                f"scheduler={'enabled' if plan.scheduling_enabled else 'serial'}, "
                f"concurrency={plan.initial_concurrency}/{plan.maximum_concurrency}, "
                f"maximum switches={plan.max_switches}."
                + (f" Distribution: {distribution}." if distribution else "")
                + (f" Excluded: {excluded}." if excluded else "")
                + (
                    f" Latest forecast: {forecasts[0].risk_level}; recommended concurrency "
                    f"{forecasts[0].recommended_concurrency}."
                    if forecasts
                    else ""
                )
            )
        else:
            self.plan_label.setText(
                "Execution-plan preview becomes available when the project window supplies provider settings."
            )

        metrics = self.service.repository.list_routing_metrics(project_id=self.project_id)
        self.metrics_table.setRowCount(len(metrics))
        for row_index, item in enumerate(metrics):
            self._set_row(
                self.metrics_table,
                row_index,
                (
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
                ),
            )

        self._circuits = self.service.repository.list_circuits(project_id=self.project_id)
        self.circuit_table.setRowCount(len(self._circuits))
        for row_index, item in enumerate(self._circuits):
            self._set_row(
                self.circuit_table,
                row_index,
                (
                    item.provider,
                    item.profile_name or item.profile_id or "Temporary key",
                    str(item.status),
                    str(item.consecutive_failures),
                    item.retry_after or "—",
                    item.last_failure_category or "—",
                    item.last_failure_code or "—",
                    item.updated_at,
                ),
                user_data=(0, item.state_key),
            )

        decisions = self.service.repository.list_decisions(project_id=self.project_id)
        self.decision_table.setRowCount(len(decisions))
        for row_index, item in enumerate(decisions):
            self._set_row(
                self.decision_table,
                row_index,
                (
                    item.created_at,
                    item.filename,
                    item.profile_name,
                    str(item.routing_mode),
                    f"{item.routing_score:.2f}",
                    str(item.routing_weight),
                    str(item.estimated_characters),
                    item.reason,
                ),
            )

        throttle_states = self.service.repository.list_throttle_states(project_id=self.project_id)
        self.throttle_table.setRowCount(len(throttle_states))
        for row_index, item in enumerate(throttle_states):
            self._set_row(
                self.throttle_table,
                row_index,
                (
                    item.provider,
                    item.profile_name or item.profile_id or "Temporary key",
                    str(item.current_concurrency),
                    str(item.recent_rate_limits),
                    item.cooldown_until or "—",
                    item.last_rate_limit_at or "—",
                    item.last_recovered_at or "—",
                    item.updated_at,
                ),
            )

        scheduler_events = self.service.repository.list_scheduler_events(project_id=self.project_id)
        self.scheduler_event_table.setRowCount(len(scheduler_events))
        for row_index, event in enumerate(scheduler_events):
            self._set_row(
                self.scheduler_event_table,
                row_index,
                (
                    event.created_at,
                    event.profile_name,
                    event.event_type,
                    str(event.from_concurrency),
                    str(event.to_concurrency),
                    str(event.pending_jobs),
                    str(event.active_jobs),
                    event.reason,
                ),
            )

        events = self.service.repository.list_events(project_id=self.project_id)
        self.event_table.setRowCount(len(events))
        for row_index, event in enumerate(events):
            self._set_row(
                self.event_table,
                row_index,
                (
                    event.created_at,
                    event.filename,
                    event.provider,
                    event.from_profile_name,
                    event.to_profile_name or "—",
                    event.failure_category,
                    event.error_code,
                    event.outcome,
                    str(event.switch_number),
                ),
            )

        circuit_by_account = {
            (item.provider, item.profile_name or item.profile_id or "Temporary key"): item
            for item in self._circuits
        }
        throttle_by_account = {
            (item.provider, item.profile_name or item.profile_id or "Temporary key"): item
            for item in throttle_states
        }
        overview_rows = []
        for item in metrics:
            account = item.profile_name or item.profile_id or "Temporary key"
            circuit = circuit_by_account.get((item.provider, account))
            throttle = throttle_by_account.get((item.provider, account))
            circuit_state = str(circuit.status) if circuit else "closed"
            concurrency = throttle.current_concurrency if throttle else scheduling.initial_concurrency
            if circuit_state == str(ProviderCircuitStatus.OPEN):
                note = "Temporarily excluded; review failure and retry time."
            elif throttle and (throttle.recent_rate_limits > 0 or throttle.cooldown_until):
                note = "Backpressure active; keep adaptive scheduling enabled."
            elif item.health_score < 80:
                note = "Health is degraded; monitor failures and latency."
            else:
                note = "Healthy and eligible for routing."
            overview_rows.append(
                (
                    item.provider,
                    account,
                    f"{item.health_score:.1f}",
                    circuit_state,
                    str(concurrency),
                    note,
                )
            )
        for circuit in self._circuits:
            account = circuit.profile_name or circuit.profile_id or "Temporary key"
            if any(row[0] == circuit.provider and row[1] == account for row in overview_rows):
                continue
            overview_rows.append(
                (
                    circuit.provider,
                    account,
                    "—",
                    str(circuit.status),
                    str(scheduling.initial_concurrency),
                    "No routing metric has been recorded yet.",
                )
            )
        self.overview_table.setRowCount(len(overview_rows))
        for row_index, values in enumerate(overview_rows):
            self._set_row(self.overview_table, row_index, values)

        self._attention_items = self.service.attention_items(self.project_id)
        self.attention_table.setRowCount(len(self._attention_items))
        for row_index, item in enumerate(self._attention_items):
            values = (
                str(item.severity),
                item.category,
                item.provider,
                item.profile_name,
                item.title,
                item.recommendation,
                item.action_type.replace("_", " "),
                item.updated_at,
            )
            self._set_row(
                self.attention_table,
                row_index,
                values,
                user_data=(0, item.attention_id),
            )
        actions = self.service.repository.list_operator_actions(
            project_id=self.project_id,
            limit=100,
        )
        self.operator_action_table.setRowCount(len(actions))
        for row_index, action in enumerate(actions):
            values = (
                action.created_at,
                action.action_type.replace("_", " "),
                str(action.target_count),
                action.summary,
                ", ".join(str(item) for item in action.metadata.get("errors", [])) or "—",
            )
            self._set_row(self.operator_action_table, row_index, values)
        critical_count = sum(
            1
            for item in self._attention_items
            if item.severity == OrchestrationAttentionSeverity.CRITICAL
        )
        self.attention_summary_label.setText(
            f"{len(self._attention_items)} actionable item(s); "
            f"{critical_count} critical. Select rows or run all safe fixes."
        )
        self.open_attention_button.setText(
            f"Review attention ({len(self._attention_items)})"
        )
        self.run_selected_attention.setEnabled(bool(self._attention_items))
        self.run_safe_attention.setEnabled(
            any(
                item.action_type in {"reset_circuit", "clear_throttle"}
                for item in self._attention_items
            )
        )

        summary = self.service.dashboard_summary(self.project_id)
        self.health_card.update_metric(
            str(summary.healthy_profiles),
            f"{summary.degraded_profiles} degraded",
            status="success" if summary.degraded_profiles == 0 else "warning",
        )
        circuit_status = "success" if summary.open_circuits == 0 else "error"
        self.circuit_card.update_metric(
            str(summary.open_circuits),
            f"{summary.half_open_circuits} half-open",
            status=circuit_status,
        )
        self.concurrency_card.update_metric(
            str(summary.current_concurrency),
            f"{summary.rate_limited_profiles} throttled account(s)",
            status="warning" if summary.rate_limited_profiles else "success",
        )
        deadline_detail = (
            "No forecast yet"
            if summary.latest_deadline_slack_seconds is None
            else f"{summary.latest_deadline_slack_seconds / 60.0:.1f} min slack"
        )
        self.deadline_card.update_metric(
            str(summary.latest_deadline_risk),
            deadline_detail,
            status=(
                "error"
                if summary.latest_deadline_risk == DeadlineRiskLevel.MISSED
                else "warning"
                if summary.latest_deadline_risk in {DeadlineRiskLevel.WATCH, DeadlineRiskLevel.AT_RISK}
                else "success"
                if summary.latest_deadline_risk == DeadlineRiskLevel.ON_TRACK
                else "neutral"
            ),
        )
        self.recommendation_label.setText(summary.recommendation)
        self.recommendation_label.setProperty("status", summary.severity)
        self.recommendation_label.style().unpolish(self.recommendation_label)
        self.recommendation_label.style().polish(self.recommendation_label)

        apply_table_density(self._tables, str(self.density.currentData() or "comfortable"))
        self.apply_filters()
        self.status_label.setText(
            f"{len(metrics)} account metric(s), {len(decisions)} routing decision(s), "
            f"{len(self._circuits)} circuit state(s), {len(events)} provider event(s), "
            f"{len(scheduler_events)} scheduler event(s), {len(forecasts)} forecast(s)."
        )

    @staticmethod
    def _set_row(
        table: QTableWidget,
        row: int,
        values: tuple[str, ...],
        *,
        user_data: tuple[int, object] | None = None,
    ) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if user_data is not None and column == user_data[0]:
                item.setData(Qt.UserRole, user_data[1])
            table.setItem(row, column, item)

    def apply_filters(self, *_args) -> None:
        query = self.search.text()
        state = str(self.status_filter.currentData() or "all")
        visible = sum(filter_table(table, query, state) for table in self._tables)
        if hasattr(self, "status_label"):
            self.status_label.setToolTip(f"{visible} visible row(s) across all operational tables.")

    def apply_selected_preset(self) -> None:
        selected = str(self.preset.currentData() or OrchestrationPreset.BALANCED.value)
        result = self.service.apply_preset(self.project_id, selected)
        self.status_label.setText(f"Applied the {result['preset']} orchestration preset.")
        self.refresh()

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
                mode=SchedulingMode(str(self.scheduling_mode.currentData() or SchedulingMode.ADAPTIVE)),
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

    def save_deadline_policy(self) -> None:
        policy = self.service.get_deadline_policy(self.project_id)
        self.service.save_deadline_policy(
            replace(
                policy,
                enabled=self.deadline_enabled.isChecked(),
                target_completion_minutes=self.target_completion_minutes.value(),
                warning_slack_minutes=self.warning_slack_minutes.value(),
                allow_concurrency_boost=self.allow_deadline_boost.isChecked(),
                maximum_deadline_concurrency=self.maximum_deadline_concurrency.value(),
                fallback_characters_per_minute=self.fallback_characters_per_minute.value(),
                safety_margin_percent=self.deadline_safety_margin.value(),
                persist_forecasts=self.persist_forecasts.isChecked(),
            )
        )
        self.status_label.setText("Deadline scheduling policy saved.")
        self.refresh()

    def _selected_attention_ids(self) -> list[str]:
        rows = {index.row() for index in self.attention_table.selectedIndexes()}
        if not rows and self.attention_table.currentRow() >= 0:
            rows.add(self.attention_table.currentRow())
        selected: list[str] = []
        for row in sorted(rows):
            item = self.attention_table.item(row, 0)
            if item is None:
                continue
            attention_id = item.data(Qt.UserRole)
            if attention_id:
                selected.append(str(attention_id))
        return selected

    def execute_selected_attention(self) -> None:
        selected = self._selected_attention_ids()
        if not selected:
            self.status_label.setText("Select one or more attention items first.")
            return
        action = self.service.execute_attention_actions(self.project_id, selected)
        self.status_label.setText(action.summary)
        self.refresh()

    def execute_all_safe_attention(self) -> None:
        safe_ids = [
            item.attention_id
            for item in self._attention_items
            if item.action_type in {"reset_circuit", "clear_throttle"}
        ]
        if not safe_ids:
            self.status_label.setText("No safe circuit or throttle fixes are available.")
            return
        action = self.service.execute_attention_actions(
            self.project_id,
            safe_ids,
            safe_only=True,
        )
        self.status_label.setText(action.summary)
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

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_view_preferences()
        self.refresh_timer.stop()
        super().closeEvent(event)
