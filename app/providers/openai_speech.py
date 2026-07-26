from __future__ import annotations

from typing import Any

import httpx

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult
from app.providers.base import TTSProvider

OPENAI_SPEECH_MODELS = ("gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15", "tts-1", "tts-1-hd")
OPENAI_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar")
OPENAI_FORMATS = ("mp3", "opus", "aac", "flac", "wav", "pcm")


class OpenAISpeechProvider(TTSProvider):
    provider_id = "openai"
    display_name = "OpenAI Speech"
    BASE_URL = "https://api.openai.com"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=settings.timeout_seconds,
            headers={"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {},
        )

    def close(self) -> None:
        self.client.close()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=True,
            requires_credential=True,
            supports_voice_listing=True,
            supports_model_listing=True,
            supports_language_code=False,
            supports_speed=True,
            supports_streaming=True,
            supports_cancellation=True,
            supported_output_formats=OPENAI_FORMATS,
            credential_fields=("api_key",),
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.api_key:
            return ProviderConfigurationResult(False, "OpenAI API key is required.")
        if settings.model_id not in OPENAI_SPEECH_MODELS:
            return ProviderConfigurationResult(False, f"Unsupported OpenAI speech model: {settings.model_id}.")
        if settings.voice_id not in OPENAI_VOICES:
            return ProviderConfigurationResult(False, f"Unsupported OpenAI voice: {settings.voice_id}.")
        if len(settings.model_dump_json()) > 100_000:
            return ProviderConfigurationResult(False, "Settings payload is unexpectedly large.")
        return ProviderConfigurationResult(True, "OpenAI Speech configuration is valid. Quota unavailable from provider.")

    def test_connection(self) -> ProviderConfigurationResult:
        return self.validate_configuration(self.settings)

    def list_voices(self) -> list[dict[str, Any]]:
        return [{"voice_id": voice, "name": voice.title(), "category": "built-in"} for voice in OPENAI_VOICES]

    def list_models(self) -> list[dict[str, Any]]:
        return [{"model_id": model, "name": model, "can_do_text_to_speech": True} for model in OPENAI_SPEECH_MODELS]

    def list_languages(self) -> list[dict[str, str]]:
        return []

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        if not result.ok:
            raise ConfigurationError(result.message)
        if len(text) > 4096:
            raise ProviderError("OpenAI Speech input exceeds 4096 characters.", retryable=False, provider_code="input_too_large")
        response_format = (settings.output_format or "mp3").split("_", 1)[0]
        if response_format not in OPENAI_FORMATS:
            raise ProviderError("OpenAI Speech output format is unsupported.", retryable=False, provider_code="unsupported_format")
        payload: dict[str, Any] = {
            "model": settings.model_id,
            "voice": settings.voice_id,
            "input": text,
            "response_format": response_format,
            "speed": settings.speed,
        }
        response = self.client.post("/v1/audio/speech", json=payload, headers={"Accept": "audio/mpeg"})
        if response.status_code >= 400:
            raise self._error(response)
        if not response.content:
            raise ProviderError("OpenAI returned an empty audio response.", retryable=True, provider_code="empty_audio")
        return response.content

    def _error(self, response: httpx.Response) -> ProviderError:
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
        code = "rate_limit" if response.status_code == 429 else "openai_error"
        if response.status_code in {401, 403}:
            code = "invalid_api_key"
            retryable = False
        return ProviderError(
            f"OpenAI Speech request failed with HTTP {response.status_code}.",
            retryable=retryable,
            http_status=response.status_code,
            provider_code=code,
            request_id=request_id,
            technical_details=response.text[:300],
        )
