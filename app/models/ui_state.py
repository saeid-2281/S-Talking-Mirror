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
    language_code: str | None
    piper_model_path: str | None
    stability: float
    similarity_boost: float
    style: float
    speed: float
    short_text_pronunciation_aid: bool
    delay_seconds: float
    max_retries: int
    use_speaker_boost: bool
    skip_existing: bool
    active_api_profile_id: str | None = None
    api_profile_failover: str = "never"
    api_profile_failover_max_switches: int = 1
    api_profile_failover_sequence_mode: str = "active_then_backups"
    api_profile_failover_manual_sequence: list[str] | None = None
    allow_unknown_quota_override: bool = False
    generation_scope: str = "row_range"
    execution_order: str = "csv"
    pronunciation_dictionary_locators: list[dict[str, str]] | None = None
    active_pronunciation_dictionary_id: str | None = None
    job_pronunciation_overrides: dict[int, str] | None = None

    def to_settings(self) -> AppSettings:
        return AppSettings(
            provider=self.provider,
            api_key=self.api_key,
            voice_id=self.voice_id,
            model_id=self.model_id or "eleven_multilingual_v2",
            language_code=self.language_code or None,
            stability=self.stability,
            similarity_boost=self.similarity_boost,
            style=self.style,
            use_speaker_boost=self.use_speaker_boost,
            speed=self.speed,
            short_text_pronunciation_aid=self.short_text_pronunciation_aid,
            delay_seconds=self.delay_seconds,
            max_retries=self.max_retries,
            skip_existing=self.skip_existing,
            overwrite_existing=False,
            piper_model_path=self.piper_model_path,
            active_api_profile_id=self.active_api_profile_id,
            api_profile_failover=self.api_profile_failover,
            api_profile_failover_max_switches=self.api_profile_failover_max_switches,
            api_profile_failover_sequence_mode=self.api_profile_failover_sequence_mode,
            api_profile_failover_manual_sequence=list(self.api_profile_failover_manual_sequence or []),
            allow_unknown_quota_override=self.allow_unknown_quota_override,
            generation_scope=self.generation_scope,
            execution_order=self.execution_order,
            pronunciation_dictionary_locators=list(self.pronunciation_dictionary_locators or []),
            active_pronunciation_dictionary_id=self.active_pronunciation_dictionary_id,
            job_pronunciation_overrides=dict(self.job_pronunciation_overrides or {}),
        )


@dataclass
class GenerationUiState:
    """Presentation state for generation controls."""

    jobs: list[TTSJob]
    paused: bool = False
    status: str = "idle"
