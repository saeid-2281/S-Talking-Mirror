from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_automation import GenerationAutomationPolicy
from app.services.generation_remediation_automation_service import (
    GenerationRemediationAutomationService,
)


class RemediationAutomationPolicyDialog(QDialog):
    """Edit the fail-safe automation policy for one project or the global scope."""

    ACTION_LABELS = {
        "record_workaround": "Record known-problem workaround",
        "evaluate_sla": "Evaluate SLA state",
        "acknowledge_incident": "Acknowledge incident",
        "retry_transient_jobs": "Retry transient failed jobs",
        "reset_interrupted_jobs": "Reset interrupted jobs",
    }

    def __init__(
        self,
        service: GenerationRemediationAutomationService,
        project_id: int | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.source = service.get_policy(project_id)
        self.action_checks: dict[str, QCheckBox] = {}
        scope = "Global" if project_id is None else f"Project {project_id}"
        self.setWindowTitle(f"Remediation Automation Policy · {scope}")
        self.resize(620, 600)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        note = QLabel(
            "Automation is disabled by default. Live mutating actions require explicit "
            "confirmation unless unattended execution is deliberately enabled."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        form = QFormLayout()
        self.enabled = QCheckBox("Enable remediation automation")
        self.enabled.setChecked(self.source.enabled)
        self.dry_run_default = QCheckBox("Use Dry Run by default")
        self.dry_run_default.setChecked(self.source.dry_run_default)
        self.require_confirmation = QCheckBox(
            "Require confirmation for live mutating actions"
        )
        self.require_confirmation.setChecked(
            self.source.require_confirmation_for_mutating
        )
        self.allow_unattended = QCheckBox(
            "Allow unattended mutating actions (advanced)"
        )
        self.allow_unattended.setChecked(self.source.allow_unattended_mutating)
        self.max_runs = QSpinBox()
        self.max_runs.setRange(1, 20)
        self.max_runs.setValue(self.source.max_auto_runs_per_incident)
        self.cooldown = QSpinBox()
        self.cooldown.setRange(0, 10080)
        self.cooldown.setSuffix(" min")
        self.cooldown.setValue(self.source.cooldown_minutes)
        form.addRow("", self.enabled)
        form.addRow("", self.dry_run_default)
        form.addRow("", self.require_confirmation)
        form.addRow("", self.allow_unattended)
        form.addRow("Maximum automatic runs", self.max_runs)
        form.addRow("Minimum cooldown", self.cooldown)
        root.addLayout(form)

        group = QGroupBox("Allowlisted internal actions")
        group_layout = QVBoxLayout(group)
        allowed = set(self.source.allowed_actions or self.service.supported_actions)
        for action_type in self.service.supported_actions:
            check = QCheckBox(self.ACTION_LABELS.get(action_type, action_type))
            check.setChecked(action_type in allowed)
            check.setToolTip(action_type)
            self.action_checks[action_type] = check
            group_layout.addWidget(check)
        root.addWidget(group, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def policy(self) -> GenerationAutomationPolicy:
        return GenerationAutomationPolicy(
            project_id=self.project_id,
            enabled=self.enabled.isChecked(),
            dry_run_default=self.dry_run_default.isChecked(),
            allowed_actions=tuple(
                action_type
                for action_type, check in self.action_checks.items()
                if check.isChecked()
            ),
            require_confirmation_for_mutating=self.require_confirmation.isChecked(),
            allow_unattended_mutating=self.allow_unattended.isChecked(),
            max_auto_runs_per_incident=self.max_runs.value(),
            cooldown_minutes=self.cooldown.value(),
            updated_at=self.source.updated_at,
        )
