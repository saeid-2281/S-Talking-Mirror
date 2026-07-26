from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest
from PySide6.QtWidgets import QApplication

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.exceptions import ProviderError
from app.gui.worker import GenerationWorker
from app.models import AppSettings, JobStatus, TTSJob
from app.providers.elevenlabs import ElevenLabsProvider
from app.services.voice_service import VoiceService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class FakeProvider:
    def __init__(self, *, voices=None, models=None, subscription=None, error: Exception | None = None, audio=b"RIFFdata"):
        self.voices = voices or [{"voice_id": "voice-1", "name": "Voice", "high_quality_base_model_ids": ["model-a"]}]
        self.models = models or [{"model_id": "model-a", "name": "Model", "can_do_text_to_speech": True}]
        self.subscription = subscription or {"tier": "free", "status": "active", "character_count": 10, "character_limit": 100}
        self.error = error
        self.audio = audio
        self.cancelled = False

    def list_voices(self):
        if self.error:
            raise self.error
        return self.voices

    def list_models(self):
        if self.error:
            raise self.error
        return self.models

    def get_subscription(self):
        if self.error:
            raise self.error
        return self.subscription

    def synthesize(self, _text, _settings):
        if self.error:
            raise self.error
        return self.audio

    def cancel(self):
        self.cancelled = True

    def close(self):
        pass


def settings(**kwargs) -> AppSettings:
    base = {
        "provider": "elevenlabs",
        "api_key": "sk_TEST",
        "voice_id": "voice-1",
        "model_id": "model-a",
        "delay_seconds": 0,
        "max_retries": 1,
    }
    base.update(kwargs)
    return AppSettings(**base)


def test_valid_connection_and_catalog_cache(monkeypatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def factory(_settings):
        calls["count"] += 1
        return FakeProvider()

    monkeypatch.setattr("app.services.voice_service.create_provider", factory)
    service = VoiceService(create_service_container(RuntimeConfig.from_root(tmp_path)).voice_repository, tmp_path / "previews")

    first = service.test_connection(settings())
    second = service.test_connection(settings())

    assert first.connected is True
    assert first.capability.voice_count == 1
    assert first.capability.tts_model_count == 1
    assert first.capability.remaining_characters == 90
    assert second.connected is True
    assert calls["count"] == 1


def test_invalid_key_connection(monkeypatch, tmp_path: Path) -> None:
    error = ProviderError("Invalid ElevenLabs API key.", provider_code="invalid_api_key", http_status=401)
    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: FakeProvider(error=error))
    service = VoiceService(create_service_container(RuntimeConfig.from_root(tmp_path)).voice_repository, tmp_path / "previews")

    result = service.test_connection(settings())

    assert result.status == "invalid_key"
    assert result.http_status == 401


def test_api_key_cache_invalidation(monkeypatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def factory(_settings):
        calls["count"] += 1
        return FakeProvider()

    monkeypatch.setattr("app.services.voice_service.create_provider", factory)
    service = VoiceService(create_service_container(RuntimeConfig.from_root(tmp_path)).voice_repository, tmp_path / "previews")

    service.refresh_catalog(settings(api_key="sk_ONE"))
    service.refresh_catalog(settings(api_key="sk_ONE"))
    service.refresh_catalog(settings(api_key="sk_TWO"))
    service.invalidate_provider_cache(settings(api_key="sk_TWO"))
    service.refresh_catalog(settings(api_key="sk_TWO"))

    assert calls["count"] == 3


def test_error_mapping_paid_plan_quota_voice_model_and_secret_redaction() -> None:
    provider = ElevenLabsProvider(settings(api_key="sk_SECRET"))
    try:
        for status, message, expected in [
            (403, "paid subscription required", "paid_plan_required"),
            (402, "quota exceeded", "insufficient_quota"),
            (404, "voice not found", "voice_not_found"),
            (404, "model not found", "model_not_found"),
        ]:
            response = httpx.Response(status, json={"detail": {"message": message, "code": expected}})
            error = provider._error_from_response(response)
            assert error.code == expected
            assert "sk_SECRET" not in (error.technical_details or "")
    finally:
        provider.close()


def test_rate_limit_retry_after_and_retryable_vs_non_retryable(monkeypatch) -> None:
    attempts = {"count": 0}

    def handler(_request):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "1.5"}, json={"detail": {"message": "rate limit"}})
        return httpx.Response(200, content=b"ok")

    provider = ElevenLabsProvider(settings())
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(handler), base_url=provider.BASE_URL)
    waits = []
    monkeypatch.setattr(provider, "_interruptible_sleep", lambda seconds: waits.append(seconds))
    try:
        assert provider._request("GET", "/v1/models").content == b"ok"
        assert waits == [1.5]
        non_retryable = provider._error_from_response(httpx.Response(401, json={"detail": {"message": "bad key"}}))
        assert non_retryable.retryable is False
    finally:
        provider.close()


def test_interruptible_backoff_cancellation() -> None:
    provider = ElevenLabsProvider(settings())
    try:
        provider.cancel()
        started = time.monotonic()
        try:
            provider._interruptible_sleep(5)
        except ProviderError as exc:
            assert exc.provider_code == "cancelled"
        assert time.monotonic() - started < 1
    finally:
        provider.close()


def test_preflight_quota_blocks_only_confirmed_insufficient_quota(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "app.services.voice_service.create_provider",
        lambda _settings: FakeProvider(subscription={"tier": "free", "status": "active", "character_count": 95, "character_limit": 100}),
    )
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = tmp_path / "out"
    output.mkdir()
    container.voice_service.refresh_catalog(settings())

    state = container.preflight_service.run(jobs=[TTSJob(row_number=2, filename="one.mp3", text="x" * 10)], settings=settings(), output_dir=output)

    assert state.can_start is False
    assert state.blocking_errors >= 1
    assert any(issue.severity == "hard_error" and "quota is insufficient" in issue.message for issue in state.issues)
    assert state.quota_snapshot["remaining"] == 5


def test_warning_only_preflight_remains_startable_and_blocked_has_error(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = tmp_path / "out"
    output.mkdir()
    (output / "one.wav").write_bytes(b"RIFF")

    warning = container.preflight_service.run(
        jobs=[TTSJob(row_number=2, filename="one.wav", text="one")],
        settings=AppSettings(provider="mock", skip_existing=True),
        output_dir=output,
    )
    blocked = container.preflight_service.run(
        jobs=[TTSJob.model_construct(row_number=2, filename="bad:name.wav", text="", status=JobStatus.PENDING)],
        settings=AppSettings(provider="mock"),
        output_dir=output,
    )

    assert warning.status == "Ready with warnings"
    assert warning.can_start is True
    assert blocked.status == "Blocked by errors"
    assert any(issue.severity == "hard_error" for issue in blocked.issues)


def test_atomic_output_partial_cleanup_and_cancel_keeps_pending(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / ".old.wav.tmp").write_bytes(b"partial")
    worker = GenerationWorker(
        [TTSJob(row_number=2, filename="one.mp3", text="one")],
        settings(),
        output,
        tmp_path / "state.sqlite",
        "project",
    )
    monkeypatch.setattr(
        "app.gui.worker.create_provider",
        lambda _settings: FakeProvider(error=ProviderError("cancelled", provider_code="cancelled")),
    )

    worker.run()

    assert worker.jobs[0].status == JobStatus.PENDING
    assert not list(output.glob("*.tmp"))
    assert not (output / "one.mp3").exists()


def test_atomic_output_writes_final_file(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "out"
    worker = GenerationWorker(
        [TTSJob(row_number=2, filename="one.mp3", text="one")],
        settings(),
        output,
        tmp_path / "state.sqlite",
        "project",
    )
    monkeypatch.setattr("app.gui.worker.create_provider", lambda _settings: FakeProvider(audio=b"audio"))

    worker.run()

    assert (output / "one.mp3").read_bytes() == b"audio"
    assert not list(output.glob("*.tmp"))


def test_safe_provider_error_details_for_reports() -> None:
    error = ProviderError(
        "ElevenLabs rate limit reached.",
        retryable=True,
        http_status=429,
        provider_code="rate_limit",
        request_id="req-123",
        technical_details="safe details",
    )

    text = GenerationWorker._safe_error(error)
    info = GenerationWorker._error_info(error)

    assert "rate_limit" in text
    assert "429" in text
    assert "req-123" in text
    assert info["provider_code"] == "rate_limit"
    assert "api_key" not in str(info).lower()


def test_preview_cache_and_failed_preview_not_cached(monkeypatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    def factory(_settings):
        calls["count"] += 1
        if calls["count"] == 3:
            return FakeProvider(error=ProviderError("paid", provider_code="paid_plan_required"))
        return FakeProvider(audio=b"preview")

    monkeypatch.setattr("app.services.voice_service.create_provider", factory)
    service = VoiceService(create_service_container(RuntimeConfig.from_root(tmp_path)).voice_repository, tmp_path / "previews")
    catalog = service.refresh_catalog(settings())
    item = catalog.voices[0]

    first = service.preview(item, "Hej", settings())
    second = service.preview(item, "Hej", settings())

    assert first == second
    assert first.read_bytes() == b"preview"
    assert calls["count"] == 2
    try:
        service.preview(item, "Ny tekst", settings())
    except ProviderError:
        pass
    assert service.cached_preview_path(item, "Ny tekst", settings()) is None


def test_main_window_connection_controls_exist(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))

    assert window.test_connection_button.text() == "Test connection"
    assert window.connection_status.text() == "Not tested"
