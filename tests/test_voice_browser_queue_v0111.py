from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.models import AppSettings, JobStatus, TTSJob
from app.repositories.voice_repository import VoiceRepository
from app.services.preview_service import PreviewService
from app.services.voice_service import VoiceService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class FakeProvider:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.synthesize_calls = 0

    def list_voices(self):
        if self.error:
            raise self.error
        return [
            {"voice_id": "voice-1", "name": "Beta", "labels": {"language": "da"}, "high_quality_base_model_ids": ["model-a"]},
            {"voice_id": "voice-2", "name": "Alpha", "labels": {"language": "en"}, "high_quality_base_model_ids": ["model-a"]},
        ]

    def list_models(self):
        return [
            {"model_id": "model-a", "name": "Model A", "can_do_text_to_speech": True},
            {"model_id": "model-b", "name": "Model B", "can_do_text_to_speech": False},
        ]

    def get_subscription(self):
        return {"tier": "creator", "status": "active", "character_count": 10, "character_limit": 110}

    def synthesize(self, _text, _settings):
        self.synthesize_calls += 1
        if self.error:
            raise self.error
        return b"preview"

    def close(self):
        pass


def make_voice_service(tmp_path: Path) -> VoiceService:
    database = Database(tmp_path / "voices.db")
    database.initialize()
    return VoiceService(
        VoiceRepository(database),
        tmp_path / "previews",
        PreviewService(tmp_path / "previews" / "index.json"),
    )


def test_shared_account_state_model_combo_and_fallback(qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gui.voice_browser import VoiceBrowserDialog

    provider = FakeProvider()
    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: provider)
    service = make_voice_service(tmp_path)
    settings = AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice-1", model_id="missing")
    assert service.test_connection(settings).connected is True

    dialog = VoiceBrowserDialog(service=service, settings_provider=lambda: settings)
    dialog._load_cached()

    assert "creator" in dialog.account_label.text()
    assert "100 characters remaining" in dialog.account_label.text()
    assert dialog.model.count() == 2
    assert dialog.model.currentData() == "model-a"
    assert "unavailable" in dialog.preview_status.text()


def test_preview_library_indexes_reuses_survives_and_cleans_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: provider)
    service = make_voice_service(tmp_path)
    settings = AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice-1", model_id="model-a")
    item = service.refresh_catalog(settings).voices[0]

    first = service.preview(item, "Hej", settings)
    second = service.preview(item, "Hej", settings)
    restarted = make_voice_service(tmp_path)

    assert first == second
    assert provider.synthesize_calls == 1
    assert restarted.saved_previews(item)[0].file_path == first
    first.unlink()
    assert restarted.saved_previews(item) == []


def test_failed_preview_is_not_indexed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.exceptions import ProviderError

    provider = FakeProvider(error=ProviderError("paid", provider_code="paid_plan_required"))
    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: provider)
    service = make_voice_service(tmp_path)
    service.repository.upsert(provider="elevenlabs", voice_id="voice-1", name="Voice")
    item = service.list(provider="elevenlabs")[0]

    with pytest.raises(ProviderError):
        service.preview(item, "Hej", AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice-1", model_id="model-a"))

    assert service.saved_previews(item) == []


def test_saved_preview_actions_and_switching_voice_stops_playback(qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gui.voice_browser import VoiceBrowserDialog

    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: FakeProvider())
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    settings = AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice-1", model_id="model-a")
    catalog = context.voice_service.refresh_catalog(settings)
    first = catalog.voices[0]
    path = context.voice_service.preview(first, "Hej", settings)
    dialog = VoiceBrowserDialog(service=context.voice_service, settings_provider=lambda: settings, audio_player_service=context.audio_player_service)
    dialog._catalog_loaded(catalog)
    dialog.table.selectRow(0)

    assert dialog.saved_preview_table.rowCount() == 1
    dialog.play_selected_saved_preview()
    assert context.audio_player_service.current_path == path
    dialog.table.selectRow(1)
    assert context.audio_player_service.playback_state == "stopped"


def test_delete_and_clear_saved_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: FakeProvider())
    service = make_voice_service(tmp_path)
    settings = AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice-1", model_id="model-a")
    item = service.refresh_catalog(settings).voices[0]
    service.preview(item, "One", settings)
    service.preview(item, "Two", settings)

    records = service.saved_previews(item)
    service.delete_preview(records[0])
    assert len(service.saved_previews(item)) == 1
    assert service.clear_previews_for_voice(item) == 1
    assert service.saved_previews(item) == []


def test_favorite_provider_order_stable_and_filters(tmp_path: Path) -> None:
    service = make_voice_service(tmp_path)
    service.repository.upsert(provider="elevenlabs", voice_id="voice-1", name="Beta")
    service.repository.upsert(provider="elevenlabs", voice_id="voice-2", name="Alpha")
    items = service.list(provider="elevenlabs")
    service.set_favorite(items[1], True)

    assert [item.voice_id for item in service.list(provider="elevenlabs")] == ["voice-1", "voice-2"]
    assert [item.voice_id for item in service.list(provider="elevenlabs", favorites_only=True)] == ["voice-2"]
    assert [item.name for item in service.list(provider="elevenlabs", sort_mode="name")] == ["Alpha", "Beta"]


def test_voice_browser_responsive_controls(qt_app, tmp_path: Path) -> None:
    from app.gui.voice_browser import VoiceBrowserDialog

    service = make_voice_service(tmp_path)
    dialog = VoiceBrowserDialog(service=service, settings_provider=lambda: AppSettings(provider="mock"))
    dialog.resize(900, 620)

    assert dialog.table.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.details_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert dialog.preview_button.minimumWidth() >= 120
    assert dialog.audio_player.play_pause.minimumWidth() >= 72


def test_retry_failed_and_selected_reset_state_and_messages(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    jobs = [
        TTSJob(row_number=2, filename="one.wav", text="one", status=JobStatus.FAILED, error="boom", retry_count=3),
        TTSJob(row_number=3, filename="two.wav", text="two", status=JobStatus.RUNNING, error="busy", retry_count=1),
    ]
    window.generation_controller.set_jobs(jobs)
    window.render_queue()

    window.retry_failed()
    assert jobs[0].status == JobStatus.PENDING
    assert jobs[0].retry_count == 0
    assert jobs[0].error is None
    assert "1 failed jobs reset to pending." in window.log.toPlainText()

    window.retry_selected()
    assert "No selected failed jobs are eligible to retry." in window.log.toPlainText()
