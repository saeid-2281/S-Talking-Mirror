from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioPlayerState:
    current_path: Path | None = None
    position: int = 0
    duration: int = 0
    playback_state: str = "stopped"
    volume: int = 70
    status: str = "No audio loaded"
    error: str = ""
    loaded: bool = False

    @property
    def filename(self) -> str:
        return self.current_path.name if self.current_path else "No file loaded"
