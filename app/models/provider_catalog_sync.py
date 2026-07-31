from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.voice_service import VoiceCatalog


@dataclass(frozen=True)
class CatalogSyncResult:
    catalog: "VoiceCatalog"
    latency_ms: int
    completed_at: str


@dataclass(frozen=True)
class CatalogDiagnostics:
    provider: str
    profile_id: str
    state: str
    stale: bool
    voice_count: int
    model_count: int
    remaining_characters: int | None
    character_limit: int | None
    refreshed_at: str | None
    saved_at: str | None
    latency_ms: int | None = None
    last_error: str | None = None

    @property
    def quota_text(self) -> str:
        if self.remaining_characters is None:
            return "Unavailable"
        if self.character_limit is None:
            return f"{self.remaining_characters:,} remaining"
        return f"{self.remaining_characters:,} / {self.character_limit:,} remaining"

    @classmethod
    def missing(cls, provider: str, profile_id: str) -> "CatalogDiagnostics":
        return cls(
            provider=provider,
            profile_id=profile_id,
            state="Not cached",
            stale=False,
            voice_count=0,
            model_count=0,
            remaining_characters=None,
            character_limit=None,
            refreshed_at=None,
            saved_at=None,
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
