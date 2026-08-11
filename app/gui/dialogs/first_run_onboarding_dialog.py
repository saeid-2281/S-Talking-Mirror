from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.first_run_onboarding import FirstRunOnboardingState
from app.services.first_run_onboarding_service import FirstRunOnboardingService


class FirstRunOnboardingDialog(QDialog):
    """Resumable first-run guidance with explicit user-controlled handoffs."""

    stateChanged = Signal(object)

    def __init__(
        self,
        service: FirstRunOnboardingService,
        parent: QWidget | None = None,
        *,
        actions: Mapping[str, Callable[[], object]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.actions = dict(actions or {})
        self.current_state: FirstRunOnboardingState | None = None
        self.setObjectName("firstRunOnboardingDialog")
        self.setWindowTitle("Getting Started — Roadmap 2 A2")
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Getting Started",
            "Roadmap 2 · Track A · Phase A2. A resumable first-run path through the existing production workflow. Opening onboarding never changes provider/account/voice/model, runs Preflight, or starts generation.",
            icon_name="settings",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard(
            "First-run guidance",
            "Progress is saved only when you explicitly mark a step reviewed.",
            tone="info",
        )
        self.workspace.add_body_widget(self.overall)

        section = DialogSection(
            "Six-step production orientation",
            "Select a step, open the related existing tool if useful, then mark the step reviewed. Tool actions are handoffs only; onboarding never applies provider or generation changes for you.",
        )
        self.step_table = QTableWidget(0, 5)
        self.step_table.setHorizontalHeaderLabels(
            ["Stage", "Step", "Status", "Why it matters", "Guided action"]
        )
        self.step_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.step_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.step_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.step_table.horizontalHeader().setStretchLastSection(True)
        self.step_table.itemSelectionChanged.connect(self._update_action_state)
        section.add_widget(self.step_table)
        self.workspace.add_body_widget(section)

        controls = QHBoxLayout()
        self.open_tool_button = QPushButton("Open selected tool")
        self.open_tool_button.clicked.connect(self.open_selected_tool)
        controls.addWidget(self.open_tool_button)

        self.reviewed_button = QPushButton("Mark reviewed")
        self.reviewed_button.clicked.connect(self.mark_selected_reviewed)
        controls.addWidget(self.reviewed_button)

        self.undo_button = QPushButton("Mark incomplete")
        self.undo_button.clicked.connect(self.mark_selected_incomplete)
        controls.addWidget(self.undo_button)

        self.reset_button = QPushButton("Reset progress")
        self.reset_button.clicked.connect(self.reset_progress)
        controls.addWidget(self.reset_button)

        controls.addStretch(1)

        self.finish_button = QPushButton("Complete onboarding")
        self.finish_button.setDefault(True)
        self.finish_button.clicked.connect(self.complete_onboarding)
        controls.addWidget(self.finish_button)

        close = QPushButton("Finish later")
        close.clicked.connect(self.close)
        controls.addWidget(close)
        self.workspace.footer_layout.addLayout(controls)

    def refresh_view(self) -> None:
        state = self.service.load_state()
        self.current_state = state
        completed, total, percent = self.service.progress(state)
        if state.first_run_completed:
            tone = "success"
            title = "ONBOARDING COMPLETE"
            detail = f"{completed}/{total} steps reviewed · {percent}% · You can revisit or reset this guide at any time."
        else:
            tone = "info" if completed == 0 else "warning"
            title = "GETTING STARTED"
            detail = f"{completed}/{total} steps reviewed · {percent}% · Your production choices remain unchanged until you act in their existing tools."
        self.overall.update_status(title, detail, tone=tone)

        completed_ids = set(state.completed_steps)
        steps = self.service.steps()
        self.step_table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            values = (
                step.stage,
                step.title,
                "Reviewed" if step.step_id in completed_ids else "To review",
                step.description,
                step.action_label,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(256, step.step_id)
                self.step_table.setItem(row, column, item)
        self.step_table.resizeColumnsToContents()
        if self.step_table.rowCount() and self.step_table.currentRow() < 0:
            self.step_table.selectRow(0)
        self.finish_button.setEnabled(
            self.service.all_required_steps_complete(state.completed_steps)
            and not state.first_run_completed
        )
        self._update_action_state()
        self.stateChanged.emit(state)

    def selected_step_id(self) -> str:
        row = self.step_table.currentRow()
        if row < 0:
            return ""
        item = self.step_table.item(row, 0)
        return str(item.data(256) or "") if item else ""

    def _selected_step(self):
        selected = self.selected_step_id()
        return next((step for step in self.service.steps() if step.step_id == selected), None)

    def _update_action_state(self) -> None:
        step = self._selected_step()
        state = self.current_state or self.service.load_state()
        completed = set(state.completed_steps)
        self.open_tool_button.setEnabled(bool(step and step.action_id in self.actions))
        self.reviewed_button.setEnabled(bool(step and step.step_id not in completed))
        self.undo_button.setEnabled(bool(step and step.step_id in completed))

    def open_selected_tool(self) -> None:
        step = self._selected_step()
        if step is None:
            return
        action = self.actions.get(step.action_id)
        if action is None:
            QMessageBox.information(
                self,
                "Guided action unavailable",
                "This onboarding step has no connected product action in the current window.",
            )
            return
        action()

    def mark_selected_reviewed(self) -> None:
        step_id = self.selected_step_id()
        if not step_id:
            return
        self.service.mark_step_complete(step_id)
        self.refresh_view()

    def mark_selected_incomplete(self) -> None:
        step_id = self.selected_step_id()
        if not step_id:
            return
        self.service.mark_step_incomplete(step_id)
        self.refresh_view()

    def complete_onboarding(self) -> None:
        try:
            state = self.service.complete_onboarding()
        except ValueError as exc:
            QMessageBox.information(self, "Onboarding is not complete", str(exc))
            return
        self.current_state = state
        self.stateChanged.emit(state)
        QMessageBox.information(
            self,
            "Getting Started complete",
            "First-run onboarding is complete. S-Talking did not change provider, account, voice/model, Preflight or generation state as part of this guide.",
        )
        self.refresh_view()

    def reset_progress(self) -> None:
        if QMessageBox.question(
            self,
            "Reset onboarding progress?",
            "Reset only the Getting Started checklist? Provider, project and generation settings are not changed.",
        ) != QMessageBox.Yes:
            return
        self.service.reset_progress()
        self.refresh_view()
