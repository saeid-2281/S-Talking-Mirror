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
            piper_model_path=settings.piper_model_path,
            stability=settings.stability,
            similarity_boost=settings.similarity_boost,
            style=settings.style,
            speed=settings.speed,
            delay_seconds=settings.delay_seconds,
            max_retries=settings.max_retries,
            use_speaker_boost=settings.use_speaker_boost,
            skip_existing=settings.skip_existing,
        )
