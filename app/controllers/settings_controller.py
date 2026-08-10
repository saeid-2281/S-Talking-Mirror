from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import load_settings, save_settings
from app.models.domain import AppSettings
from app.models.ui_state import SettingsViewData


class SettingsController:
    """Coordinates settings persistence and dirty-state suppression."""

    def __init__(self, settings_path: Path) -> None:
        self.settings_path = settings_path
        self._loading = False
        self._last_settings: AppSettings | None = None

    @property
    def is_loading(self) -> bool:
        return self._loading

    @contextmanager
    def loading(self) -> Iterator[None]:
        previous = self._loading
        self._loading = True
        try:
            yield
        finally:
            self._loading = previous

    def load_global_settings(self) -> AppSettings | None:
        try:
            settings = load_settings(self.settings_path)
        except Exception:
            return None
        self._last_settings = settings
        return settings

    def save_global_settings(self, settings: AppSettings) -> None:
        save_settings(settings, self.settings_path)
        self._last_settings = settings

    def settings_changed(self, settings: AppSettings) -> bool:
        if self._loading:
            self._last_settings = settings
            return False
        changed = self._last_settings != settings
        self._last_settings = settings
        return changed

    def from_view_data(self, values: SettingsViewData) -> AppSettings:
        return values.to_settings()

    def to_view_data(self, settings: AppSettings) -> SettingsViewData:
        return SettingsViewData(
            provider=settings.provider,
            api_key=settings.api_key,
            voice_id=settings.voice_id,
            model_id=settings.model_id,
            language_code=settings.language_code,
            piper_model_path=settings.piper_model_path,
            stability=settings.stability,
            similarity_boost=settings.similarity_boost,
            style=settings.style,
            speed=settings.speed,
            short_text_pronunciation_aid=settings.short_text_pronunciation_aid,
            delay_seconds=settings.delay_seconds,
            max_retries=settings.max_retries,
            use_speaker_boost=settings.use_speaker_boost,
            skip_existing=settings.skip_existing,
            active_api_profile_id=settings.active_api_profile_id,
            provider_options=dict(settings.provider_options),
            api_profile_failover=settings.api_profile_failover,
            api_profile_failover_max_switches=settings.api_profile_failover_max_switches,
            api_profile_failover_sequence_mode=settings.api_profile_failover_sequence_mode,
            api_profile_failover_manual_sequence=settings.api_profile_failover_manual_sequence,
            allow_unknown_quota_override=settings.allow_unknown_quota_override,
            generation_scope=settings.generation_scope,
            execution_order=settings.execution_order,
            pronunciation_dictionary_locators=settings.pronunciation_dictionary_locators,
            active_pronunciation_dictionary_id=settings.active_pronunciation_dictionary_id,
            job_pronunciation_overrides=settings.job_pronunciation_overrides,
        )
