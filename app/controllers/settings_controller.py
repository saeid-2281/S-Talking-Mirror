from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.config import load_settings, save_settings
from app.models.domain import AppSettings


@dataclass(frozen=True)
class ProviderSettingsData:
    settings: AppSettings


class SettingsController:
    """Coordinates settings persistence and dirty-state suppression."""

    def __init__(self, settings_path: Path = Path("settings.json")) -> None:
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
