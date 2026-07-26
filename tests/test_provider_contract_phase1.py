from __future__ import annotations

import httpx
import pytest

from app.exceptions import ConfigurationError
from app.models import AppSettings
from app.provider_factory import available_provider_ids, create_provider
from app.providers.openai_speech import OPENAI_FORMATS, OPENAI_SPEECH_MODELS, OPENAI_VOICES, OpenAISpeechProvider
from app.providers.optional_adapters import AmazonPollyProvider, AzureSpeechProvider, GoogleCloudTTSProvider, KokoroLocalProvider


def test_provider_factory_lists_requested_providers() -> None:
    assert {"mock", "piper", "elevenlabs", "openai", "azure", "google", "aws_polly", "kokoro"}.issubset(available_provider_ids())


def test_openai_capabilities_and_validation() -> None:
    settings = AppSettings(provider="openai", api_key="sk_TEST", model_id="gpt-4o-mini-tts", voice_id="alloy")
    provider = OpenAISpeechProvider(settings)
    try:
        capabilities = provider.capabilities()
        assert capabilities.requires_credential is True
        assert capabilities.supports_speed is True
        assert capabilities.supported_output_formats == OPENAI_FORMATS
        assert provider.validate_configuration(settings).ok is True
        assert provider.validate_configuration(settings.model_copy(update={"voice_id": "missing"})).ok is False
    finally:
        provider.close()


def test_openai_speech_request_payload(monkeypatch) -> None:
    captured = {}
    settings = AppSettings(provider="openai", api_key="sk_TEST", model_id="gpt-4o-mini-tts", voice_id="alloy", output_format="wav", speed=1.1)
    provider = OpenAISpeechProvider(settings)

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return httpx.Response(200, content=b"audio", request=httpx.Request("POST", "https://api.openai.com/v1/audio/speech"))

    monkeypatch.setattr(provider.client, "post", fake_post)
    try:
        assert provider.synthesize("Hej", settings) == b"audio"
    finally:
        provider.close()

    assert captured["url"] == "/v1/audio/speech"
    assert captured["json"] == {
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "input": "Hej",
        "response_format": "wav",
        "speed": 1.1,
    }


def test_openai_input_limit_and_no_quota_guess() -> None:
    settings = AppSettings(provider="openai", api_key="sk_TEST", model_id=OPENAI_SPEECH_MODELS[0], voice_id=OPENAI_VOICES[0])
    provider = OpenAISpeechProvider(settings)
    try:
        with pytest.raises(Exception):
            provider.synthesize("x" * 4097, settings)
        assert "Quota unavailable from provider" in provider.validate_configuration(settings).message
    finally:
        provider.close()


def test_optional_provider_adapters_report_missing_dependencies_without_import_crash() -> None:
    for cls in [AzureSpeechProvider, GoogleCloudTTSProvider, AmazonPollyProvider, KokoroLocalProvider]:
        provider = cls(AppSettings(provider=cls.provider_id))
        result = provider.validate_configuration(provider.settings)
        assert provider.capabilities().provider_id == cls.provider_id
        assert result.ok is False or result.ok is True
        if not result.ok:
            assert result.missing_dependency
            with pytest.raises(ConfigurationError):
                provider.synthesize("Hej", provider.settings)


def test_factory_creates_openai_provider() -> None:
    provider = create_provider(AppSettings(provider="openai", api_key="sk_TEST", model_id="gpt-4o-mini-tts", voice_id="alloy"))
    try:
        assert provider.capabilities().display_name == "OpenAI Speech"
    finally:
        provider.close()
