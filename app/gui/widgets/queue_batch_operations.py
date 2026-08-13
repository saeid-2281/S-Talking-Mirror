from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget

from app.models.queue_batch_operations import QueueBatchSnapshot


class QueueBatchOperationsWidget(QFrame):
    lensRequested = Signal(str)
    lensChanged = Signal(str)
    groupChanged = Signal(str)
    useSelectionRequested = Signal()
    actionRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("queueScopeSummary")
        self._compact = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        title = QLabel("Batch plan")
        title.setObjectName("queueCommandSectionLabel")
        self.lens = QComboBox()
        for label, code in (
            ("All visible", "all"),
            ("Pending", "pending"),
            ("Failed", "failed"),
            ("Current selection", "selected"),
            ("Quota-ready", "quota"),
        ):
            self.lens.addItem(label, code)
        self.lens.setAccessibleName("Queue batch lens")
        self.lens.currentIndexChanged.connect(self._lens_changed)

        self.select_button = QPushButton("Select preview rows")
        self.select_button.setObjectName("queueSecondaryAction")
        self.select_button.clicked.connect(self._emit_lens)

        self.scope_button = QPushButton("Use selection as scope")
        self.scope_button.setObjectName("queueSecondaryAction")
        self.scope_button.clicked.connect(self.useSelectionRequested)

        self.group_by = QComboBox()
        self.group_by.addItem("Group: Status", "status")
        self.group_by.addItem("Group: Provider", "provider")
        self.group_by.addItem("Group: Voice", "voice")
        self.group_by.setAccessibleName("Queue grouping lens")
        self.group_by.currentIndexChanged.connect(self._group_changed)

        self.summary = QLabel("No queue jobs")
        self.summary.setObjectName("queueVisibleSummary")
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.plan_preview = QLabel(
            "Plan preview · choose a lens to inspect rows before changing generation scope."
        )
        self.plan_preview.setObjectName("queueBatchPlanPreview")
        self.plan_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.plan_preview.setToolTip(
            "Lens preview and row selection never run Preflight or start generation."
        )

        self.bulk = QToolButton()
        self.bulk.setText("Bulk actions")
        self.bulk.setPopupMode(QToolButton.InstantPopup)
        self.bulk.setAccessibleName("Queue bulk actions")
        menu = QMenu(self.bulk)
        self.bulk_actions = {}
        for label, code in (
            ("Retry failed", "retry_failed"),
            ("Skip selected", "skip_selected"),
            ("Reset selected", "reset_selected"),
            ("Clear completed", "clear_completed"),
        ):
            action = menu.addAction(label)
            self.bulk_actions[code] = action
            action.triggered.connect(
                lambda _checked=False, value=code: self.actionRequested.emit(value)
            )
        self.bulk.setMenu(menu)

        layout.addWidget(title)
        layout.addWidget(self.lens)
        layout.addWidget(self.select_button)
        layout.addWidget(self.scope_button)
        layout.addWidget(self.group_by)
        summary_stack = QVBoxLayout()
        summary_stack.setContentsMargins(0, 0, 0, 0)
        summary_stack.setSpacing(1)
        summary_stack.addWidget(self.summary)
        summary_stack.addWidget(self.plan_preview)
        layout.addLayout(summary_stack, 1)
        layout.addWidget(self.bulk)

    def update_snapshot(self, snapshot: QueueBatchSnapshot) -> None:
        groups = " · ".join(
            f"{group.label} {group.job_count:,}"
            for group in snapshot.groups[:3]
        )
        suffix = f" · {groups}" if groups else ""
        self.summary.setText(snapshot.summary + suffix)
        self.summary.setToolTip(
            "Grouping is analytical only; it never changes queue or execution order."
        )
        self.plan_preview.setText(
            f"Plan preview · {snapshot.lens_summary} · "
            "Select preview rows first; generation scope changes only with Use selection as scope."
        )
        self.scope_button.setEnabled(snapshot.selected_jobs > 0)
        self.scope_button.setToolTip(
            (
                f"Set generation scope to the current {snapshot.selected_jobs:,} selected job(s). "
                "This invalidates Preflight but does not run it or start generation."
                if snapshot.selected_jobs
                else "Select queue rows before using selection as generation scope."
            )
        )
        self.bulk_actions["retry_failed"].setEnabled(snapshot.failed_jobs > 0)
        self.bulk_actions["skip_selected"].setEnabled(snapshot.selected_jobs > 0)
        self.bulk_actions["reset_selected"].setEnabled(snapshot.selected_jobs > 0)
        self.bulk_actions["clear_completed"].setEnabled(snapshot.completed_jobs > 0)
        quota_index = self.lens.findData("quota")
        if quota_index >= 0:
            self.lens.model().item(quota_index).setEnabled(snapshot.quota_jobs > 0)

    def set_compact_mode(self, compact: bool) -> None:
        self._compact = bool(compact)
        self.setVisible(not self._compact)
        self.setMaximumHeight(44 if not self._compact else 0)

    def focus_lens(self) -> None:
        if self._compact:
            self.setVisible(True)
            self.setMaximumHeight(44)
        self.lens.setFocus(Qt.ShortcutFocusReason)

    def _emit_lens(self) -> None:
        self.lensRequested.emit(str(self.lens.currentData() or "all"))

    def _lens_changed(self) -> None:
        self.lensChanged.emit(str(self.lens.currentData() or "all"))

    def _group_changed(self) -> None:
        self.groupChanged.emit(str(self.group_by.currentData() or "status"))
