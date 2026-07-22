from __future__ import annotations

import json
import os
from pathlib import Path

from app.exceptions import ConfigurationError
from app.models import AppSettings


def load_settings(path: Path) -> AppSettings:
    if not path.exists():
        raise ConfigurationError(
            f"Settings file not found: {path}. Copy settings.example.json to settings.json."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Could not read settings: {exc}") from exc

    env_key = os.getenv("ELEVENLABS_API_KEY")
    if env_key:
        raw["api_key"] = env_key

    try:
        return AppSettings.model_validate(raw)
    except Exception as exc:
        raise ConfigurationError(f"Invalid settings: {exc}") from exc


def save_settings(settings: AppSettings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
