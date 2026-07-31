from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_cost_capacity import (
    GenerationCostBudgetPolicy,
    GenerationCostCapacityDashboard,
    GenerationPricingRate,
)
from app.services.generation_cost_capacity_service import GenerationCostCapacityService
from app.services.monitor_formatting import format_duration


class GenerationCostBudgetPolicyDialog(QDialog):
    def __init__(
        self,
        service: GenerationCostCapacityService,
        policy: GenerationCostBudgetPolicy,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.policy = policy
        self.saved_policy: GenerationCostBudgetPolicy | None = None
        self.setWindowTitle("Cost Budget Policy")
        self.resize(560, 510)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox("Evaluate budgets and publish alerts")
        self.currency = QLineEdit()
        self.currency.setMaxLength(8)
        self.daily_budget = self._money()
        self.weekly_budget = self._money()
        self.monthly_budget = self._money()
        self.warning_percent = self._percentage()
        self.max_queue_cost = self._money()
        self.default_rate = self._money(maximum=1_000_000.0)
        self.bill_retries = QCheckBox("Include estimated retry characters")
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 525600)
        self.cooldown.setSuffix(" min")
        form.addRow("Enabled", self.enabled)
        form.addRow("Currency", self.currency)
        form.addRow("Daily budget", self.daily_budget)
        form.addRow("Weekly budget", self.weekly_budget)
        form.addRow("Monthly budget", self.monthly_budget)
        form.addRow("Warning threshold", self.warning_percent)
        form.addRow("Maximum queued-work cost", self.max_queue_cost)
        form.addRow("Default price / 1M characters", self.default_rate)
        form.addRow("Retry billing", self.bill_retries)
        form.addRow("Alert cooldown", self.cooldown)
        root.addLayout(form)
        help_label = QLabel(
            "A budget value of 0 disables that limit. Provider/model rates override "
            "the default price. Currency conversion is intentionally not performed."
        )
        help_label.setWordWrap(True)
        root.addWidget(help_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._load()

    @staticmethod
    def _money(*, maximum: float = 1_000_000_000.0) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(0.0, maximum)
        control.setDecimals(4)
        return control

    @staticmethod
    def _percentage() -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(1.0, 100.0)
        control.setDecimals(1)
        control.setSuffix("%")
        return control

    def _load(self) -> None:
        policy = self.policy
        self.enabled.setChecked(policy.enabled)
        self.currency.setText(policy.currency)
        self.daily_budget.setValue(policy.daily_budget)
        self.weekly_budget.setValue(policy.weekly_budget)
        self.monthly_budget.setValue(policy.monthly_budget)
        self.warning_percent.setValue(policy.warning_percent)
        self.max_queue_cost.setValue(policy.max_queue_cost)
        self.default_rate.setValue(policy.default_price_per_million_characters)
        self.bill_retries.setChecked(policy.bill_retry_characters)
        self.cooldown.setValue(policy.alert_cooldown_minutes)

    def save(self) -> None:
        self.saved_policy = self.service.save_policy(
            replace(
                self.policy,
                enabled=self.enabled.isChecked(),
                currency=self.currency.text(),
                daily_budget=self.daily_budget.value(),
                weekly_budget=self.weekly_budget.value(),
                monthly_budget=self.monthly_budget.value(),
                warning_percent=self.warning_percent.value(),
                max_queue_cost=self.max_queue_cost.value(),
                default_price_per_million_characters=self.default_rate.value(),
                bill_retry_characters=self.bill_retries.isChecked(),
                alert_cooldown_minutes=self.cooldown.value(),
            )
        )
        self.accept()


class GenerationPricingRateDialog(QDialog):
    def __init__(
        self,
        service: GenerationCostCapacityService,
        rate: GenerationPricingRate,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.rate = rate
        self.saved_rate: GenerationPricingRate | None = None
        self.setWindowTitle("Provider Pricing Rate")
        self.resize(500, 360)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.provider = QLineEdit(rate.provider)
        self.model = QLineEdit(rate.model)
        self.price = QDoubleSpinBox()
        self.price.setRange(0.0, 1_000_000.0)
        self.price.setDecimals(6)
        self.price.setValue(rate.price_per_million_characters)
        self.currency = QLineEdit(rate.currency)
        self.currency.setMaxLength(8)
        self.source = QComboBox()
        self.source.addItems(["manual", "provider", "contract", "imported"])
        source_index = self.source.findText(rate.source)
        self.source.setCurrentIndex(max(0, source_index))
        self.scope = QLabel("Project" if rate.project_id is not None else "Global")
        form.addRow("Scope", self.scope)
        form.addRow("Provider", self.provider)
        form.addRow("Model (* for all)", self.model)
        form.addRow("Price / 1M characters", self.price)
        form.addRow("Currency", self.currency)
        form.addRow("Source", self.source)
        root.addLayout(form)
        self.status_label = QLabel()
        root.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def save(self) -> None:
        if not self.provider.text().strip():
            self.status_label.setText("Provider is required.")
            return
        self.saved_rate = self.service.save_rate(
            replace(
                self.rate,
                provider=self.provider.text(),
                model=self.model.text() or "*",
                price_per_million_characters=self.price.value(),
                currency=self.currency.text(),
                source=self.source.currentText(),
            )
        )
        self.accept()


class GenerationCostCapacityDialog(QDialog):
    """Cost, budget, provider-efficiency, and queue-capacity dashboard."""

    def __init__(
        self,
        service: GenerationCostCapacityService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
        provider: str = "",
        model: str = "",
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.project_name = project_name
        self.provider = provider
        self.model = model
        self.export_dir = export_dir or Path.cwd() / "reports" / "cost-capacity"
        self.dashboard_data: GenerationCostCapacityDashboard | None = None
        self.setWindowTitle("Generation Cost & Capacity")
        self.resize(1320, 820)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Cost & Capacity Intelligence")
        title.setStyleSheet("font-size:20px;font-weight:700;")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(QLabel(self.project_name))
        root.addLayout(heading)

        summary = QHBoxLayout()
        self.state_label = self._metric_label("State", "—")
        self.today_label = self._metric_label("Today", "—")
        self.month_label = self._metric_label("This month", "—")
        self.retry_label = self._metric_label("Retry waste", "—")
        self.queue_label = self._metric_label("Queued cost", "—")
        self.eta_label = self._metric_label("Queue ETA", "—")
        for label in (
            self.state_label,
            self.today_label,
            self.month_label,
            self.retry_label,
            self.queue_label,
            self.eta_label,
        ):
            summary.addWidget(label, 1)
        root.addLayout(summary)

        self.month_budget = QProgressBar()
        self.month_budget.setRange(0, 100)
        self.month_budget.setFormat("Monthly budget used: %p%")
        root.addWidget(self.month_budget)

        tabs = QTabWidget()
        budget_page = QWidget()
        budget_layout = QVBoxLayout(budget_page)
        self.budget_table = QTableWidget(0, 4)
        self.budget_table.setHorizontalHeaderLabels(
            ["Budget", "Spend", "Limit", "Status"]
        )
        self._prepare_table(self.budget_table, stretch=True)
        budget_layout.addWidget(self.budget_table)
        tabs.addTab(budget_page, "Budgets & forecast")

        provider_page = QWidget()
        provider_layout = QVBoxLayout(provider_page)
        self.provider_table = QTableWidget(0, 11)
        self.provider_table.setHorizontalHeaderLabels(
            [
                "Provider",
                "Model",
                "Sessions",
                "Jobs",
                "Success",
                "Characters",
                "Total cost",
                "Retry cost",
                "Cost/file",
                "Files/min",
                "Chars/min",
            ]
        )
        self._prepare_table(self.provider_table)
        provider_layout.addWidget(self.provider_table)
        tabs.addTab(provider_page, "Provider efficiency")

        rates_page = QWidget()
        rates_layout = QVBoxLayout(rates_page)
        self.rate_table = QTableWidget(0, 7)
        self.rate_table.setHorizontalHeaderLabels(
            ["Scope", "Provider", "Model", "Price / 1M", "Currency", "Source", "Updated"]
        )
        self._prepare_table(self.rate_table)
        self.rate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        rates_layout.addWidget(self.rate_table)
        rate_actions = QHBoxLayout()
        for text, handler in (
            ("Add project rate", self.add_rate),
            ("Edit selected", self.edit_rate),
            ("Delete selected", self.delete_rate),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            rate_actions.addWidget(button)
        rate_actions.addStretch(1)
        rates_layout.addLayout(rate_actions)
        tabs.addTab(rates_page, "Pricing rates")

        sessions_page = QWidget()
        sessions_layout = QVBoxLayout(sessions_page)
        self.session_table = QTableWidget(0, 9)
        self.session_table.setHorizontalHeaderLabels(
            [
                "Recorded",
                "Session",
                "Provider",
                "Model",
                "Characters",
                "Retry chars",
                "Rate / 1M",
                "Estimated",
                "Actual/effective",
            ]
        )
        self._prepare_table(self.session_table)
        sessions_layout.addWidget(self.session_table)
        tabs.addTab(sessions_page, "Session costs")

        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["Created", "State", "Today", "Week", "Month", "Projected month", "Queue"]
        )
        self._prepare_table(self.history_table)
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
            ("Edit budget policy", self.edit_policy),
            ("Evaluate & save snapshot", self.evaluate),
            ("Export", self.export_dashboard),
            ("Refresh", self.refresh),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            actions.addWidget(button)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

    @staticmethod
    def _prepare_table(table: QTableWidget, *, stretch: bool = False) -> None:
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch if stretch else QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setStretchLastSection(True)

    @staticmethod
    def _metric_label(title: str, value: str) -> QLabel:
        label = QLabel(f"{title}\n{value}")
        label.setAlignment(Qt.AlignCenter)
        label.setProperty("metric_title", title)
        label.setStyleSheet(
            "QLabel{border:1px solid palette(mid);border-radius:6px;padding:10px;}"
        )
        return label

    @staticmethod
    def _set_metric(label: QLabel, value: str) -> None:
        label.setText(f"{label.property('metric_title')}\n{value}")

    def refresh(self) -> None:
        self.dashboard_data = self.service.dashboard(
            project_id=self.project_id,
            provider=self.provider,
            model=self.model,
        )
        dashboard = self.dashboard_data
        snapshot = dashboard.snapshot
        currency = snapshot.currency
        forecast = snapshot.queue_forecast
        self._set_metric(self.state_label, self._label(snapshot.state))
        self._set_metric(self.today_label, self._money(snapshot.daily_spend, currency))
        self._set_metric(self.month_label, self._money(snapshot.monthly_spend, currency))
        self._set_metric(self.retry_label, self._money(snapshot.retry_cost, currency))
        self._set_metric(
            self.queue_label,
            self._money(forecast.estimated_cost, currency) if forecast else "—",
        )
        self._set_metric(
            self.eta_label,
            format_duration(forecast.estimated_duration_seconds) if forecast else "—",
        )
        self.month_budget.setValue(
            max(0, min(100, round(snapshot.monthly_budget_usage_percent)))
        )
        self.reasons_label.setText(
            " · ".join(snapshot.reasons)
            if snapshot.reasons
            else "Configured budgets and queue-cost limits are within target."
        )
        self._populate_budgets(dashboard)
        self._populate_providers(dashboard)
        self._populate_rates(dashboard)
        self._populate_sessions(dashboard)
        self._populate_history(dashboard)
        forecast_text = (
            f"{forecast.queued_jobs} queued file(s), {forecast.queued_characters:,} "
            f"characters, {forecast.confidence} confidence"
            if forecast
            else "No queue forecast"
        )
        self.status_label.setText(forecast_text)

    def _populate_budgets(self, dashboard: GenerationCostCapacityDashboard) -> None:
        snapshot = dashboard.snapshot
        policy = dashboard.policy
        currency = policy.currency
        rows = (
            (
                "Daily",
                self._money(snapshot.daily_spend, currency),
                self._limit(policy.daily_budget, currency),
                dashboard.budget_status.get("daily", "—"),
            ),
            (
                "Weekly",
                self._money(snapshot.weekly_spend, currency),
                self._limit(policy.weekly_budget, currency),
                dashboard.budget_status.get("weekly", "—"),
            ),
            (
                "Monthly",
                self._money(snapshot.monthly_spend, currency),
                self._limit(policy.monthly_budget, currency),
                dashboard.budget_status.get("monthly", "—"),
            ),
            (
                "Projected month",
                self._money(snapshot.projected_monthly_cost, currency),
                self._limit(policy.monthly_budget, currency),
                (
                    "breached"
                    if policy.monthly_budget > 0
                    and snapshot.projected_monthly_cost > policy.monthly_budget
                    else "healthy"
                ),
            ),
            (
                "Queued work",
                self._money(
                    snapshot.queue_forecast.estimated_cost
                    if snapshot.queue_forecast is not None
                    else 0.0,
                    currency,
                ),
                self._limit(policy.max_queue_cost, currency),
                (
                    "breached"
                    if policy.max_queue_cost > 0
                    and snapshot.queue_forecast is not None
                    and snapshot.queue_forecast.estimated_cost > policy.max_queue_cost
                    else "healthy"
                ),
            ),
        )
        self.budget_table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.budget_table.setItem(
                    row,
                    column,
                    QTableWidgetItem(self._label(value) if column == 3 else value),
                )

    def _populate_providers(self, dashboard: GenerationCostCapacityDashboard) -> None:
        metrics = dashboard.snapshot.provider_metrics
        self.provider_table.setRowCount(len(metrics))
        for row, item in enumerate(metrics):
            values = (
                item.provider,
                item.model,
                str(item.session_count),
                str(item.total_jobs),
                f"{item.success_rate:.2f}%",
                f"{item.total_characters:,}",
                self._money(item.total_cost, dashboard.policy.currency),
                self._money(item.retry_cost, dashboard.policy.currency),
                self._money(item.cost_per_file, dashboard.policy.currency),
                f"{item.average_files_per_minute:.2f}",
                f"{item.average_characters_per_minute:.0f}",
            )
            for column, value in enumerate(values):
                self.provider_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_rates(self, dashboard: GenerationCostCapacityDashboard) -> None:
        rates = dashboard.rates
        self.rate_table.setRowCount(len(rates))
        for row, rate in enumerate(rates):
            values = (
                "Project" if rate.project_id is not None else "Global",
                rate.provider,
                rate.model,
                f"{rate.price_per_million_characters:.6f}",
                rate.currency,
                rate.source,
                self._short_timestamp(rate.updated_at),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, rate.rate_id)
                self.rate_table.setItem(row, column, item)

    def _populate_sessions(self, dashboard: GenerationCostCapacityDashboard) -> None:
        costs = dashboard.recent_costs
        self.session_table.setRowCount(len(costs))
        for row, cost in enumerate(costs):
            values = (
                self._short_timestamp(cost.recorded_at),
                cost.session_id[:12],
                cost.provider,
                cost.model,
                f"{cost.character_count:,}",
                f"{cost.retry_characters:,}",
                f"{cost.price_per_million_characters:.6f} {cost.currency}",
                self._money(cost.estimated_cost, cost.currency),
                self._money(cost.effective_cost, cost.currency),
            )
            for column, value in enumerate(values):
                self.session_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_history(self, dashboard: GenerationCostCapacityDashboard) -> None:
        history = dashboard.history
        self.history_table.setRowCount(len(history))
        for row, item in enumerate(history):
            queue_cost = item.queue_forecast.estimated_cost if item.queue_forecast else 0.0
            values = (
                self._short_timestamp(item.created_at),
                self._label(item.state),
                self._money(item.daily_spend, item.currency),
                self._money(item.weekly_spend, item.currency),
                self._money(item.monthly_spend, item.currency),
                self._money(item.projected_monthly_cost, item.currency),
                self._money(queue_cost, item.currency),
            )
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))

    def edit_policy(self) -> None:
        dialog = GenerationCostBudgetPolicyDialog(
            self.service,
            self.service.get_policy(self.project_id),
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            self.status_label.setText("Cost budget policy saved.")

    def add_rate(self) -> None:
        policy = self.service.get_policy(self.project_id)
        rate = GenerationPricingRate(
            rate_id=uuid.uuid4().hex,
            project_id=self.project_id,
            provider=self.provider or "elevenlabs",
            model=self.model or "*",
            currency=policy.currency,
        )
        dialog = GenerationPricingRateDialog(self.service, rate, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            self.status_label.setText("Pricing rate saved.")

    def edit_rate(self) -> None:
        rate = self._selected_rate()
        if rate is None:
            self.status_label.setText("Select one pricing row first.")
            return
        dialog = GenerationPricingRateDialog(self.service, rate, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            self.status_label.setText("Pricing rate updated.")

    def delete_rate(self) -> None:
        rate = self._selected_rate()
        if rate is None:
            self.status_label.setText("Select one pricing row first.")
            return
        answer = QMessageBox.question(
            self,
            "Delete pricing rate",
            f"Delete {rate.provider} / {rate.model}?",
        )
        if answer != QMessageBox.Yes:
            return
        self.service.delete_rate(rate.rate_id)
        self.refresh()
        self.status_label.setText("Pricing rate deleted.")

    def _selected_rate(self) -> GenerationPricingRate | None:
        row = self.rate_table.currentRow()
        if row < 0:
            selected = self.rate_table.selectionModel().selectedRows()
            row = selected[0].row() if selected else -1
        if row < 0 or self.dashboard_data is None:
            return None
        item = self.rate_table.item(row, 0)
        rate_id = str(item.data(Qt.UserRole)) if item is not None else ""
        return next(
            (rate for rate in self.dashboard_data.rates if rate.rate_id == rate_id),
            None,
        )

    def evaluate(self) -> None:
        snapshot = self.service.evaluate_and_persist(
            project_id=self.project_id,
            provider=self.provider,
            model=self.model,
        )
        self.refresh()
        self.status_label.setText(
            f"Snapshot {snapshot.snapshot_id[:8]} saved with state "
            f"{self._label(snapshot.state)}."
        )

    def export_dashboard(self) -> tuple[Path, Path] | None:
        if self.dashboard_data is None:
            return None
        json_path, csv_path = self.service.export(
            self.dashboard_data,
            self.export_dir,
            project_name=self.project_name,
        )
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}.")
        return json_path, csv_path

    @staticmethod
    def _money(value: float, currency: str) -> str:
        return f"{value:.4f} {currency}"

    @classmethod
    def _limit(cls, value: float, currency: str) -> str:
        return cls._money(value, currency) if value > 0 else "Not configured"

    @staticmethod
    def _label(value: object) -> str:
        return str(value or "—").replace("_", " ").title()

    @staticmethod
    def _short_timestamp(value: str) -> str:
        return value.replace("T", " ")[:19] if value else "—"
