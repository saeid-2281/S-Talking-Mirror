from __future__ import annotations

from dataclasses import dataclass
from time import sleep

from PySide6.QtTest import QSignalSpy

from app.gui.provider_account_sync import ProviderAccountSyncController
from app.models.domain import AppSettings
from app.models.elevenlabs import ProviderCapability, ProviderConnectionResult
from app.services.voice_service import VoiceCatalog


@dataclass
class _FakeVoiceService:
    calls: int = 0
    delay_seconds: float = 0.0

    def test_connection(self, _settings, *, force_refresh: bool = False):
        if self.delay_seconds:
            sleep(self.delay_seconds)
        self.calls += 1
        capability = ProviderCapability(
            voice_count=3,
            tts_model_count=2,
            account_tier="creator",
            character_count=100,
            character_limit=1000,
        )
        return ProviderConnectionResult("connected", "ok", capability)

    def cached_catalog(self, _settings):
        return VoiceCatalog(voices=(), models=(), account=None, refreshed_at="now")


def test_sync_controller_prevents_duplicate_profile_refresh(qt_app) -> None:
    service = _FakeVoiceService(delay_seconds=0.02)
    controller = ProviderAccountSyncController(service)
    completed = QSignalSpy(controller.completed)

    assert controller.start("profile-a", AppSettings(provider="mock"), force_refresh=True)
    assert not controller.start("profile-a", AppSettings(provider="mock"), force_refresh=True)
    if completed.count() == 0:
        assert completed.wait(2000)
    assert completed.count() == 1
    assert service.calls == 1
    assert not controller.is_busy("profile-a")


def test_sync_controller_allows_independent_profiles(qt_app) -> None:
    service = _FakeVoiceService()
    controller = ProviderAccountSyncController(service)
    completed = QSignalSpy(controller.completed)

    assert controller.start("profile-a", AppSettings(provider="mock"), force_refresh=False)
    assert controller.start("profile-b", AppSettings(provider="mock"), force_refresh=False)
    while completed.count() < 2:
        assert completed.wait(2000)
    ids = {
        completed.at(index)[0].profile_id
        for index in range(completed.count())
    }
    assert ids == {"profile-a", "profile-b"}


def test_sync_controller_logically_cancels_late_result(qt_app) -> None:
    service = _FakeVoiceService(delay_seconds=0.1)
    controller = ProviderAccountSyncController(service)
    completed = QSignalSpy(controller.completed)
    cancelled = QSignalSpy(controller.cancelled)

    assert controller.start("profile-a", AppSettings(provider="mock"), force_refresh=True)
    assert controller.cancel("profile-a")
    assert cancelled.count() == 1
    qt_app.processEvents()
    assert not controller.is_busy("profile-a")
    assert completed.count() == 0
    controller.thread_pool.waitForDone(2000)
    qt_app.processEvents()
    assert completed.count() == 0


def test_provider_accounts_dialog_exposes_background_sync_controls() -> None:
    source = open("app/gui/dialogs/provider_accounts_dialog.py", encoding="utf-8").read()
    assert "ProviderAccountSyncController" in source
    assert "Cancel sync" in source
    assert "Syncing account catalog" in source
    assert "already syncing" in source
