from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CatalogItemKind = Literal["voice", "model"]
CatalogSourceState = Literal[
    "cached",
    "refreshed",
    "built_in",
    "account_required",
    "not_refreshed",
    "error",
]


@dataclass(frozen=True)
class UnifiedCatalogSource:
    provider_id: str
    provider_name: str
    profile_id: str | None
    profile_name: str | None
    state: CatalogSourceState
    voice_count: int
    model_count: int
    refreshed_at: str | None = None
    message: str = ""


@dataclass(frozen=True)
class UnifiedCatalogItem:
    key: str
    kind: CatalogItemKind
    provider_id: str
    provider_name: str
    profile_id: str | None
    profile_name: str | None
    item_id: str
    name: str
    languages: tuple[str, ...] = ()
    category: str | None = None
    description: str = ""
    compatible_model_ids: tuple[str, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    is_favorite: bool = False
    can_do_text_to_speech: bool = True
    maximum_text_length: int | None = None
    cost_factor: float | None = None
    source_state: CatalogSourceState = "cached"

    @property
    def language_text(self) -> str:
        return ", ".join(self.languages)

    @property
    def search_text(self) -> str:
        values = [
            self.kind,
            self.provider_id,
            self.provider_name,
            self.profile_name or "",
            self.item_id,
            self.name,
            self.language_text,
            self.category or "",
            self.description,
            *self.compatible_model_ids,
        ]
        values.extend(value for pair in self.labels for value in pair)
        return " ".join(values).casefold()


@dataclass(frozen=True)
class UnifiedVoiceModelCatalog:
    sources: tuple[UnifiedCatalogSource, ...]
    items: tuple[UnifiedCatalogItem, ...]
    generated_at: str

    @property
    def voice_count(self) -> int:
        return sum(1 for item in self.items if item.kind == "voice")

    @property
    def model_count(self) -> int:
        return sum(1 for item in self.items if item.kind == "model")

    @property
    def provider_count(self) -> int:
        return len(self.sources)

SelectionCompatibility = Literal["compatible", "incompatible", "unknown"]


@dataclass(frozen=True)
class UnifiedCatalogSelectionReview:
    item_key: str
    provider_change: bool
    account_change: bool
    selection_change: bool
    compatibility: SelectionCompatibility
    changes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    can_apply: bool = True

    @property
    def change_text(self) -> str:
        return " · ".join(self.changes) if self.changes else "No settings change."

    @property
    def warning_text(self) -> str:
        return " · ".join(self.warnings)
