from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_planning import BatchGenerationPlan
from app.services.monitor_formatting import format_duration


class PlanMetricCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchPlanMetricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("batchPlanMetricTitle")
        self.value_label = QLabel("—")
        self.value_label.setObjectName("batchPlanMetricValue")
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("batchPlanMetricDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def update_metric(self, value: str, detail: str = "", tone: str = "neutral") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class BatchPlanSummary(QWidget):
    """Decision-ready cost, capacity, quota and retry scenario summary."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batchPlanSummary")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        metrics = QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(8)
        metrics.setVerticalSpacing(8)
        self.scope_card = PlanMetricCard("Scope")
        self.cost_card = PlanMetricCard("Estimated cost")
        self.time_card = PlanMetricCard("Estimated time")
        self.quota_card = PlanMetricCard("Quota")
        self.budget_card = PlanMetricCard("Queue budget")
        self.risk_card = PlanMetricCard("Plan risk")
        for index, card in enumerate(
            [self.scope_card, self.cost_card, self.time_card, self.quota_card, self.budget_card, self.risk_card]
        ):
            metrics.addWidget(card, index // 3, index % 3)
            metrics.setColumnStretch(index % 3, 1)
        root.addLayout(metrics)

        reason_frame = QFrame()
        reason_frame.setObjectName("batchPlanReasonCard")
        reason_layout = QHBoxLayout(reason_frame)
        reason_layout.setContentsMargins(10, 7, 10, 7)
        self.reason_label = QLabel("Plan details are unavailable.")
        self.reason_label.setObjectName("batchPlanReason")
        self.reason_label.setWordWrap(True)
        reason_layout.addWidget(self.reason_label, 1)
        root.addWidget(reason_frame)

        self.scenario_table = QTableWidget(0, 6)
        self.scenario_table.setObjectName("batchPlanScenarioTable")
        self.scenario_table.setHorizontalHeaderLabels(
            ["Scenario", "Retry reserve", "Characters", "Requests", "Time", "Cost"]
        )
        self.scenario_table.horizontalHeader().setStretchLastSection(True)
        self.scenario_table.setAlternatingRowColors(True)
        self.scenario_table.setShowGrid(False)
        self.scenario_table.setSelectionMode(QTableWidget.NoSelection)
        self.scenario_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.scenario_table.setMinimumHeight(132)
        root.addWidget(self.scenario_table)

    def set_plan(self, plan: BatchGenerationPlan | None) -> None:
        if plan is None:
            self._set_unavailable()
            return
        self.scope_card.update_metric(
            f"{plan.files:,} files",
            f"{plan.characters:,} characters · {plan.provider_requests:,} requests",
        )
        if plan.cost_available:
            self.cost_card.update_metric(
                f"{plan.currency} {plan.estimated_cost:,.4f}",
                f"{plan.currency} {plan.price_per_million_characters:,.2f} / 1M chars · {plan.pricing_source}",
            )
        else:
            self.cost_card.update_metric("Unavailable", "Configure a provider pricing rate.", "warning")

        completion = self._completion_text(plan.estimated_completion_at)
        self.time_card.update_metric(
            format_duration(plan.estimated_duration_seconds),
            f"{completion} · {plan.throughput_confidence.title()} confidence · {plan.historical_session_count} sessions",
            "warning" if plan.throughput_confidence == "low" else "neutral",
        )
        if plan.provider != "elevenlabs":
            self.quota_card.update_metric("Not tracked", "This provider has no character quota snapshot.")
        elif plan.quota_remaining is None:
            self.quota_card.update_metric("Unknown", "Refresh provider account data.", "warning")
        elif plan.quota_shortfall:
            self.quota_card.update_metric(
                f"Short {plan.quota_shortfall:,}",
                f"{plan.quota_remaining:,} characters currently available",
                "error",
            )
        else:
            usage = f"{plan.quota_usage_percent:.1f}%" if plan.quota_usage_percent is not None else "—"
            tone = "warning" if (plan.quota_usage_percent or 0) >= 80 else "success"
            self.quota_card.update_metric(
                f"{plan.quota_remaining:,} available",
                f"Batch uses {usage} of available quota",
                tone,
            )

        if plan.max_queue_cost > 0 and plan.budget_usage_percent is not None:
            usage = plan.budget_usage_percent
            tone = "error" if usage > 100 else "warning" if usage >= 80 else "success"
            self.budget_card.update_metric(
                f"{usage:.1f}%",
                f"Limit {plan.currency} {plan.max_queue_cost:,.2f}",
                tone,
            )
        elif plan.max_queue_cost > 0:
            self.budget_card.update_metric(
                "Unknown",
                f"Limit {plan.currency} {plan.max_queue_cost:,.2f} · pricing unavailable",
                "warning",
            )
        else:
            self.budget_card.update_metric("No limit", "Configure a maximum queue cost if needed.")

        risk_tone = {"high": "error", "medium": "warning", "low": "success"}.get(plan.risk_level, "neutral")
        self.risk_card.update_metric(plan.risk_level.title(), f"Limiting factor: {plan.limiting_factor}", risk_tone)
        self.reason_label.setText(" · ".join(plan.reasons))
        self.reason_label.setProperty("tone", risk_tone)
        self.reason_label.style().unpolish(self.reason_label)
        self.reason_label.style().polish(self.reason_label)

        self.scenario_table.setRowCount(len(plan.scenarios))
        for row, scenario in enumerate(plan.scenarios):
            cost = f"{plan.currency} {scenario.estimated_cost:,.4f}" if plan.cost_available else "Unavailable"
            values = [
                scenario.label,
                f"{scenario.retry_reserve_percent}%",
                f"{scenario.characters:,}",
                f"{scenario.provider_requests:,}",
                format_duration(scenario.estimated_duration_seconds),
                cost,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.scenario_table.setItem(row, column, item)

    def _set_unavailable(self) -> None:
        for card in (self.scope_card, self.cost_card, self.time_card, self.quota_card, self.budget_card, self.risk_card):
            card.update_metric("—", "Run preflight to calculate this value.")
        self.reason_label.setText("Plan details are unavailable.")
        self.scenario_table.setRowCount(0)

    @staticmethod
    def _completion_text(value: str | None) -> str:
        if not value:
            return "Completion time unavailable"
        try:
            parsed = datetime.fromisoformat(value)
            return f"Complete around {parsed.astimezone().strftime('%H:%M')}"
        except (TypeError, ValueError):
            return "Completion time unavailable"
