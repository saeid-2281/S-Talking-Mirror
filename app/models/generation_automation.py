from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GenerationAutomationAction:
    action_type: str
    title: str
    parameters: dict[str, object] = field(default_factory=dict)
    rollback_instruction: str = ""


@dataclass(frozen=True)
class GenerationAutomationPolicy:
    project_id: int | None = None
    enabled: bool = False
    dry_run_default: bool = True
    allowed_actions: tuple[str, ...] = ()
    require_confirmation_for_mutating: bool = True
    allow_unattended_mutating: bool = False
    max_auto_runs_per_incident: int = 2
    cooldown_minutes: int = 60
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationAutomationActionResult:
    position: int
    action_type: str
    title: str
    status: str
    message: str = ""
    output: dict[str, object] = field(default_factory=dict)
    started_at: str = ""
    completed_at: str | None = None
    rollback_instruction: str = ""


@dataclass(frozen=True)
class GenerationAutomatedRemediation:
    automation_id: str
    incident_id: str
    problem_id: str | None
    runbook_id: str | None
    runbook_name: str
    trigger: str
    status: str
    dry_run: bool
    action_results: tuple[GenerationAutomationActionResult, ...] = ()
    actor: str | None = None
    blocked_reason: str | None = None
    rollback_status: str = "not_requested"
    rollback_note: str = ""
    started_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None

    @property
    def completed_actions(self) -> int:
        return sum(
            result.status in {"completed", "planned", "skipped"}
            for result in self.action_results
        )

    @property
    def total_actions(self) -> int:
        return len(self.action_results)

    @property
    def progress_percent(self) -> int:
        if not self.action_results:
            return 0
        return round((self.completed_actions / len(self.action_results)) * 100)
