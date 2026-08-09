from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.models.generation_live_operations import GenerationLiveSnapshot
from app.services.monitor_formatting import format_duration


class GenerationLiveOperationsWidget(QFrame):
    pauseRequested = Signal()
    stopRequested = Signal()
    retryRequested = Signal()
    outputRequested = Signal()
    failureReviewRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("monitorProgressCard")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(7)

        heading = QHBoxLayout()
        title = QLabel("Run focus")
        title.setObjectName("monitorSectionTitle")
        self.state_badge = QLabel("Ready")
        self.state_badge.setObjectName("monitorStatusBadge")
        self.state_badge.setAlignment(Qt.AlignCenter)
        self.state_badge.setProperty("tone", "success")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.state_badge)
        root.addLayout(heading)

        self.progress_label = QLabel("No active queue")
        self.progress_label.setObjectName("monitorPercent")
        self.progress_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.progress_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.current_label = QLabel("Current: —")
        self.current_label.setObjectName("monitorMetricValue")
        self.current_label.setWordWrap(True)
        self.timing_label = QLabel("ETA: —")
        self.timing_label.setObjectName("monitorMetricValue")
        self.failure_label = QLabel("Failures: 0")
        self.failure_label.setObjectName("monitorMetricValue")
        self.run_label = QLabel("Run: —")
        self.run_label.setObjectName("monitorMetricValue")
        grid.addWidget(self.current_label, 0, 0, 1, 2)
        grid.addWidget(self.timing_label, 1, 0)
        grid.addWidget(self.failure_label, 1, 1)
        grid.addWidget(self.run_label, 2, 0, 1, 2)
        root.addLayout(grid)

        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(6)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("monitorPrimaryAction")
        self.stop_button = QPushButton("Stop")
        self.retry_button = QPushButton("Retry transient")
        self.output_button = QPushButton("Open latest output")
        self.failures_button = QPushButton("Review failures")
        for button in (self.stop_button, self.retry_button, self.output_button, self.failures_button):
            button.setObjectName("queueSecondaryAction")
        self.pause_button.clicked.connect(self.pauseRequested)
        self.stop_button.clicked.connect(self.stopRequested)
        self.retry_button.clicked.connect(self.retryRequested)
        self.output_button.clicked.connect(self.outputRequested)
        self.failures_button.clicked.connect(self.failureReviewRequested)
        actions.addWidget(self.pause_button, 0, 0)
        actions.addWidget(self.stop_button, 0, 1)
        actions.addWidget(self.retry_button, 1, 0)
        actions.addWidget(self.failures_button, 1, 1)
        actions.addWidget(self.output_button, 2, 0, 1, 2)
        root.addLayout(actions)

    def update_snapshot(self, snapshot: GenerationLiveSnapshot) -> None:
        self.state_badge.setText(snapshot.state)
        self.state_badge.setProperty("tone", self._tone(snapshot.state))
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)

        self.progress_label.setText(
            f"{snapshot.progress_text} · Completed {snapshot.completed:,} · "
            f"Pending {snapshot.pending:,} · Failed {snapshot.failed:,}"
        )
        current = Path(snapshot.current_filename).name if snapshot.current_filename else "—"
        self.current_label.setText(f"Current: {current}")
        self.current_label.setToolTip(snapshot.current_filename)
        eta = format_duration(snapshot.eta_seconds) if snapshot.eta_seconds > 0 else "—"
        average = format_duration(snapshot.average_seconds, empty_zero=True)
        confidence = snapshot.eta_confidence.title()
        self.timing_label.setText(f"ETA: {eta} · confidence {confidence} · avg {average}")
        self.failure_label.setText(
            f"Failures: {snapshot.failed:,} · retryable {snapshot.retryable_failed:,} · retries {snapshot.retries:,}"
        )
        self.run_label.setText(f"Run: {snapshot.run_id or '—'}")
        self.run_label.setToolTip(snapshot.run_id)

        self.pause_button.setText("Resume" if snapshot.paused else "Pause")
        self.pause_button.setEnabled(snapshot.can_pause)
        self.stop_button.setEnabled(snapshot.can_stop)
        self.retry_button.setEnabled(snapshot.can_retry)
        self.failures_button.setEnabled(snapshot.can_review_failures)
        self.output_button.setEnabled(snapshot.can_open_output)
        self.output_button.setToolTip(snapshot.latest_output)

    def focus_primary_action(self) -> None:
        for button in (
            self.pause_button,
            self.retry_button,
            self.output_button,
            self.failures_button,
            self.stop_button,
        ):
            if button.isEnabled():
                button.setFocus(Qt.ShortcutFocusReason)
                return
        self.setFocus(Qt.ShortcutFocusReason)

    @staticmethod
    def _tone(state: str) -> str:
        lowered = state.casefold()
        if "attention" in lowered or "fail" in lowered:
            return "error"
        if "pause" in lowered or "stop" in lowered:
            return "warning"
        if "run" in lowered:
            return "running"
        if "complete" in lowered or "ready" in lowered:
            return "success"
        return "info"
