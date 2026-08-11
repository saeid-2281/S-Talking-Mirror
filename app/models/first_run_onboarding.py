from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class FirstRunOnboardingStep:
    step_id: str
    title: str
    stage: str
    description: str
    action_id: str
    action_label: str
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FirstRunOnboardingState:
    document_schema_version: int
    completed_steps: tuple[str, ...] = field(default_factory=tuple)
    first_run_completed: bool = False
    completed_at: str = ""
    updated_at: str = ""
    last_step: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "document_schema_version": self.document_schema_version,
            "completed_steps": list(self.completed_steps),
            "first_run_completed": self.first_run_completed,
            "completed_at": self.completed_at,
            "updated_at": self.updated_at,
            "last_step": self.last_step,
        }
