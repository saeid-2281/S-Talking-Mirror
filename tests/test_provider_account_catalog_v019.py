from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models.domain import AppSettings
from app.services.voice_service import VoiceService


class _Provider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def list_voices(self):
        return []

    def list_models(self):
        return [
            {"model_id": self.model_id, "name": self.model_id, "can_do_text_to_speech": True},
            {"model_id": self.model_id, "name": f"{self.model_id} duplicate", "can_do_text_to_speech": True},
        ]

    def get_subscription(self):
        return {"tier": "creator", "status": "active", "character_count": 10, "character_limit": 100}

    def close(self):
        return None


def _service(tmp_path: Path) -> VoiceService:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    return VoiceService(container.voice_repository, tmp_path / "previews")


def test_catalog_cache_is_profile_specific_and_force_refresh_bypasses_cache(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def factory(settings: AppSettings):
        calls.append(str(settings.active_api_profile_id))
        return _Provider(f"model-{settings.active_api_profile_id}")

    monkeypatch.setattr("app.services.voice_service.create_provider", factory)
    service = _service(tmp_path)
    first = AppSettings(provider="elevenlabs", api_key="same-key", active_api_profile_id="first")
    second = AppSettings(provider="elevenlabs", api_key="same-key", active_api_profile_id="second")

    assert service.refresh_catalog(first).models[0].model_id == "model-first"
    assert service.refresh_catalog(first).models[0].model_id == "model-first"
    assert service.refresh_catalog(second).models[0].model_id == "model-second"
    assert service.refresh_catalog(first, force=True).models[0].model_id == "model-first"

    assert calls == ["first", "second", "first"]


def test_model_normalization_removes_duplicate_model_ids(tmp_path: Path) -> None:
    service = _service(tmp_path)
    items = service._normalize_models(
        [
            {"model_id": "eleven_v3", "name": "Old"},
            {"model_id": "eleven_v3", "name": "Current"},
            {"model_id": "eleven_flash_v2_5", "name": "Flash"},
        ]
    )

    assert [item.model_id for item in items] == ["eleven_v3", "eleven_flash_v2_5"]
    assert items[0].name == "Current"
