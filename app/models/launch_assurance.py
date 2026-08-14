from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LaunchAssuranceEvidence:
    """Privacy-safe evidence that one resolved request crossed all launch checkpoints."""

    preflight_revision: str
    preflight_context_fingerprint: str
    launch_revision: str
    generation_revision: str = ""
    status: str = "launch_verified"
    checked_dimensions: tuple[str, ...] = ()

    @property
    def launch_matches_preflight(self) -> bool:
        return bool(self.preflight_revision) and self.launch_revision == self.preflight_revision

    @property
    def generation_matches_launch(self) -> bool:
        return bool(self.generation_revision) and self.generation_revision == self.launch_revision

    @property
    def fully_verified(self) -> bool:
        return (
            self.status == "generation_verified"
            and self.launch_matches_preflight
            and self.generation_matches_launch
        )
