from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_performance import (
    GenerationPerformanceBudget,
    GenerationPerformanceThresholds,
)


class PerformanceBudgetDialog(QDialog):
    """Edit project or global performance-regression thresholds."""

    def __init__(
        self,
        budget: GenerationPerformanceBudget,
        parent: QWidget | None = None,
        *,
        scope_label: str = "Global defaults",
    ) -> None:
        super().__init__(parent)
        self._source_budget = budget
        self.setWindowTitle("Performance budgets")
        self.resize(520, 620)
        root = QVBoxLayout(self)
        description = QLabel(
            f"Scope: {scope_label}. Warning and critical values control future "
            "regression analysis; existing sessions can be recalculated from history."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        form = QFormLayout()
        self.enabled = QCheckBox("Emit performance alerts")
        self.enabled.setChecked(budget.enabled)
        form.addRow("Alerts", self.enabled)
        self.minimum_sessions = self._integer(1, 50, budget.thresholds.minimum_baseline_sessions)
        self.window_size = self._integer(1, 100, budget.thresholds.baseline_window_size)
        self.cooldown = self._integer(0, 10080, budget.alert_cooldown_minutes, " min")
        form.addRow("Minimum baseline sessions", self.minimum_sessions)
        form.addRow("Baseline window", self.window_size)
        form.addRow("Duplicate-alert cooldown", self.cooldown)

        self.throughput_warning = self._percent(budget.thresholds.throughput_drop_warning)
        self.throughput_critical = self._percent(budget.thresholds.throughput_drop_critical)
        self.elapsed_warning = self._percent(budget.thresholds.elapsed_increase_warning)
        self.elapsed_critical = self._percent(budget.thresholds.elapsed_increase_critical)
        self.completion_warning = self._points(budget.thresholds.completion_drop_warning)
        self.completion_critical = self._points(budget.thresholds.completion_drop_critical)
        self.failure_warning = self._points(budget.thresholds.failure_rate_increase_warning)
        self.failure_critical = self._points(budget.thresholds.failure_rate_increase_critical)
        self.retry_warning = self._points(budget.thresholds.retry_rate_increase_warning)
        self.retry_critical = self._points(budget.thresholds.retry_rate_increase_critical)

        form.addRow("Throughput drop warning", self.throughput_warning)
        form.addRow("Throughput drop critical", self.throughput_critical)
        form.addRow("Seconds/job increase warning", self.elapsed_warning)
        form.addRow("Seconds/job increase critical", self.elapsed_critical)
        form.addRow("Completion drop warning", self.completion_warning)
        form.addRow("Completion drop critical", self.completion_critical)
        form.addRow("Failure increase warning", self.failure_warning)
        form.addRow("Failure increase critical", self.failure_critical)
        form.addRow("Retries/100 increase warning", self.retry_warning)
        form.addRow("Retries/100 increase critical", self.retry_critical)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def budget(self) -> GenerationPerformanceBudget:
        warning_throughput = self.throughput_warning.value() / 100.0
        warning_elapsed = self.elapsed_warning.value() / 100.0
        thresholds = GenerationPerformanceThresholds(
            minimum_baseline_sessions=self.minimum_sessions.value(),
            baseline_window_size=max(self.window_size.value(), self.minimum_sessions.value()),
            throughput_drop_warning=warning_throughput,
            throughput_drop_critical=max(
                warning_throughput,
                self.throughput_critical.value() / 100.0,
            ),
            elapsed_increase_warning=warning_elapsed,
            elapsed_increase_critical=max(
                warning_elapsed,
                self.elapsed_critical.value() / 100.0,
            ),
            completion_drop_warning=self.completion_warning.value(),
            completion_drop_critical=max(
                self.completion_warning.value(),
                self.completion_critical.value(),
            ),
            failure_rate_increase_warning=self.failure_warning.value(),
            failure_rate_increase_critical=max(
                self.failure_warning.value(),
                self.failure_critical.value(),
            ),
            retry_rate_increase_warning=self.retry_warning.value(),
            retry_rate_increase_critical=max(
                self.retry_warning.value(),
                self.retry_critical.value(),
            ),
        )
        return replace(
            self._source_budget,
            enabled=self.enabled.isChecked(),
            thresholds=thresholds,
            alert_cooldown_minutes=self.cooldown.value(),
        )

    @staticmethod
    def _integer(minimum: int, maximum: int, value: int, suffix: str = "") -> QSpinBox:
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(int(value))
        control.setSuffix(suffix)
        return control

    @staticmethod
    def _percent(value: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(0.0, 1000.0)
        control.setDecimals(1)
        control.setSingleStep(5.0)
        control.setSuffix(" %")
        control.setValue(float(value) * 100.0)
        return control

    @staticmethod
    def _points(value: float) -> QDoubleSpinBox:
        control = QDoubleSpinBox()
        control.setRange(0.0, 100.0)
        control.setDecimals(1)
        control.setSingleStep(1.0)
        control.setSuffix(" pt")
        control.setValue(float(value))
        return control
