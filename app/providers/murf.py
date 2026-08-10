from __future__ import annotations

import base64
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

MURF_MODEL_ID = "GEN2"
MURF_OUTPUT_FORMATS = ("mp3", "wav", "flac", "ogg", "pcm")
MURF_SAMPLE_RATES = (8000, 24000, 44100, 48000)
MURF_MAX_TEXT_CHARACTERS = 3000


class MurfProvider(TTSProvider):
    provider_id = "murf"
    display_name = "Murf"
    BASE_URL = "https://api.murf.ai"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancelled = False
        self._voice_payload: list[dict[str, Any]] | None = None
        headers = {"Content-Type": "application/json"}
        if settings.api_key.strip():
            headers["api-key"] = settings.api_key.strip()
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
            supports_speed=True,
            supports_pitch=True,
            supports_cancellation=True,
            supported_output_formats=MURF_OUTPUT_FORMATS,
            credential_fields=("api_key",),
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.api_key.strip():
            return ProviderConfigurationResult(False, "Murf API key is required.")
        return ProviderConfigurationResult(True, "Murf API credential is configured.")

    def validate_synthesis_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        account = self.validate_configuration(settings)
        if not account.ok:
            return account
        model = str(settings.model_id or "").strip().upper()
        if model != MURF_MODEL_ID:
            return ProviderConfigurationResult(
                False,
                "Murf non-streaming synthesis requires the explicit GEN2 model.",
            )
        if not str(settings.voice_id or "").strip():
            return ProviderConfigurationResult(False, "Murf voice is required.")
        locale = self._locale(settings)
        if locale.casefold() == "da-dk":
            return ProviderConfigurationResult(
                False,
                "Murf Danish is not currently certified in S-Talking because the current public Gen2/Falcon 2 documentation does not explicitly document da-DK.",
            )
        output = self._simple_output(settings)
        if output not in MURF_OUTPUT_FORMATS:
            return ProviderConfigurationResult(False, f"Unsupported Murf output format: {output}.")
        sample_rate = self._sample_rate(settings)
        if sample_rate not in MURF_SAMPLE_RATES:
            return ProviderConfigurationResult(False, f"Unsupported Murf sample rate: {sample_rate}.")
        pitch = int(settings.provider_options.get("pitch", 0))
        if not -50 <= pitch <= 50:
            return ProviderConfigurationResult(False, "Murf pitch must be between -50 and 50.")
        variation = int(settings.provider_options.get("variation", 1))
        if not 0 <= variation <= 5:
            return ProviderConfigurationResult(False, "Murf variation must be between 0 and 5.")
        return ProviderConfigurationResult(True, "Murf Gen2 synthesis configuration is valid.")

    def test_connection(self) -> ProviderConfigurationResult:
        if not self.settings.api_key.strip():
            return ProviderConfigurationResult(False, "Murf API key is required.")
        voices = self._voices_payload(force=True)
        return ProviderConfigurationResult(True, f"Murf connected; {len(voices)} Gen2 voice(s) discovered.")

    def list_voices(self) -> list[dict[str, Any]]:
        requested = self._locale(self.settings)
        voices: list[dict[str, Any]] = []
        for item in self._voices_payload():
            voice_id = str(item.get("voiceId") or "").strip()
            if not voice_id:
                continue
            supported = item.get("supportedLocales") if isinstance(item.get("supportedLocales"), dict) else {}
            locales = [str(key) for key in supported]
            primary = str(item.get("locale") or "").strip()
            if primary and primary not in locales:
                locales.insert(0, primary)
            if requested and locales and requested.casefold() not in {value.casefold() for value in locales}:
                continue
            selected_locale = requested if requested and any(requested.casefold() == value.casefold() for value in locales) else primary
            selected_meta = next(
                (
                    value
                    for key, value in supported.items()
                    if str(key).casefold() == selected_locale.casefold() and isinstance(value, dict)
                ),
                {},
            )
            styles = (
                selected_meta.get("availableStyles")
                if isinstance(selected_meta, dict)
                else None
            )
            if not isinstance(styles, list):
                styles = []
            voices.append(
                {
                    "voice_id": voice_id,
                    "name": str(item.get("displayName") or voice_id),
                    "language": selected_locale or (locales[0] if locales else None),
                    "category": "murf-gen2",
                    "description": str(item.get("description") or ""),
                    "labels": {
                        "gender": str(item.get("gender") or ""),
                        "locales": ",".join(locales),
                        "styles": ",".join(str(style) for style in styles if style),
                    },
                    "compatible_model_ids": [MURF_MODEL_ID],
                }
            )
        return voices

    def list_models(self) -> list[dict[str, Any]]:
        languages = sorted(self._all_locales(), key=str.casefold) if self._voice_payload is not None else []
        return [
            {
                "model_id": MURF_MODEL_ID,
                "name": "Murf Gen2 (non-streaming)",
                "languages": languages,
                "can_do_text_to_speech": True,
                "maximum_text_length": MURF_MAX_TEXT_CHARACTERS,
            }
        ]

    def list_languages(self) -> list[dict[str, str]]:
        return [
            {"language_code": locale, "name": locale}
            for locale in sorted(self._all_locales(), key=str.casefold)
        ]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_synthesis_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        if len(text) > MURF_MAX_TEXT_CHARACTERS:
            raise ProviderError(
                f"Murf input exceeds {MURF_MAX_TEXT_CHARACTERS:,} characters.",
                retryable=False,
                provider_code="input_too_large",
            )

        payload: dict[str, Any] = {
            "text": text,
            "voiceId": settings.voice_id,
            "format": self._simple_output(settings).upper(),
            "modelVersion": MURF_MODEL_ID,
            "sampleRate": self._sample_rate(settings),
            "channelType": "MONO",
            "encodeAsBase64": True,
            "variation": int(settings.provider_options.get("variation", 1)),
        }
        locale = self._locale(settings)
        if locale:
            payload["locale"] = locale
        rate = round((float(settings.speed) - 1.0) * 100)
        if rate:
            payload["rate"] = rate
        pitch = int(settings.provider_options.get("pitch", 0))
        if pitch:
            payload["pitch"] = pitch
        style = str(settings.provider_options.get("style") or "").strip()
        if style:
            payload["style"] = style

        self._cancelled = False
        response = self._request("POST", "/v1/speech/generate", json=payload)
        if response.status_code >= 400:
            raise self._error(response)
        if self._cancelled:
            raise ProviderError("Murf request was cancelled.", retryable=False, provider_code="cancelled")
        result = response.json()
        if not isinstance(result, dict):
            raise ProviderError("Murf returned an invalid synthesis response.", retryable=True, provider_code="invalid_response")
        encoded = str(result.get("encodedAudio") or "").strip()
        if not encoded:
            raise ProviderError(
                "Murf did not return zero-retention base64 audio.",
                retryable=True,
                provider_code="empty_audio",
            )
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                "Murf returned invalid base64 audio.",
                retryable=True,
                provider_code="invalid_audio",
                technical_details=str(exc)[:300],
            ) from exc
        if not audio:
            raise ProviderError("Murf returned empty audio.", retryable=True, provider_code="empty_audio")
        return audio

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "murf_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderNormalizedError("timeout", "Murf request timed out.", retryable=True)
        if isinstance(error, httpx.TransportError):
            return ProviderNormalizedError(
                "network_error",
                "Murf network request failed.",
                retryable=True,
                safe_details=str(error)[:300],
            )
        return super().normalize_error(error)

    def _voices_payload(self, *, force: bool = False) -> list[dict[str, Any]]:
        if self._voice_payload is not None and not force:
            return self._voice_payload
        if not self.settings.api_key.strip():
            raise ConfigurationError("Murf API key is required.")
        response = self._request("GET", "/v1/speech/voices", params={"model": "gen2"})
        if response.status_code >= 400:
            raise self._error(response)
        payload = response.json()
        if not isinstance(payload, list):
            raise ProviderError("Murf returned an invalid voice catalog.", retryable=True, provider_code="invalid_catalog")
        self._voice_payload = [item for item in payload if isinstance(item, dict)]
        return self._voice_payload

    def _all_locales(self) -> set[str]:
        values: set[str] = set()
        for item in self._voices_payload():
            primary = str(item.get("locale") or "").strip()
            if primary:
                values.add(primary)
            supported = item.get("supportedLocales")
            if isinstance(supported, dict):
                values.update(str(key) for key in supported if str(key).strip())
        return values

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.client.request(method.upper(), url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Murf request timed out.",
                retryable=True,
                provider_code="timeout",
                technical_details=str(exc)[:300],
            ) from exc
        except httpx.TransportError as exc:
            code = "cancelled" if self._cancelled else "network_error"
            raise ProviderError(
                "Murf request was cancelled." if self._cancelled else "Murf network request failed.",
                retryable=not self._cancelled,
                provider_code=code,
                technical_details=str(exc)[:300],
            ) from exc

    @staticmethod
    def _simple_output(settings: AppSettings) -> str:
        return (
            settings.output_format
            or settings.file_extension.strip(".")
            or "wav"
        ).split("_", 1)[0].casefold()

    @staticmethod
    def _locale(settings: AppSettings) -> str:
        raw = str(settings.language_code or "").strip().replace("_", "-")
        if raw.casefold() == "da":
            return "da-DK"
        if raw.casefold() == "en":
            return "en-US"
        if len(raw) == 5 and raw[2] == "-":
            return f"{raw[:2].lower()}-{raw[3:].upper()}"
        return raw

    @staticmethod
    def _sample_rate(settings: AppSettings) -> int:
        return int(settings.provider_options.get("sample_rate", 44100))

    @staticmethod
    def _error(response: httpx.Response) -> ProviderError:
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        detail = ""
        code = "murf_error"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("error") or payload.get("detail") or "")
                code = str(payload.get("code") or code).casefold().replace(" ", "_")
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
        elif response.status_code in {400, 404, 422}:
            code = "invalid_request"
            retryable = False
        return ProviderError(
            f"Murf request failed with HTTP {response.status_code}.",
            retryable=retryable,
            http_status=response.status_code,
            provider_code=code,
            request_id=request_id,
            technical_details=(detail or response.text)[:300],
        )
