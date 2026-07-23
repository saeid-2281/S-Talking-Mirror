from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.models.domain import AppSettings, TTSJob


@dataclass(frozen=True)
class GenerationContext:
    """Inputs needed to start a generation run."""

    project_name: str
    project_key: str
    output_path: Path


@dataclass(frozen=True)
class SettingsViewData:
    """View-facing settings values collected from provider widgets."""

    provider: str
    api_key: str
    voice_id: str
    model_id: str
    piper_model_path: str | None
    stability: float
    similarity_boost: float
    style: float
    speed: float
    delay_seconds: float
    max_retries: int
    use_speaker_boost: bool
    skip_existing: bool

    def to_settings(self) -> AppSettings:
        return AppSettings(
            provider=self.provider,
            api_key=self.api_key,
            voice_id=self.voice_id,
            model_id=self.model_id or "eleven_multilingual_v2",
            language_code="da",
            stability=self.stability,
            similarity_boost=self.similarity_boost,
            style=self.style,
            use_speaker_boost=self.use_speaker_boost,
            speed=self.speed,
            delay_seconds=self.delay_seconds,
            max_retries=self.max_retries,
            skip_existing=self.skip_existing,
            overwrite_existing=False,
            piper_model_path=self.piper_model_path,
        )


@dataclass
class GenerationUiState:
    """Presentation state for generation controls."""

    jobs: list[TTSJob]
    paused: bool = False
    status: str = "idle"
