from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any

from app.models.domain import AppSettings


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


def hash_text(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def voice_settings(settings: AppSettings) -> dict[str, Any]:
    return {
        "provider": settings.provider,
        "voice_id": settings.voice_id,
        "model_id": settings.model_id,
        "stability": settings.stability,
        "similarity_boost": settings.similarity_boost,
        "style": settings.style,
        "speed": settings.speed,
        "use_speaker_boost": settings.use_speaker_boost,
    }


def hash_settings(settings: AppSettings) -> str:
    payload = json.dumps(voice_settings(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_cache_key(text: str, settings: AppSettings) -> str:
    payload = {
        "settings": voice_settings(settings),
        "text": normalize_text(text),
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class CacheRepository:
    pass
