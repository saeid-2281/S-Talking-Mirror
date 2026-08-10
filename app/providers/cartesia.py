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

CARTESIA_API_VERSION = "2026-03-01"
CARTESIA_TTS_MODELS = ("sonic-3.5", "sonic-3", "sonic-latest")
CARTESIA_LANGUAGES = (
    "en", "fr", "de", "es", "pt", "zh", "ja", "hi", "it", "ko", "nl",
    "pl", "ru", "sv", "tr", "tl", "bg", "ro", "ar", "cs", "el", "fi",
    "hr", "ms", "sk", "da", "ta", "uk", "hu", "no", "vi", "bn", "th",
    "he", "ka", "id", "te", "gu", "kn", "ml", "mr", "pa",
)
CARTESIA_OUTPUT_FORMATS = ("mp3", "wav")


class CartesiaProvider(TTSProvider):
    provider_id = "cartesia"
    display_name = "Cartesia"
    BASE_URL = "https://api.cartesia.ai"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancelled = False
        headers = {
            "Content-Type": "application/json",
            "Cartesia-Version": CARTESIA_API_VERSION,
        }
        if settings.api_key.strip():
            headers["Authorization"] = f"Bearer {settings.api_key.strip()}"
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=settings.timeout_seconds,
            headers=headers,
        )

    def close(self) -> None:
        self.client.close()

    def cancel(self) -> None:
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
            supports_language_code=True,
            supports_pronunciation_dictionary=True,
            supports_speed=True,
            supports_volume=True,
            supports_streaming=True,
            supports_cancellation=True,
            supported_output_formats=CARTESIA_OUTPUT_FORMATS,
            credential_fields=("api_key",),
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.api_key.strip():
            return ProviderConfigurationResult(False, "Cartesia API key is required.")
        return ProviderConfigurationResult(True, "Cartesia API credential is configured.")

    def validate_synthesis_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        account = self.validate_configuration(settings)
        if not account.ok:
            return account
        model = str(settings.model_id or "").strip()
        if model not in CARTESIA_TTS_MODELS:
            return ProviderConfigurationResult(False, f"Unsupported Cartesia TTS model: {model or 'none'}.")
        if not str(settings.voice_id or "").strip():
            return ProviderConfigurationResult(False, "Cartesia voice is required.")
        language = self._language(settings)
        if language and language not in CARTESIA_LANGUAGES:
            return ProviderConfigurationResult(False, f"Cartesia language {language!r} is not supported by the current Sonic API contract.")
        output = self._simple_output(settings)
        if output not in CARTESIA_OUTPUT_FORMATS:
            return ProviderConfigurationResult(False, f"Unsupported Cartesia output format: {output}.")
        if not 0.6 <= float(settings.speed) <= 1.5:
            return ProviderConfigurationResult(False, "Cartesia speed must be between 0.6 and 1.5.")
        return ProviderConfigurationResult(True, "Cartesia Sonic synthesis configuration is valid.")

    def test_connection(self) -> ProviderConfigurationResult:
        if not self.settings.api_key.strip():
            return ProviderConfigurationResult(False, "Cartesia API key is required.")
        response = self._request("GET", "/voices", params={"limit": 1})
        if response.status_code >= 400:
            raise self._error(response)
        return ProviderConfigurationResult(True, "Cartesia connected; voice catalog is accessible.")

    def list_voices(self) -> list[dict[str, Any]]:
        if not self.settings.api_key.strip():
            raise ConfigurationError("Cartesia API key is required.")
        language = self._language(self.settings)
        params: dict[str, object] = {"limit": 100, "expand[]": "preview_file_url"}
        if language:
            params["language"] = language
        voices: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(20):
            if cursor:
                params["starting_after"] = cursor
            response = self._request("GET", "/voices", params=params)
            if response.status_code >= 400:
                raise self._error(response)
            payload = response.json()
            items = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise ProviderError("Cartesia returned an invalid voice catalog.", retryable=True, provider_code="invalid_catalog")
            for item in items:
                if not isinstance(item, dict):
                    continue
                voice_id = str(item.get("id") or "").strip()
                if not voice_id:
                    continue
                locales = item.get("locales") if isinstance(item.get("locales"), list) else []
                locale_values = [str(value.get("locale") or "") for value in locales if isinstance(value, dict)]
                primary_language = str(item.get("language") or "").strip()
                voices.append(
                    {
                        "voice_id": voice_id,
                        "name": str(item.get("name") or voice_id),
                        "language": primary_language or (locale_values[0] if locale_values else ""),
                        "category": "cartesia-sonic",
                        "description": str(item.get("description") or item.get("tagline") or ""),
                        "preview_url": str(item.get("preview_file_url") or "") or None,
                        "is_owner": bool(item.get("is_owner")) if "is_owner" in item else None,
                        "labels": {
                            "language": primary_language,
                            "locales": ",".join(value for value in locale_values if value),
                            "gender": str(item.get("gender") or ""),
                            "country": str(item.get("country") or ""),
                        },
                        "compatible_model_ids": list(CARTESIA_TTS_MODELS),
                    }
                )
            if not bool(payload.get("has_more")):
                break
            cursor = str(payload.get("next_page") or "").strip()
            if not cursor:
                break
        return voices

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": model,
                "name": "Cartesia Sonic 3.5" if model == "sonic-3.5" else f"Cartesia {model}",
                "languages": list(CARTESIA_LANGUAGES),
                "can_do_text_to_speech": True,
            }
            for model in CARTESIA_TTS_MODELS
        ]

    def list_languages(self) -> list[dict[str, str]]:
        return [{"language_code": code, "name": code} for code in CARTESIA_LANGUAGES]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_synthesis_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        payload: dict[str, Any] = {
            "model_id": settings.model_id,
            "transcript": text,
            "voice": {"mode": "id", "id": settings.voice_id},
            "output_format": self._output_format(settings),
        }
        language = self._language(settings)
        if language:
            payload["language"] = language
        if float(settings.speed) != 1.0:
            payload["generation_config"] = {"speed": float(settings.speed)}
        pronunciation_dict_id = str(settings.provider_options.get("pronunciation_dict_id") or "").strip()
        if pronunciation_dict_id:
            payload["pronunciation_dict_id"] = pronunciation_dict_id
        self._cancelled = False
        response = self._request("POST", "/tts/bytes", json=payload)
        if response.status_code >= 400:
            raise self._error(response)
        if self._cancelled:
            raise ProviderError("Cartesia request was cancelled.", retryable=False, provider_code="cancelled")
        if not response.content:
            raise ProviderError("Cartesia returned empty audio.", retryable=True, provider_code="empty_audio")
        return response.content

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "cartesia_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderNormalizedError("timeout", "Cartesia request timed out.", retryable=True)
        if isinstance(error, httpx.TransportError):
            return ProviderNormalizedError("network_error", "Cartesia network request failed.", retryable=True, safe_details=str(error)[:300])
        return super().normalize_error(error)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.client.request(method.upper(), url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError("Cartesia request timed out.", retryable=True, provider_code="timeout", technical_details=str(exc)[:300]) from exc
        except httpx.TransportError as exc:
            code = "cancelled" if self._cancelled else "network_error"
            raise ProviderError(
                "Cartesia request was cancelled." if self._cancelled else "Cartesia network request failed.",
                retryable=not self._cancelled,
                provider_code=code,
                technical_details=str(exc)[:300],
            ) from exc

    @staticmethod
    def _language(settings: AppSettings) -> str:
        value = str(settings.language_code or "").strip().replace("_", "-")
        return value.split("-", 1)[0].casefold() if value else ""

    @staticmethod
    def _simple_output(settings: AppSettings) -> str:
        return (settings.output_format or settings.file_extension.strip(".") or "mp3").split("_", 1)[0].casefold()

    @classmethod
    def _output_format(cls, settings: AppSettings) -> dict[str, object]:
        output = cls._simple_output(settings)
        if output == "wav":
            return {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 44100}
        if output == "mp3":
            return {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000}
        raise ConfigurationError(f"Unsupported Cartesia output format: {output}.")

    def _error(self, response: httpx.Response) -> ProviderError:
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        detail = ""
        code = "cartesia_error"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("detail") or payload.get("title") or "")
                code = str(payload.get("error_code") or code)
                request_id = request_id or str(payload.get("request_id") or "") or None
        except (ValueError, TypeError):
            detail = ""
        retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
        if response.status_code in {401, 403}:
            code = "invalid_api_key"
            retryable = False
        elif response.status_code == 429:
            code = "quota_or_rate_limit"
        elif response.status_code in {400, 404, 422}:
            code = "invalid_request"
            retryable = False
        return ProviderError(
            f"Cartesia request failed with HTTP {response.status_code}.",
            retryable=retryable,
            http_status=response.status_code,
            provider_code=code,
            request_id=request_id,
            technical_details=(detail or response.text)[:300],
        )
