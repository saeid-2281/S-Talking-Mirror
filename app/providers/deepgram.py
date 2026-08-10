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

DEEPGRAM_OUTPUT_FORMATS = ("mp3", "wav", "opus", "flac", "aac", "pcm")
DEEPGRAM_DOCUMENTED_AURA_LANGUAGES = ("en", "es", "nl", "fr", "de", "it", "ja")


class DeepgramProvider(TTSProvider):
    provider_id = "deepgram"
    display_name = "Deepgram Aura"
    BASE_URL = "https://api.deepgram.com"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancelled = False
        self._model_payload: dict[str, Any] | None = None
        headers = {"Content-Type": "application/json"}
        if settings.api_key.strip():
            headers["Authorization"] = f"Token {settings.api_key.strip()}"
        self.client = httpx.Client(base_url=self.BASE_URL, timeout=settings.timeout_seconds, headers=headers)

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
            supports_speed=True,
            supports_streaming=True,
            supports_cancellation=True,
            supported_output_formats=DEEPGRAM_OUTPUT_FORMATS,
            credential_fields=("api_key",),
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.api_key.strip():
            return ProviderConfigurationResult(False, "Deepgram API key is required.")
        return ProviderConfigurationResult(True, "Deepgram API credential is configured.")

    def validate_synthesis_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        account = self.validate_configuration(settings)
        if not account.ok:
            return account
        model = self._selected_model(settings)
        if not model.startswith("aura-"):
            return ProviderConfigurationResult(False, "Select an explicit Deepgram Aura TTS voice/model before synthesis.")
        configured_model = str(settings.model_id or "").strip()
        configured_voice = str(settings.voice_id or "").strip()
        if configured_model.startswith("aura-") and configured_voice.startswith("aura-") and configured_model != configured_voice:
            return ProviderConfigurationResult(False, "Deepgram Aura voice and model must reference the same catalog model.")
        language = self._language(settings)
        model_language = self._model_language(model)
        if language == "da" and model_language != "da":
            return ProviderConfigurationResult(False, "Deepgram Aura Danish is not certified in S-Talking because the current public Aura catalog does not document Danish voices.")
        if language and model_language and language != model_language:
            return ProviderConfigurationResult(False, f"Deepgram model {model} is {model_language}, not {language}.")
        output = self._simple_output(settings)
        if output not in DEEPGRAM_OUTPUT_FORMATS:
            return ProviderConfigurationResult(False, f"Unsupported Deepgram output format: {output}.")
        if not 0.7 <= float(settings.speed) <= 1.5:
            return ProviderConfigurationResult(False, "Deepgram Aura speed must be between 0.7 and 1.5.")
        return ProviderConfigurationResult(True, "Deepgram Aura synthesis configuration is valid.")

    def test_connection(self) -> ProviderConfigurationResult:
        if not self.settings.api_key.strip():
            return ProviderConfigurationResult(False, "Deepgram API key is required.")
        payload = self._models_payload(force=True)
        tts = payload.get("tts") if isinstance(payload, dict) else None
        count = len(tts) if isinstance(tts, list) else 0
        return ProviderConfigurationResult(True, f"Deepgram connected; {count} public TTS model(s) discovered.")

    def list_voices(self) -> list[dict[str, Any]]:
        models = self._tts_models()
        requested = self._language(self.settings)
        voices: list[dict[str, Any]] = []
        for item in models:
            canonical = str(item.get("canonical_name") or item.get("name") or "").strip()
            if not canonical:
                continue
            languages = tuple(str(value) for value in item.get("languages") or () if value)
            base_languages = {self._base_language(value) for value in languages}
            if requested and requested not in base_languages:
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
            use_cases = metadata.get("use_cases") if isinstance(metadata.get("use_cases"), list) else []
            voice_name = str(item.get("name") or canonical)
            voices.append(
                {
                    "voice_id": canonical,
                    "name": voice_name.title(),
                    "language": languages[0] if languages else self._model_language(canonical),
                    "category": "deepgram-aura-2",
                    "description": ", ".join(str(value) for value in tags if value),
                    "preview_url": str(metadata.get("sample") or "") or None,
                    "labels": {
                        "language": ",".join(languages),
                        "accent": str(metadata.get("accent") or ""),
                        "age": str(metadata.get("age") or ""),
                        "use_case": ",".join(str(value) for value in use_cases if value),
                        "tags": ",".join(str(value) for value in tags if value),
                    },
                    "compatible_model_ids": [canonical],
                }
            )
        return voices

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": str(item.get("canonical_name") or item.get("name") or ""),
                "name": str(item.get("canonical_name") or item.get("name") or ""),
                "languages": [str(value) for value in item.get("languages") or () if value],
                "can_do_text_to_speech": True,
            }
            for item in self._tts_models()
            if str(item.get("canonical_name") or item.get("name") or "").strip()
        ]

    def list_languages(self) -> list[dict[str, str]]:
        languages: set[str] = set()
        for item in self._tts_models():
            for value in item.get("languages") or ():
                if str(value).strip():
                    languages.add(str(value).strip())
        return [{"language_code": code, "name": code} for code in sorted(languages, key=str.casefold)]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_synthesis_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        params = {"model": self._selected_model(settings), **self._output_params(settings)}
        if float(settings.speed) != 1.0:
            params["speed"] = str(float(settings.speed))
        self._cancelled = False
        response = self._request("POST", "/v1/speak", params=params, json={"text": text})
        if response.status_code >= 400:
            raise self._error(response)
        if self._cancelled:
            raise ProviderError("Deepgram request was cancelled.", retryable=False, provider_code="cancelled")
        if not response.content:
            raise ProviderError("Deepgram returned empty audio.", retryable=True, provider_code="empty_audio")
        return response.content

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "deepgram_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderNormalizedError("timeout", "Deepgram request timed out.", retryable=True)
        if isinstance(error, httpx.TransportError):
            return ProviderNormalizedError("network_error", "Deepgram network request failed.", retryable=True, safe_details=str(error)[:300])
        return super().normalize_error(error)

    def _tts_models(self) -> list[dict[str, Any]]:
        payload = self._models_payload()
        items = payload.get("tts") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderError("Deepgram returned an invalid TTS model catalog.", retryable=True, provider_code="invalid_catalog")
        return [item for item in items if isinstance(item, dict)]

    def _models_payload(self, *, force: bool = False) -> dict[str, Any]:
        if self._model_payload is not None and not force:
            return self._model_payload
        if not self.settings.api_key.strip():
            raise ConfigurationError("Deepgram API key is required.")
        response = self._request("GET", "/v1/models")
        if response.status_code >= 400:
            raise self._error(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProviderError("Deepgram returned an invalid models response.", retryable=True, provider_code="invalid_catalog")
        self._model_payload = payload
        return payload

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.client.request(method.upper(), url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError("Deepgram request timed out.", retryable=True, provider_code="timeout", technical_details=str(exc)[:300]) from exc
        except httpx.TransportError as exc:
            code = "cancelled" if self._cancelled else "network_error"
            raise ProviderError(
                "Deepgram request was cancelled." if self._cancelled else "Deepgram network request failed.",
                retryable=not self._cancelled,
                provider_code=code,
                technical_details=str(exc)[:300],
            ) from exc

    @staticmethod
    def _selected_model(settings: AppSettings) -> str:
        model = str(settings.model_id or "").strip()
        voice = str(settings.voice_id or "").strip()
        if model.startswith("aura-"):
            return model
        if voice.startswith("aura-"):
            return voice
        return model

    @staticmethod
    def _language(settings: AppSettings) -> str:
        return DeepgramProvider._base_language(str(settings.language_code or ""))

    @staticmethod
    def _base_language(value: str) -> str:
        normalized = str(value or "").strip().replace("_", "-").casefold()
        return normalized.split("-", 1)[0] if normalized else ""

    @staticmethod
    def _model_language(model_id: str) -> str:
        return str(model_id or "").rsplit("-", 1)[-1].casefold() if "-" in str(model_id or "") else ""

    @staticmethod
    def _simple_output(settings: AppSettings) -> str:
        return (settings.output_format or settings.file_extension.strip(".") or "mp3").split("_", 1)[0].casefold()

    @classmethod
    def _output_params(cls, settings: AppSettings) -> dict[str, str]:
        output = cls._simple_output(settings)
        if output == "mp3":
            return {"encoding": "mp3"}
        if output == "wav":
            return {"encoding": "linear16", "container": "wav"}
        if output == "opus":
            return {"encoding": "opus", "container": "ogg"}
        if output in {"flac", "aac"}:
            return {"encoding": output}
        if output == "pcm":
            return {"encoding": "linear16", "container": "none"}
        raise ConfigurationError(f"Unsupported Deepgram output format: {output}.")

    def _error(self, response: httpx.Response) -> ProviderError:
        request_id = response.headers.get("dg-request-id") or response.headers.get("x-request-id")
        detail = ""
        code = "deepgram_error"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("err_msg") or payload.get("message") or payload.get("details") or "")
                code = str(payload.get("err_code") or payload.get("category") or code).casefold().replace(" ", "_")
                request_id = request_id or str(payload.get("request_id") or "") or None
        except (ValueError, TypeError):
            detail = ""
        retryable = response.status_code in {408, 429, 500, 502, 503, 504}
        if response.status_code in {401, 403}:
            code = "invalid_api_key"
            retryable = False
        elif response.status_code == 402:
            code = "insufficient_credits"
            retryable = False
        elif response.status_code == 429:
            code = "quota_or_rate_limit"
        elif response.status_code in {400, 404, 413, 415, 422}:
            code = "invalid_request"
            retryable = False
        return ProviderError(
            f"Deepgram request failed with HTTP {response.status_code}.",
            retryable=retryable,
            http_status=response.status_code,
            provider_code=code,
            request_id=request_id,
            technical_details=(detail or response.text)[:300],
        )
