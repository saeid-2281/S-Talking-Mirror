from __future__ import annotations

from pathlib import Path

from app.database.connection import Database
from app.models.domain import AppSettings
from app.repositories.voice_repository import VoiceRepository
from app.services.voice_service import VoiceService


def make_service(tmp_path: Path) -> VoiceService:
    database = Database(tmp_path / "voices.db")
    database.initialize()
    return VoiceService(VoiceRepository(database), tmp_path / "previews")


def test_voice_repository_upsert_list_and_favorite(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.repository.upsert(
        provider="elevenlabs",
        voice_id="voice-1",
        name="Danish Voice",
        language="da",
        category="professional",
        metadata={"description": "Calm Danish voice", "labels": {"accent": "danish"}},
    )
    items = service.list(provider="elevenlabs")
    assert len(items) == 1
    assert items[0].name == "Danish Voice"
    service.set_favorite(items[0], True)
    favorites = service.list(provider="elevenlabs", favorites_only=True)
    assert len(favorites) == 1
    assert favorites[0].is_favorite is True


def test_voice_search_covers_metadata(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.repository.upsert(
        provider="elevenlabs",
        voice_id="voice-2",
        name="Claus",
        language="da",
        category="professional",
        metadata={"description": "Warm narrator", "labels": {"accent": "copenhagen"}},
    )
    assert service.list(provider="elevenlabs", query="warm")
    assert service.list(provider="elevenlabs", query="copenhagen")
    assert service.list(provider="elevenlabs", query="voice-2")
    assert not service.list(provider="elevenlabs", query="swedish")


def test_mock_refresh_and_preview(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    settings = AppSettings(provider="mock", api_key="", file_extension=".wav")
    voices = service.refresh(settings)
    assert voices[0].voice_id == "mock-tone"
    path = service.preview(voices[0], "Hej verden", settings)
    assert path.exists()
    assert path.suffix == ".wav"
    assert path.read_bytes().startswith(b"RIFF")
