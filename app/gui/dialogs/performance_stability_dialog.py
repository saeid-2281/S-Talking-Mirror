from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.performance_stability_service import PerformanceStabilityService


class PerformanceStabilityDialog(QDialog):
    """Inspect bounded performance evidence and manage long-run observations."""

    def __init__(
        self,
        service: PerformanceStabilityService,
        parent: QWidget | None = None,
        *,
        queue_state=None,
        open_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.queue_state = queue_state
        self.open_path = open_path
        self.current_snapshot = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("performanceStabilityDialog")
        self.setWindowTitle("Performance and long-run stability")
        self.resize(1180, 780)
        self.setMinimumSize(900, 620)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Performance and long-run stability",
            "Measure startup, working set, threads, Qt objects and long-run growth using bounded process counters only—never project text or credentials.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting performance evidence", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        metrics_section = DialogSection(
            "Current process metrics",
            "A low-overhead sample of the current process. Python heap appears when a managed observation enables tracemalloc.",
        )
        self.metrics_table = QTableWidget(0, 3)
        self.metrics_table.setObjectName("performanceStabilityMetricsTable")
        self.metrics_table.setHorizontalHeaderLabels(["Metric", "Value", "Budget context"])
        self.metrics_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.metrics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        metrics_section.add_widget(self.metrics_table)
        self.workspace.add_body_widget(metrics_section)

        gate_section = DialogSection(
            "Performance budgets",
            "Warnings identify capacity pressure. Blockers identify values that should be resolved before a stable production release.",
        )
        self.gate_table = QTableWidget(0, 5)
        self.gate_table.setObjectName("performanceStabilityGateTable")
        self.gate_table.setHorizontalHeaderLabels(["Status", "Gate", "Severity", "Evidence", "Action"])
        self.gate_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.gate_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        gate_section.add_widget(self.gate_table)
        self.workspace.add_body_widget(gate_section)

        run_section = DialogSection(
            "Observation history",
            "Start an observation before a long generation or idle soak. Background samples are bounded by the configured retention limit.",
        )
        self.run_table = QTableWidget(0, 8)
        self.run_table.setObjectName("performanceStabilityRunTable")
        self.run_table.setHorizontalHeaderLabels(
            ["Status", "Label", "Started", "Duration", "Samples", "Peak RSS", "RSS growth", "Growth/hour"]
        )
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.run_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        run_section.add_widget(self.run_table)
        self.workspace.add_body_widget(run_section)

        sample_section = DialogSection(
            "Recent samples",
            "Only process counters, queue size and generation state are stored. Labels are sanitized and capped.",
        )
        self.sample_table = QTableWidget(0, 8)
        self.sample_table.setObjectName("performanceStabilitySampleTable")
        self.sample_table.setHorizontalHeaderLabels(
            ["Time", "Label", "RSS", "Python heap", "Threads", "Qt widgets", "Handles", "Queue"]
        )
        self.sample_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sample_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        sample_section.add_widget(self.sample_table)
        self.workspace.add_body_widget(sample_section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        buttons = (
            ("Refresh", self.refresh, "general.refresh", False),
            ("Capture sample", self.capture_sample, "report", False),
            ("Start observation", self.start_observation, "general.success", True),
            ("Finish observation", self.finish_observation, "generation.stop", False),
            ("Export JSON and CSV", self.export_snapshot, "save", False),
            ("Open evidence folder", self.open_evidence_folder, "project.output_folder", False),
        )
        for text, handler, icon_name, primary in buttons:
            button = QPushButton(text)
            button.setIcon(action_icon(icon_name))
            button.clicked.connect(handler)
            if primary:
                button.setObjectName("dialogPrimaryAction")
            self.workspace.add_footer_widget(button)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close)

    def _queue_values(self) -> tuple[int, bool]:
        if callable(self.queue_state):
            try:
                payload = self.queue_state() or {}
                return max(0, int(payload.get("queue_total", 0))), bool(payload.get("generation_active", False))
            except (TypeError, ValueError):
                return 0, False
        return 0, False

    def refresh(self) -> None:
        queue_total, active = self._queue_values()
        snapshot = self.service.snapshot(queue_total=queue_total, generation_active=active)
        self.current_snapshot = snapshot
        tone = "error" if snapshot.status == "blocked" else "warning" if snapshot.status == "attention" else "success"
        self.summary.update_status(
            snapshot.summary,
            (
                f"RSS {self._mb(snapshot.current_sample.rss_bytes)} · "
                f"{snapshot.current_sample.process_thread_count} thread(s) · "
                f"{snapshot.current_sample.qt_widget_count} Qt widget(s) · "
                f"startup {self._startup(snapshot.current_sample.startup_elapsed_ms)}"
            ),
            tone=tone,
        )
        policy = snapshot.policy
        metric_rows = [
            ("Startup", self._startup(snapshot.current_sample.startup_elapsed_ms), f"warn {policy.startup_warning_ms} ms"),
            ("Working set", self._mb(snapshot.current_sample.rss_bytes), f"warn {policy.rss_warning_mb} MB"),
            ("Python traced heap", self._mb(snapshot.current_sample.python_heap_bytes), f"warn {policy.python_heap_warning_mb} MB"),
            ("Process threads", str(snapshot.current_sample.process_thread_count), f"warn {policy.process_thread_warning}"),
            ("Qt active threads", str(snapshot.current_sample.qt_active_thread_count), "global Qt thread pool"),
            ("Qt widgets", str(snapshot.current_sample.qt_widget_count), f"warn {policy.qt_widget_warning}"),
            ("Top-level widgets", str(snapshot.current_sample.qt_top_level_count), "current QApplication"),
            ("Process handles", str(snapshot.current_sample.process_handle_count or "not measured"), f"warn {policy.handle_warning}"),
            ("GC-tracked objects", str(snapshot.current_sample.gc_object_count), "diagnostic counter"),
        ]
        self.metrics_table.setRowCount(len(metric_rows))
        for row, values in enumerate(metric_rows):
            for column, value in enumerate(values):
                self.metrics_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.metrics_table.resizeColumnsToContents()

        self.gate_table.setRowCount(len(snapshot.gates))
        for row, gate in enumerate(snapshot.gates):
            values = (gate.status.replace("_", " ").title(), gate.label, gate.severity.title(), gate.detail, gate.remediation or "—")
            for column, value in enumerate(values):
                self.gate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.gate_table.resizeColumnsToContents()

        self.run_table.setRowCount(len(snapshot.runs))
        for row, run in enumerate(snapshot.runs):
            values = (
                run.status.title(),
                run.label,
                run.started_at,
                f"{run.duration_seconds:.1f} s",
                str(run.sample_count),
                self._mb(run.peak_rss_bytes),
                self._signed_mb(run.rss_growth_bytes),
                f"{run.growth_mb_per_hour:.2f} MB/h",
            )
            for column, value in enumerate(values):
                self.run_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.run_table.resizeColumnsToContents()

        samples = list(reversed(snapshot.recent_samples[-30:]))
        self.sample_table.setRowCount(len(samples))
        for row, sample in enumerate(samples):
            values = (
                sample.captured_at,
                sample.label,
                self._mb(sample.rss_bytes),
                self._mb(sample.python_heap_bytes),
                str(sample.process_thread_count),
                str(sample.qt_widget_count),
                str(sample.process_handle_count or "—"),
                f"{sample.queue_total}{' active' if sample.generation_active else ''}",
            )
            for column, value in enumerate(values):
                self.sample_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.sample_table.resizeColumnsToContents()
        observation = snapshot.active_run_label or "none"
        self.status_label.setText(
            f"Background sampling {'enabled' if snapshot.background_sampling_enabled else 'disabled'} · "
            f"interval {policy.sample_interval_seconds}s · active observation: {observation}"
        )

    def capture_sample(self):
        queue_total, active = self._queue_values()
        sample = self.service.collect_sample(
            label="manual-ui",
            queue_total=queue_total,
            generation_active=active,
        )
        self.refresh()
        self.status_label.setText(f"Captured sample at {sample.captured_at}")
        return sample

    def start_observation(self) -> str:
        run_id = self.service.start_observation("manual UI observation")
        self.refresh()
        self.status_label.setText(f"Observation started: {run_id}")
        return run_id

    def finish_observation(self):
        run = self.service.finish_observation()
        self.refresh()
        if run is None:
            self.status_label.setText("No active observation to finish.")
        else:
            self.status_label.setText(f"Observation finished: {run.run_id}")
        return run

    def export_snapshot(self) -> tuple[Path, Path]:
        json_path, csv_path = self.service.export_snapshot()
        self.status_label.setText(f"Exported {json_path.name} and {csv_path.name}")
        if callable(self.open_path):
            self.open_path(json_path.parent)
        return json_path, csv_path

    def open_evidence_folder(self) -> None:
        if callable(self.open_path):
            self.open_path(self.service.root)
        self.status_label.setText(str(self.service.root))

    @staticmethod
    def _mb(value: int) -> str:
        if not value:
            return "not measured"
        return f"{value / 1024**2:.1f} MB"

    @staticmethod
    def _signed_mb(value: int) -> str:
        return f"{value / 1024**2:+.1f} MB"

    @staticmethod
    def _startup(value: int | None) -> str:
        return "not measured" if value is None else f"{value} ms"
