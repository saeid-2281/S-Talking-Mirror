from __future__ import annotations

from pathlib import Path

from app.database.connection import Database
from app.gui.voice_browser import VoiceBrowserDialog
from app.models.domain import AppSettings
from app.repositories.voice_repository import VoiceRepository
from app.services.voice_library_store import VoiceLibraryStore
from app.services.voice_service import VoiceService


def _service(tmp_path: Path) -> VoiceService:
    database = Database(tmp_path / "voices.db")
    database.initialize()
    service = VoiceService(VoiceRepository(database), tmp_path / "previews")
    for index in range(3):
        service.repository.upsert(
            provider="mock",
            voice_id=f"voice-{index}",
            name=f"Voice {index}",
            language="da",
            category="professional",
            metadata={"labels": {"accent": "danish"}},
        )
    return service


def test_voice_library_is_scoped_by_provider_profile(tmp_path: Path) -> None:
    store = VoiceLibraryStore(tmp_path / "library.json")
    store.add_to_collection("elevenlabs", "profile-a", "voice-1", "Narration")
    store.set_pinned("elevenlabs", "profile-a", "voice-1", True)
    store.mark_used("elevenlabs", "profile-a", "voice-1")

    assert store.collections_for_voice("elevenlabs", "profile-a", "voice-1") == ("Narration",)
    assert store.is_pinned("elevenlabs", "profile-a", "voice-1")
    assert store.use_count("elevenlabs", "profile-a", "voice-1") == 1
    assert store.collections_for_voice("elevenlabs", "profile-b", "voice-1") == ()
    assert not store.is_pinned("elevenlabs", "profile-b", "voice-1")


def test_voice_service_filters_recent_collections_and_pinned(tmp_path: Path) -> None:
    service = _service(tmp_path)
    settings = AppSettings(provider="mock", active_api_profile_id="profile-a")
    items = service.list(provider="mock")
    selected = items[1]
    service.add_to_collection(selected, "profile-a", "Lessons")
    service.set_pinned(selected, "profile-a", True)
    service.mark_used(selected, "profile-a")

    collection = service.list(
        provider="mock",
        profile_id="profile-a",
        collection="Lessons",
        collection_only=True,
    )
    recent = service.list(provider="mock", profile_id="profile-a", recent_only=True)
    pinned = service.list(provider="mock", profile_id="profile-a", pinned_only=True)

    assert [item.voice_id for item in collection] == [selected.voice_id]
    assert [item.voice_id for item in recent] == [selected.voice_id]
    assert [item.voice_id for item in pinned] == [selected.voice_id]
    assert settings.active_api_profile_id == "profile-a"


def test_voice_browser_collections_recent_and_pin_ui(qt_app, tmp_path: Path) -> None:
    service = _service(tmp_path)
    settings = AppSettings(provider="mock", active_api_profile_id="profile-a")
    item = service.list(provider="mock")[0]
    service.add_to_collection(item, "profile-a", "Danish")
    service.set_pinned(item, "profile-a", True)
    service.mark_used(item, "profile-a")

    dialog = VoiceBrowserDialog(service=service, settings_provider=lambda: settings)
    dialog._rebuild_collections()
    dialog.tabs.setCurrentIndex(3)
    dialog.collection.setCurrentIndex(dialog.collection.findData("Danish"))
    dialog.apply_filters()
    qt_app.processEvents()

    assert dialog.tabs.count() == 4
    assert dialog.collection.findData("Danish") >= 0
    assert dialog.table.rowCount() == 1
    assert "1 pinned" in dialog.results_label.text()
    assert dialog.pin_button.text() in {"Pin", "Unpin"}
