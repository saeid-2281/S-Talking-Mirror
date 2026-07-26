from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreviewRecord:
    provider: str
    voice_id: str
    model_id: str
    preview_text: str
    text_hash: str
    settings_hash: str
    file_path: Path
    created_at: str
    duration_seconds: float | None
    file_size: int
    last_played_at: str | None = None

    @property
    def character_count(self) -> int:
        return len(self.preview_text)
