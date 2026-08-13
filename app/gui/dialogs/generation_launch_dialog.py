from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.batch_plan_summary import BatchPlanSummary
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.domain import AppSettings
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmation


class GenerationLaunchDialog(QDialog):
    """Focused review surface for the final irreversible launch decision."""

    def __init__(
        self,
        confirmation: GenerationConfirmation,
        state: PreflightState,
        parent: QWidget | None = None,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.confirmation = confirmation
        self.state = state
        self.settings = settings
        self.acknowledgement_boxes: dict[str, QCheckBox] = {}
        self.setObjectName("generationLaunchDialog")
        self.setWindowTitle("Generation launch review")
        self.resize(920, 680)
        self.setMinimumSize(680, 480)
        self._build()
        self.render()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.workspace = DialogWorkspace(
            "Generation launch review",
            "Confirm the exact scope, provider impact and file-policy decisions before the batch starts.",
            icon_name="generation.start",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.status_card = DialogStatusCard("Review required", "", tone="warning")
        self.status_card.setObjectName("generationLaunchStatusCard")
        self.workspace.add_body_widget(self.status_card)

        self.readiness_card = DialogStatusCard(
            "Current explicit Preflight",
            "",
            tone="info",
        )
        self.readiness_card.setObjectName("generationLaunchReadinessSnapshot")
        self.workspace.add_body_widget(self.readiness_card)

        self.decision_section = DialogSection(
            "Unified preflight decision",
            "One explainable result combines source preparation, provider readiness, planning, quota, output policy, baseline guard, and approvals.",
        )
        self.decision_card = DialogStatusCard("Decision not calculated", "", tone="neutral")
        self.decision_card.setObjectName("generationUnifiedDecisionStatus")
        self.decision_section.add_widget(self.decision_card)
        self.decision_recommendations = QLabel()
        self.decision_recommendations.setObjectName("generationUnifiedDecisionRecommendations")
        self.decision_recommendations.setWordWrap(True)
        self.decision_recommendations.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.decision_section.add_widget(self.decision_recommendations)
        self.workspace.add_body_widget(self.decision_section)

        plan_section = DialogSection(
            "Execution plan",
            "The launch uses the same immutable plan calculated by the latest preflight run.",
        )
        self.plan_summary = BatchPlanSummary()
        plan_section.add_widget(self.plan_summary)
        self.workspace.add_body_widget(plan_section)

        checklist_section = DialogSection(
            "Launch checklist",
            "Review every decision item. Required acknowledgements are called out separately below.",
        )
        self.check_table = QTableWidget(0, 3)
        self.check_table.setObjectName("generationLaunchChecklist")
        self.check_table.setHorizontalHeaderLabels(["State", "Check", "Details"])
        self.check_table.horizontalHeader().setStretchLastSection(True)
        self.check_table.setAlternatingRowColors(True)
        self.check_table.setShowGrid(False)
        self.check_table.setSelectionMode(QTableWidget.NoSelection)
        self.check_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.check_table.setMinimumHeight(170)
        checklist_section.add_widget(self.check_table)
        self.workspace.add_body_widget(checklist_section, 1)

        self.ack_section = DialogSection(
            "Required acknowledgements",
            "Start remains disabled until every required decision is explicitly acknowledged.",
        )
        self.ack_container = QFrame()
        self.ack_container.setObjectName("generationLaunchAcknowledgements")
        self.ack_layout = QVBoxLayout(self.ack_container)
        self.ack_layout.setContentsMargins(10, 8, 10, 8)
        self.ack_layout.setSpacing(7)
        self.ack_section.add_widget(self.ack_container)
        self.workspace.add_body_widget(self.ack_section)

        if self.state.existing_outputs:
            output_section = DialogSection(
                "Existing output preview",
                f"{len(self.state.existing_outputs):,} existing output(s) detected · Showing up to 20",
            )
            self.output_table = QTableWidget(min(20, len(self.state.existing_outputs)), 1)
            self.output_table.setObjectName("generationLaunchExistingOutputs")
            self.output_table.setHorizontalHeaderLabels(["Path"])
            self.output_table.horizontalHeader().setStretchLastSection(True)
            self.output_table.setShowGrid(False)
            self.output_table.setSelectionMode(QTableWidget.NoSelection)
            self.output_table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.output_table.setMaximumHeight(190)
            for row, path in enumerate(self.state.existing_outputs[:20]):
                item = QTableWidgetItem(path)
                item.setToolTip(path)
                self.output_table.setItem(row, 0, item)
            output_section.add_widget(self.output_table)
            self.workspace.add_body_widget(output_section)
        else:
            self.output_table = None

        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        self.copy_button = QPushButton("Copy launch summary")
        self.copy_button.setObjectName("generationLaunchCopyAction")
        self.copy_button.setIcon(action_icon("general.copy"))
        self.copy_button.clicked.connect(self.copy_summary)
        tools.addWidget(self.copy_button)
        tools.addStretch(1)
        self.workspace.add_body_widget(self._layout_host(tools))

        self.review_button = QPushButton("Back to Preflight")
        self.start_button = QPushButton("Start reviewed generation")
        self.start_button.setObjectName("dialogPrimaryAction")
        self.start_button.setIcon(action_icon("generation.start"))
        self.review_button.clicked.connect(self.reject)
        self.start_button.clicked.connect(self.accept)
        self.workspace.add_footer_stretch()
        self.workspace.add_footer_widget(self.review_button)
        self.workspace.add_footer_widget(self.start_button)

    def render(self) -> None:
        tone = "warning" if self.confirmation.requires_user_confirmation else "success"
        if not self.confirmation.allowed:
            tone = "error"
        self.status_card.update_status(
            self.confirmation.title or "Generation launch",
            f"{self.confirmation.summary}\n{self.confirmation.message}",
            tone=tone,
        )
        decision = self.confirmation.unified_decision
        settings = self.settings
        provider = settings.provider if settings is not None else (
            self.state.generation_plan.provider if self.state.generation_plan is not None else "Unknown provider"
        )
        model = settings.model_id if settings is not None else (
            self.state.generation_plan.model if self.state.generation_plan is not None else ""
        )
        voice = settings.voice_id if settings is not None else ""
        language = settings.language_code if settings is not None else ""
        trace = decision.trace_id[:12] if decision is not None and decision.trace_id else "not calculated"
        self.readiness_card.update_status(
            "Current explicit Preflight",
            (
                f"Status: {self.state.status} · Preflight revision: {self.state.revision[:12] or 'unknown'} · "
                f"Settings revision: {self.state.settings_revision[:12] or 'unknown'} · Decision trace: {trace}\n"
                f"Resolved request: {provider or 'Unknown provider'} · {voice or 'Default voice'} · "
                f"{model or 'Default model'} · {language or 'Language not set'}\n"
                "This launch review is read-only: it does not change provider/account/voice/model, "
                "rerun Preflight, or start generation. Generation begins only after Start reviewed generation."
            ),
            tone="success" if self.confirmation.allowed else "error",
        )
        self.decision_section.setVisible(decision is not None)
        if decision is not None:
            decision_tone = {
                "ready": "success",
                "ready_with_warnings": "warning",
                "approval_required": "warning",
                "blocked": "error",
            }.get(decision.status, "neutral")
            self.decision_card.update_status(
                decision.headline,
                f"{decision.summary}\nDecision trace: {decision.trace_id}",
                tone=decision_tone,
            )
            if decision.recommendations:
                self.decision_recommendations.setText(
                    "Recommended next actions:\n"
                    + "\n".join(f"• {item}" for item in decision.recommendations)
                )
            else:
                self.decision_recommendations.setText("No additional action is recommended.")
        self.plan_summary.set_plan(self.state.generation_plan)

        self.check_table.setRowCount(len(self.confirmation.checks))
        state_labels = {
            "success": "Ready",
            "warning": "Review",
            "error": "Risk",
            "info": "Info",
            "neutral": "Info",
        }
        for row, check in enumerate(self.confirmation.checks):
            values = [state_labels.get(check.tone, "Info"), check.title, check.detail]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setData(Qt.UserRole, check.tone)
                self.check_table.setItem(row, column, item)

        while self.ack_layout.count():
            item = self.ack_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.acknowledgement_boxes.clear()
        required_checks = [
            item for item in self.confirmation.checks if item.requires_acknowledgement
        ]
        for check in required_checks:
            box = QCheckBox(f"I understand: {check.title}")
            box.setObjectName("generationLaunchAcknowledgement")
            box.setProperty("ackCode", check.code)
            box.setToolTip(check.detail)
            box.toggled.connect(self._update_start_enabled)
            self.acknowledgement_boxes[check.code] = box
            self.ack_layout.addWidget(box)
        if not required_checks:
            ready = QLabel("No additional acknowledgement is required for this launch.")
            ready.setObjectName("generationLaunchNoAcknowledgement")
            ready.setWordWrap(True)
            self.ack_layout.addWidget(ready)
        self.ack_section.setVisible(bool(required_checks))
        self._update_start_enabled()

    def acknowledged_codes(self) -> tuple[str, ...]:
        return tuple(
            code
            for code, box in self.acknowledgement_boxes.items()
            if box.isChecked()
        )

    def copy_summary(self) -> None:
        decision = self.confirmation.unified_decision
        decision_lines = (
            [
                f"Unified decision: {decision.headline}",
                decision.summary,
                f"Decision trace: {decision.trace_id}",
                *(f"Recommendation: {item}" for item in decision.recommendations),
                "",
            ]
            if decision is not None
            else []
        )
        lines = [
            self.confirmation.title,
            self.confirmation.summary,
            self.confirmation.message,
            "",
            *decision_lines,
            *(
                f"[{check.tone.upper()}] {check.title}: {check.detail}"
                for check in self.confirmation.checks
            ),
            "",
            f"Launch fingerprint: {self.confirmation.fingerprint}",
        ]
        QApplication.clipboard().setText("\n".join(lines))

    def _update_start_enabled(self) -> None:
        all_acknowledged = all(
            box.isChecked() for box in self.acknowledgement_boxes.values()
        )
        self.start_button.setEnabled(self.confirmation.allowed and all_acknowledged)
        remaining = sum(
            1 for box in self.acknowledgement_boxes.values() if not box.isChecked()
        )
        if remaining:
            self.start_button.setToolTip(
                f"Acknowledge {remaining:,} remaining decision(s) before starting."
            )
        else:
            self.start_button.setToolTip("Start exactly the reviewed generation batch. No provider or scope change is applied here.")

    @staticmethod
    def _layout_host(layout: QHBoxLayout) -> QFrame:
        host = QFrame()
        host.setObjectName("generationLaunchTools")
        host.setLayout(layout)
        return host
