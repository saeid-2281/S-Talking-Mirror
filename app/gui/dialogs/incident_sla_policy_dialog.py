from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_incident import GenerationIncidentSlaPolicy


class IncidentSlaPolicyDialog(QDialog):
    """Edit global or project-specific incident response and resolution targets."""

    def __init__(
        self,
        policy: GenerationIncidentSlaPolicy,
        parent: QWidget | None = None,
        *,
        project_name: str = "Global",
    ) -> None:
        super().__init__(parent)
        self._policy = policy
        self.setWindowTitle("Incident SLA Policy")
        self.resize(460, 300)

        root = QVBoxLayout(self)
        title = QLabel(f"Incident SLA policy · {project_name}")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)

        form = QFormLayout()
        self.enabled = QCheckBox("Enable SLA tracking and escalation")
        self.enabled.setChecked(policy.enabled)
        form.addRow("Policy", self.enabled)
        self.critical_response = self._minutes(policy.critical_response_minutes)
        self.critical_resolution = self._minutes(policy.critical_resolution_minutes)
        self.warning_response = self._minutes(policy.warning_response_minutes)
        self.warning_resolution = self._minutes(policy.warning_resolution_minutes)
        form.addRow("Critical response", self.critical_response)
        form.addRow("Critical resolution", self.critical_resolution)
        form.addRow("Warning response", self.warning_response)
        form.addRow("Warning resolution", self.warning_resolution)
        root.addLayout(form)

        hint = QLabel(
            "Changing the policy recalculates deadlines for active incidents in this scope."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _minutes(value: int) -> QSpinBox:
        field = QSpinBox()
        field.setRange(1, 10080)
        field.setSuffix(" min")
        field.setValue(max(1, int(value)))
        return field

    def policy(self) -> GenerationIncidentSlaPolicy:
        return replace(
            self._policy,
            enabled=self.enabled.isChecked(),
            critical_response_minutes=self.critical_response.value(),
            critical_resolution_minutes=self.critical_resolution.value(),
            warning_response_minutes=self.warning_response.value(),
            warning_resolution_minutes=self.warning_resolution.value(),
        )
