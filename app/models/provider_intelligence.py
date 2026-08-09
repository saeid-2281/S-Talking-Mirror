from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSelectionSuggestion:
    model_id: str | None = None
    model_name: str | None = None
    voice_id: str | None = None
    voice_name: str | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.model_id or self.voice_id)

    @property
    def summary(self) -> str:
        parts: list[str] = []
        if self.model_name or self.model_id:
            parts.append(f"Model {self.model_name or self.model_id}")
        if self.voice_name or self.voice_id:
            parts.append(f"Voice {self.voice_name or self.voice_id}")
        return " · ".join(parts)


@dataclass(frozen=True)
class ProviderIntelligenceState:
    provider_id: str
    provider_name: str
    status: str
    tone: str
    selection_summary: str
    compatibility_text: str
    compatibility_tone: str
    quota_text: str
    quota_tone: str
    batch_text: str
    cost_text: str
    recommendation: str
    primary_action_code: str
    primary_action_label: str
    suggestion: ProviderSelectionSuggestion = ProviderSelectionSuggestion()
    catalog_available: bool = False
    scoped_jobs: int = 0
    scoped_characters: int = 0

    @property
    def can_apply_suggestion(self) -> bool:
        return self.primary_action_code == "apply-suggestion" and self.suggestion.has_changes
