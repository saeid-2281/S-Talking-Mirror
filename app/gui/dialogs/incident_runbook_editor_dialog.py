from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.models.generation_automation import GenerationAutomationAction
from app.models.generation_incident import GenerationIncidentRunbook


class IncidentRunbookEditorDialog(QDialog):
    """Create or edit manual steps and allowlisted automation for one runbook."""

    def __init__(
        self,
        runbook: GenerationIncidentRunbook,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source = runbook
        self.setWindowTitle("Incident Runbook")
        self.resize(700, 680)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._manual_tab(), "Runbook")
        tabs.addTab(self._automation_tab(), "Automation")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _manual_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.name = QLineEdit(self._source.name)
        self.description = QPlainTextEdit(self._source.description)
        self.description.setMaximumHeight(90)
        self.severity = QComboBox()
        for label, value in (
            ("Any severity", "any"),
            ("Critical", "critical"),
            ("Warning", "warning"),
        ):
            self.severity.addItem(label, value)
        index = self.severity.findData(self._source.severity_filter)
        self.severity.setCurrentIndex(max(0, index))
        self.pattern = QLineEdit(self._source.fingerprint_pattern)
        self.pattern.setPlaceholderText(
            "Optional regex for fingerprint, title, or summary"
        )
        self.enabled = QCheckBox("Enabled")
        self.enabled.setChecked(self._source.enabled)
        self.steps = QPlainTextEdit("\n".join(self._source.steps))
        self.steps.setPlaceholderText("One manual remediation step per line")
        form.addRow("Name", self.name)
        form.addRow("Description", self.description)
        form.addRow("Severity", self.severity)
        form.addRow("Fingerprint pattern", self.pattern)
        form.addRow("", self.enabled)
        form.addRow("Manual steps", self.steps)
        return tab

    def _automation_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.automation_enabled = QCheckBox("Enable allowlisted automation")
        self.automation_enabled.setChecked(self._source.automation_enabled)
        self.automation_trigger = QComboBox()
        for label, value in (
            ("Manual only", "manual"),
            ("When an incident opens", "incident_opened"),
            ("When a known problem recurs", "known_problem_recurrence"),
        ):
            self.automation_trigger.addItem(label, value)
        index = self.automation_trigger.findData(self._source.automation_trigger)
        self.automation_trigger.setCurrentIndex(max(0, index))
        self.dry_run_only = QCheckBox("Restrict this runbook to Dry Run")
        self.dry_run_only.setChecked(self._source.dry_run_only)
        self.max_auto_runs = QSpinBox()
        self.max_auto_runs.setRange(1, 20)
        self.max_auto_runs.setValue(self._source.max_auto_runs)
        self.cooldown_minutes = QSpinBox()
        self.cooldown_minutes.setRange(0, 10080)
        self.cooldown_minutes.setSuffix(" min")
        self.cooldown_minutes.setValue(self._source.cooldown_minutes)
        self.automation_actions = QPlainTextEdit(
            "\n".join(self._format_action(action) for action in self._source.automation_actions)
        )
        self.automation_actions.setPlaceholderText(
            "One action per line:\n"
            "action_type | Display title | {\"max_retries\": 4} | Rollback instruction\n\n"
            "Supported: record_workaround, evaluate_sla, acknowledge_incident, "
            "retry_transient_jobs, reset_interrupted_jobs"
        )
        self.rollback_instructions = QPlainTextEdit(
            self._source.rollback_instructions
        )
        self.rollback_instructions.setMaximumHeight(100)
        self.rollback_instructions.setPlaceholderText(
            "Operator instructions when a live automation fails"
        )
        form.addRow("", self.automation_enabled)
        form.addRow("Trigger", self.automation_trigger)
        form.addRow("", self.dry_run_only)
        form.addRow("Maximum automatic runs", self.max_auto_runs)
        form.addRow("Cooldown", self.cooldown_minutes)
        form.addRow("Allowlisted actions", self.automation_actions)
        form.addRow("Rollback instructions", self.rollback_instructions)
        return tab

    def runbook(self) -> GenerationIncidentRunbook:
        return GenerationIncidentRunbook(
            runbook_id=self._source.runbook_id,
            project_id=self._source.project_id,
            name=self.name.text(),
            description=self.description.toPlainText(),
            severity_filter=str(self.severity.currentData() or "any"),
            fingerprint_pattern=self.pattern.text(),
            steps=tuple(self.steps.toPlainText().splitlines()),
            enabled=self.enabled.isChecked(),
            automation_enabled=self.automation_enabled.isChecked(),
            automation_trigger=str(self.automation_trigger.currentData() or "manual"),
            automation_actions=self._parse_actions(
                self.automation_actions.toPlainText().splitlines()
            ),
            dry_run_only=self.dry_run_only.isChecked(),
            max_auto_runs=self.max_auto_runs.value(),
            cooldown_minutes=self.cooldown_minutes.value(),
            rollback_instructions=self.rollback_instructions.toPlainText(),
            created_at=self._source.created_at,
            updated_at=self._source.updated_at,
        )

    @staticmethod
    def _format_action(action: GenerationAutomationAction) -> str:
        parameters = json.dumps(action.parameters, ensure_ascii=False, sort_keys=True)
        return " | ".join(
            (
                action.action_type,
                action.title,
                parameters,
                action.rollback_instruction,
            )
        ).rstrip(" |")

    @staticmethod
    def _parse_actions(lines: list[str]) -> tuple[GenerationAutomationAction, ...]:
        actions: list[GenerationAutomationAction] = []
        for line_number, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split("|", 3)]
            action_type = parts[0]
            title = parts[1] if len(parts) > 1 else ""
            parameters_text = parts[2] if len(parts) > 2 else "{}"
            rollback = parts[3] if len(parts) > 3 else ""
            try:
                parameters = json.loads(parameters_text or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Automation action line {line_number} contains invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(parameters, dict):
                raise ValueError(
                    f"Automation action line {line_number} parameters must be a JSON object."
                )
            actions.append(
                GenerationAutomationAction(
                    action_type=action_type,
                    title=title,
                    parameters={str(key): value for key, value in parameters.items()},
                    rollback_instruction=rollback,
                )
            )
        return tuple(actions)
