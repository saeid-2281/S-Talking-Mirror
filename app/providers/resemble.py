from __future__ import annotations

import base64
from typing import Any
from xml.sax.saxutils import escape

import httpx

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import (
    ProviderCapabilities,
    ProviderConfigurationResult,
    ProviderNormalizedError,
)
from app.providers.base import TTSProvider

RESEMBLE_OUTPUT_FORMATS = ("wav", "mp3")
RESEMBLE_MODEL_ID = "resemble-ultra"
RESEMBLE_PRECISIONS = ("MULAW", "PCM_16", "PCM_24", "PCM_32")
RESEMBLE_DOCUMENTED_LOCALES = (
    "af-za", "am-et", "ar-ae", "ar-eg", "ar-iq", "ar-kw", "ar-ma", "ar-qa",
    "ar-sa", "az-az", "bg-bg", "bn-bd", "bn-in", "bs-ba", "ca-es", "cmn-cn",
    "cs-cz", "da-dk", "de-de", "el-gr", "en-au", "en-ca", "en-gb", "en-hk",
    "en-ie", "en-in", "en-ke", "en-nz", "en-sg", "en-us", "en-za", "es-ar",
    "es-ch", "es-co", "es-cr", "es-cu", "es-do", "es-ec", "es-es", "es-mx",
    "es-pe", "es-pr", "es-py", "es-us", "es-ve", "et-ee", "eu-es", "fa-ir",
    "fi-fi", "fil-ph", "fr-be", "fr-ca", "fr-ch", "fr-fr", "ga-ie", "gu-in",
    "he-il", "hi-in", "hr-hr", "hu-hu", "hy-am", "id-id", "is-is", "it-it",
    "ja-jp", "jv-id", "ka-ge", "kk-kz", "km-kh", "kn-in", "ko-kr", "lt-lt",
    "lv-lv", "ml-in", "mn-mn", "mr-in", "ms-my", "mt-mt", "my-mm", "nb-no",
    "ne-np", "nl-be", "nl-nl", "pa-in", "pl-pl", "ps-af", "pt-br", "pt-pt",
    "ro-ro", "ru-ru", "si-lk", "sk-sk", "sl-si", "so-so", "sq-al", "sr-rs",
    "sv-se", "sw-ke", "ta-in", "ta-lk", "ta-my", "te-in", "th-th", "tr-tr",
    "uk-ua", "ur-pk", "vi-vn", "yue-cn", "zh-cn", "zh-hk", "zh-tw", "zu-za",
)


class ResembleProvider(TTSProvider):
    provider_id = "resemble"
    display_name = "Resemble AI"
    API_BASE_URL = "https://app.resemble.ai/api/v2"
    SYNTHESIS_URL = "https://f.cluster.resemble.ai/synthesize"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._cancelled = False
        headers = {"Content-Type": "application/json"}
        if settings.api_key.strip():
            headers["Authorization"] = f"Bearer {settings.api_key.strip()}"
        self.client = httpx.Client(timeout=settings.timeout_seconds, headers=headers)

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
            supports_ssml=True,
            supports_cancellation=True,
            supported_output_formats=RESEMBLE_OUTPUT_FORMATS,
            credential_fields=("api_key",),
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.api_key.strip():
            return ProviderConfigurationResult(False, "Resemble API key is required.")
        return ProviderConfigurationResult(True, "Resemble API credential is configured.")

    def validate_synthesis_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        account = self.validate_configuration(settings)
        if not account.ok:
            return account
        if not str(settings.voice_id or "").strip():
            return ProviderConfigurationResult(False, "Resemble voice UUID is required.")
        model = str(settings.model_id or "").strip()
        if model and model != RESEMBLE_MODEL_ID:
            return ProviderConfigurationResult(
                False,
                "Resemble selects the TTS model from the voice. Use the voice-managed Resemble Ultra catalog entry.",
            )
        output = self._simple_output(settings)
        if output not in RESEMBLE_OUTPUT_FORMATS:
            return ProviderConfigurationResult(False, f"Unsupported Resemble output format: {output}.")
        locale = self._locale(settings)
        if locale and locale not in RESEMBLE_DOCUMENTED_LOCALES:
            return ProviderConfigurationResult(
                False,
                f"Resemble locale {locale!r} is not in the current documented SSML locale contract.",
            )
        if float(settings.speed) != 1.0:
            return ProviderConfigurationResult(
                False,
                "Resemble numeric speed is not mapped by the current S-Talking adapter; use speed 1.0.",
            )
        precision = str(settings.provider_options.get("precision") or "PCM_32").strip().upper()
        if precision not in RESEMBLE_PRECISIONS:
            return ProviderConfigurationResult(False, f"Unsupported Resemble WAV precision: {precision}.")
        return ProviderConfigurationResult(
            True,
            "Resemble synthesis configuration is valid; the selected voice remains authoritative for language support.",
        )

    def test_connection(self) -> ProviderConfigurationResult:
        if not self.settings.api_key.strip():
            return ProviderConfigurationResult(False, "Resemble API key is required.")
        response = self._request(
            "GET",
            f"{self.API_BASE_URL}/voices",
            params={"page": 1, "page_size": 10, "advanced": "true"},
        )
        if response.status_code >= 400:
            raise self._error(response)
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise ProviderError(
                "Resemble returned an invalid voice catalog response.",
                retryable=True,
                provider_code="invalid_catalog",
            )
        return ProviderConfigurationResult(True, "Resemble connected; voice catalog is accessible.")

    def list_voices(self) -> list[dict[str, Any]]:
        if not self.settings.api_key.strip():
            raise ConfigurationError("Resemble API key is required.")
        voices: list[dict[str, Any]] = []
        for page in range(1, 101):
            response = self._request(
                "GET",
                f"{self.API_BASE_URL}/voices",
                params={"page": page, "page_size": 100, "advanced": "true"},
            )
            if response.status_code >= 400:
                raise self._error(response)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError(
                    "Resemble returned an invalid voice catalog.",
                    retryable=True,
                    provider_code="invalid_catalog",
                )
            items = payload.get("items")
            if not isinstance(items, list):
                raise ProviderError(
                    "Resemble returned an invalid voice catalog.",
                    retryable=True,
                    provider_code="invalid_catalog",
                )
            for item in items:
                if not isinstance(item, dict):
                    continue
                voice_id = str(
                    item.get("uuid")
                    or item.get("voice_uuid")
                    or item.get("id")
                    or ""
                ).strip()
                if not voice_id:
                    continue
                languages = self._voice_languages(item)
                voices.append(
                    {
                        "voice_id": voice_id,
                        "name": str(item.get("name") or item.get("display_name") or voice_id),
                        "language": languages[0] if languages else None,
                        "category": "resemble-voice",
                        "description": str(item.get("description") or item.get("status") or ""),
                        "preview_url": str(
                            item.get("preview_url")
                            or item.get("sample_url")
                            or item.get("audio_url")
                            or ""
                        ) or None,
                        "is_owner": bool(item.get("is_owner")) if "is_owner" in item else None,
                        "labels": {
                            "status": str(item.get("status") or ""),
                            "model": str(item.get("model") or item.get("model_version") or ""),
                            "languages": ",".join(languages),
                        },
                        # Resemble chooses the model from voice_uuid; do not
                        # enforce model/voice compatibility in S-Talking.
                        "compatible_model_ids": [],
                    }
                )
            num_pages = int(payload.get("num_pages") or page)
            if page >= num_pages:
                break
        return voices

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": RESEMBLE_MODEL_ID,
                "name": "Resemble Ultra (voice-managed)",
                "languages": list(RESEMBLE_DOCUMENTED_LOCALES),
                "can_do_text_to_speech": True,
            }
        ]

    def list_languages(self) -> list[dict[str, str]]:
        return [
            {"language_code": locale, "name": locale}
            for locale in RESEMBLE_DOCUMENTED_LOCALES
        ]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_synthesis_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        data = self._synthesis_data(text, settings)
        if len(data) > 3000:
            raise ConfigurationError("Resemble synchronous synthesis accepts at most 3,000 characters including SSML.")
        output = self._simple_output(settings)
        payload: dict[str, Any] = {
            "voice_uuid": settings.voice_id,
            "data": data,
            "output_format": output,
        }
        if output == "wav":
            payload["precision"] = str(
                settings.provider_options.get("precision") or "PCM_32"
            ).strip().upper()
        if bool(settings.provider_options.get("use_hd", False)):
            payload["use_hd"] = True
        if bool(settings.provider_options.get("apply_custom_pronunciations", False)):
            payload["apply_custom_pronunciations"] = True
        project_uuid = str(settings.provider_options.get("project_uuid") or "").strip()
        if project_uuid:
            payload["project_uuid"] = project_uuid

        self._cancelled = False
        response = self._request("POST", self.SYNTHESIS_URL, json=payload)
        if response.status_code >= 400:
            raise self._error(response)
        if self._cancelled:
            raise ProviderError("Resemble request was cancelled.", retryable=False, provider_code="cancelled")
        result = response.json()
        if not isinstance(result, dict) or result.get("success") is False:
            raise ProviderError(
                "Resemble synthesis returned an invalid response.",
                retryable=True,
                provider_code="invalid_response",
            )
        encoded = str(result.get("audio_content") or "").strip()
        if not encoded:
            raise ProviderError("Resemble returned empty audio.", retryable=True, provider_code="empty_audio")
        try:
            audio = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise ProviderError(
                "Resemble returned invalid base64 audio.",
                retryable=True,
                provider_code="invalid_audio",
                technical_details=str(exc)[:300],
            ) from exc
        if not audio:
            raise ProviderError("Resemble returned empty audio.", retryable=True, provider_code="empty_audio")
        return audio

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "resemble_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        if isinstance(error, httpx.TimeoutException):
            return ProviderNormalizedError("timeout", "Resemble request timed out.", retryable=True)
        if isinstance(error, httpx.TransportError):
            return ProviderNormalizedError(
                "network_error",
                "Resemble network request failed.",
                retryable=True,
                safe_details=str(error)[:300],
            )
        return super().normalize_error(error)

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self.client.request(method.upper(), url, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Resemble request timed out.",
                retryable=True,
                provider_code="timeout",
                technical_details=str(exc)[:300],
            ) from exc
        except httpx.TransportError as exc:
            code = "cancelled" if self._cancelled else "network_error"
            raise ProviderError(
                "Resemble request was cancelled." if self._cancelled else "Resemble network request failed.",
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
        raw = str(settings.language_code or "").strip().replace("_", "-").casefold()
        if raw == "da":
            return "da-dk"
        if raw == "en":
            return "en-us"
        return raw

    @classmethod
    def _synthesis_data(cls, text: str, settings: AppSettings) -> str:
        locale = cls._locale(settings)
        stripped = text.lstrip()
        if not locale or stripped.startswith("<speak"):
            return text
        return f'<speak version="1.1" xml:lang="{locale}">{escape(text)}</speak>'

    @staticmethod
    def _voice_languages(item: dict[str, Any]) -> list[str]:
        raw = (
            item.get("supported_languages")
            or item.get("languages")
            or item.get("locales")
            or ()
        )
        if isinstance(raw, str):
            raw = [raw]
        values: list[str] = []
        if isinstance(raw, (list, tuple)):
            for value in raw:
                if isinstance(value, dict):
                    code = value.get("locale") or value.get("language") or value.get("code")
                else:
                    code = value
                if code:
                    values.append(str(code))
        return values

    @staticmethod
    def _error(response: httpx.Response) -> ProviderError:
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        detail = ""
        code = "resemble_error"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("error") or payload.get("detail") or "")
                code = str(payload.get("code") or code).casefold().replace(" ", "_")
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
            f"Resemble request failed with HTTP {response.status_code}.",
            retryable=retryable,
            http_status=response.status_code,
            provider_code=code,
            request_id=request_id,
            technical_details=(detail or response.text)[:300],
        )
