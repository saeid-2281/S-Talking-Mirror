from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import AppSettings
from app.models.preflight_state import PreflightState


@dataclass(frozen=True)
class GenerationConfirmation:
    allowed: bool
    title: str = ""
    message: str = ""
    requires_user_confirmation: bool = False


class GenerationConfirmationCoordinator:
    """Single source for start-generation confirmation decisions."""

    def evaluate(self, state: PreflightState, settings: AppSettings) -> GenerationConfirmation:
        if state.status == "Blocked by errors":
            return GenerationConfirmation(False, "Preflight errors", "Resolve blocking errors before generation.")
        if state.status == "Ready with warnings":
            warnings = sum(1 for issue in state.issues if issue.severity == "warning")
            return GenerationConfirmation(
                True,
                "Preflight warnings",
                f"{warnings:,} warning(s) found. Continue anyway?",
                True,
            )
        return GenerationConfirmation(True)
