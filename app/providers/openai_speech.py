from __future__ import annotations

from typing import Any

import httpx

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import (
    ProviderCapabilities,
    ProviderConfigurationResult,
    ProviderNormalizedError,
)
from app.providers.base import TTSProvider

OPENAI_SPEECH_MODELS = (
    "gpt-4o-mini-tts",
    "gpt-4o-mini-tts-2025-12-15",
    "gpt-4o-mini-tts-2025-03-20",
    "tts-1",
    "tts-1-hd",
)
OPENAI_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)
_OPENAI_LEGACY_TTS_VOICES = (
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
)
OPENAI_FORMATS = ("mp3", "opus", "aac", "flac", "wav", "pcm")
_OPENAI_MIME_TYPES = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "application/octet-stream",
}


class OpenAISpeechProvider(TTSProvider):
    """Production HTTP adapter for the OpenAI Audio Speech endpoint."""

    provider_id = "openai"
    display_name = "OpenAI Speech"
    BASE_URL = "https://api.openai.com"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancelled = False
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=settings.timeout_seconds,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            }
            if settings.api_key
            else {"Content-Type": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def cancel(self) -> None:
        """Best-effort cancellation for an in-flight synchronous HTTP request."""
        self._cancelled = True
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
        if not settings.api_key.strip():
            return ProviderConfigurationResult(False, "OpenAI API key is required.")
        if settings.model_id not in OPENAI_SPEECH_MODELS:
            return ProviderConfigurationResult(
                False,
                f"Unsupported OpenAI speech model: {settings.model_id}.",
            )
        if not self._voice_supported(settings.voice_id, settings.model_id):
            return ProviderConfigurationResult(
                False,
                f"Unsupported OpenAI voice {settings.voice_id!r} for model {settings.model_id}.",
            )
        response_format = self._response_format(settings)
        if response_format not in OPENAI_FORMATS:
            return ProviderConfigurationResult(
                False,
                f"Unsupported OpenAI speech output format: {response_format}.",
            )
        if not 0.25 <= float(settings.speed) <= 4.0:
            return ProviderConfigurationResult(
                False,
                "OpenAI speech speed must be between 0.25 and 4.0.",
            )
        return ProviderConfigurationResult(
            True,
            "OpenAI Speech configuration is valid. Quota unavailable from provider.",
        )

    def test_connection(self) -> ProviderConfigurationResult:
        result = self.validate_configuration(self.settings)
        if not result.ok:
            return result
        # Model retrieval validates both authentication and access without
        # creating billable speech output.
        response = self._request("GET", f"/v1/models/{self.settings.model_id}")
        if response.status_code >= 400:
            raise self._error(response)
        return ProviderConfigurationResult(
            True,
            f"OpenAI Speech connected; model {self.settings.model_id} is accessible.",
        )

    def list_voices(self) -> list[dict[str, Any]]:
        modern_models = tuple(
            model for model in OPENAI_SPEECH_MODELS if model.startswith("gpt-4o-mini-tts")
        )
        legacy_models = ("tts-1", "tts-1-hd")
        return [
            {
                "voice_id": voice,
                "name": voice.title(),
                "category": "built-in",
                "description": "OpenAI built-in speech voice",
                "compatible_model_ids": (
                    modern_models + legacy_models
                    if voice in _OPENAI_LEGACY_TTS_VOICES
                    else modern_models
                ),
            }
            for voice in OPENAI_VOICES
        ]

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": model,
                "name": model,
                "can_do_text_to_speech": True,
            }
            for model in OPENAI_SPEECH_MODELS
        ]

    def list_languages(self) -> list[dict[str, str]]:
        # The Speech endpoint accepts multilingual input but does not use a
        # language-code request parameter.
        return []

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        if not result.ok:
            raise ConfigurationError(result.message)
        if len(text) > 4096:
            raise ProviderError(
                "OpenAI Speech input exceeds 4096 characters.",
                retryable=False,
                provider_code="input_too_large",
            )

        response_format = self._response_format(settings)
        payload: dict[str, Any] = {
            "model": settings.model_id,
            "voice": self._voice_payload(settings.voice_id),
            "input": text,
            "response_format": response_format,
            "speed": settings.speed,
        }
        instructions = str(settings.provider_options.get("instructions") or "").strip()
        if instructions and settings.model_id not in {"tts-1", "tts-1-hd"}:
            payload["instructions"] = instructions[:4096]

        self._cancelled = False
        response = self._request(
            "POST",
            "/v1/audio/speech",
            json=payload,
            headers={"Accept": _OPENAI_MIME_TYPES[response_format]},
        )
        if response.status_code >= 400:
            raise self._error(response)
        if self._cancelled:
            raise ProviderError(
                "OpenAI Speech request was cancelled.",
                retryable=False,
                provider_code="cancelled",
            )
        if not response.content:
            raise ProviderError(
                "OpenAI returned an empty audio response.",
                retryable=True,
                provider_code="empty_audio",
            )
        return response.content

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "openai_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderNormalizedError(
                "timeout",
                "OpenAI Speech request timed out.",
                retryable=True,
            )
        if isinstance(error, httpx.TransportError):
            return ProviderNormalizedError(
                "network_error",
                "OpenAI Speech network request failed.",
                retryable=True,
                safe_details=str(error)[:300],
            )
        return super().normalize_error(error)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            normalized = method.upper()
            if normalized == "POST":
                return self.client.post(url, **kwargs)
            if normalized == "GET":
                return self.client.get(url, **kwargs)
            return self.client.request(normalized, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "OpenAI Speech request timed out.",
                retryable=True,
                provider_code="timeout",
                technical_details=str(exc)[:300],
            ) from exc
        except httpx.TransportError as exc:
            if self._cancelled:
                raise ProviderError(
                    "OpenAI Speech request was cancelled.",
                    retryable=False,
                    provider_code="cancelled",
                ) from exc
            raise ProviderError(
                "OpenAI Speech network request failed.",
                retryable=True,
                provider_code="network_error",
                technical_details=str(exc)[:300],
            ) from exc

    def _error(self, response: httpx.Response) -> ProviderError:
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
        code = "rate_limit" if response.status_code == 429 else "openai_error"
        if response.status_code in {401, 403}:
            code = "invalid_api_key"
            retryable = False
        elif response.status_code == 404:
            code = "model_not_found"
            retryable = False
        elif response.status_code == 400:
            code = "invalid_request"
            retryable = False

        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or "")
        except (ValueError, TypeError):
            detail = ""
        safe_detail = detail[:300] or response.text[:300]

        return ProviderError(
            f"OpenAI Speech request failed with HTTP {response.status_code}.",
            retryable=retryable,
            http_status=response.status_code,
            provider_code=code,
            request_id=request_id,
            technical_details=safe_detail,
        )

    @staticmethod
    def _response_format(settings: AppSettings) -> str:
        return (settings.output_format or "mp3").split("_", 1)[0].casefold()

    @staticmethod
    def _voice_supported(voice_id: str, model_id: str) -> bool:
        voice = str(voice_id or "").strip()
        model = str(model_id or "").strip()
        if voice.startswith("voice_"):
            return model.startswith("gpt-4o-mini-tts")
        if model in {"tts-1", "tts-1-hd"}:
            return voice in _OPENAI_LEGACY_TTS_VOICES
        return voice in OPENAI_VOICES

    @staticmethod
    def _voice_payload(voice_id: str) -> str | dict[str, str]:
        voice = str(voice_id or "").strip()
        if voice.startswith("voice_"):
            return {"id": voice}
        return voice
