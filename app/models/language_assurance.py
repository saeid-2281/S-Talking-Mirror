from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


LanguageAssuranceLevel = Literal["strong", "bounded", "best_effort", "none"]
LanguageEnforcementMode = Literal[
    "explicit_parameter",
    "ssml_locale",
    "model_bound",
    "voice_bound",
    "instruction",
    "test_only",
    "unknown",
]


@dataclass(frozen=True)
class LanguageAssuranceDecision:
    provider_id: str
    requested_language: str
    canonical_language: str
    provider_language: str
    enforcement_mode: LanguageEnforcementMode
    assurance_level: LanguageAssuranceLevel
    blocking: bool = False
    code: str = ""
    message: str = ""
    suggested_action: str = ""
    rows: tuple[int, ...] = ()

    @property
    def requires_acknowledgement(self) -> bool:
        return not self.blocking and self.assurance_level in {"best_effort", "none"}


@dataclass(frozen=True)
class BatchLanguageAssurance:
    decisions: tuple[LanguageAssuranceDecision, ...] = field(default_factory=tuple)
    languages: tuple[str, ...] = field(default_factory=tuple)
    overall_level: LanguageAssuranceLevel = "none"

    @property
    def blocking_count(self) -> int:
        return sum(1 for item in self.decisions if item.blocking)

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.decisions if item.requires_acknowledgement)

    @property
    def summary(self) -> str:
        languages = ", ".join(self.languages) if self.languages else "Language not set"
        modes = ", ".join(
            dict.fromkeys(item.enforcement_mode.replace("_", " ") for item in self.decisions)
        )
        mode_text = modes or "unknown"
        return (
            f"{languages} · assurance {self.overall_level.replace('_', ' ')} · "
            f"enforcement {mode_text}"
        )
