from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VoicePreviewResult:
    path: Path
    cache_hit: bool
    latency_ms: int
