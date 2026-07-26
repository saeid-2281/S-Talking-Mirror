from __future__ import annotations

import random
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.elevenlabs import ProviderErrorInfo
from app.models.pronunciation_dictionary import PronunciationRule
from app.providers.base import TTSProvider

SECRET_VALUE = re.compile(r"(sk_[A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+)", re.IGNORECASE)


class ElevenLabsProvider(TTSProvider):
    BASE_URL = "https://api.elevenlabs.io"

    def __init__(self, settings: AppSettings) -> None:
        if not settings.api_key:
            raise ConfigurationError(
                "ElevenLabs API key is missing. Set it in settings.json or ELEVENLABS_API_KEY."
            )
        self.settings = settings
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=settings.timeout_seconds,
            headers={"xi-api-key": settings.api_key},
        )
        self._cancelled = False

    def close(self) -> None:
        self.client.close()

    def cancel(self) -> None:
        self._cancelled = True
        try:
            self.client.close()
        except Exception:
            pass

    def __enter__(self) -> "ElevenLabsProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: ProviderError | None = None
        for attempt in range(self.settings.max_retries + 1):
            if self._cancelled:
                raise self._cancelled_error()
            try:
                response = self.client.request(method, url, **kwargs)
                if response.status_code < 400:
                    return response
                error = self._error_from_response(response)
                provider_error = self._provider_error(error)
                if not error.retryable:
                    raise provider_error
                retry_after = response.headers.get("retry-after")
                delay = self._retry_delay(attempt, retry_after)
                last_error = provider_error
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError) as exc:
                if self._cancelled:
                    raise self._cancelled_error() from exc
                error = self._error_from_exception(exc)
                delay = self._retry_delay(attempt, None)
                last_error = self._provider_error(error)
            if attempt < self.settings.max_retries:
                self._interruptible_sleep(delay)
        raise last_error or ProviderError("ElevenLabs request failed after retries.", retryable=True)

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._cancelled:
                raise self._cancelled_error()
            time.sleep(min(0.1, max(deadline - time.monotonic(), 0)))

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), 60.0)
            except ValueError:
                pass
        return min(2**attempt + random.uniform(0, 0.25), 30.0)

    def _error_from_response(self, response: httpx.Response) -> ProviderErrorInfo:
        text = self._safe_text(response.text[:500])
        provider_code = None
        message = text
        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict):
                provider_code = detail.get("code") or detail.get("status") or detail.get("type")
                message = str(detail.get("message") or text)
        except Exception:
            pass
        code, user_message, retryable = self._classify(response.status_code, str(provider_code or ""), message)
        return ProviderErrorInfo(
            code=code,
            message=user_message,
            retryable=retryable,
            http_status=response.status_code,
            provider_code=str(provider_code) if provider_code else None,
            request_id=response.headers.get("request-id") or response.headers.get("x-request-id"),
            technical_details=f"ElevenLabs HTTP {response.status_code}: {message}",
        )

    def _error_from_exception(self, exc: Exception) -> ProviderErrorInfo:
        if isinstance(exc, httpx.TimeoutException):
            return ProviderErrorInfo("timeout", "ElevenLabs request timed out.", True, technical_details=str(exc))
        return ProviderErrorInfo("network_failure", "Network error while contacting ElevenLabs.", True, technical_details=str(exc))

    def _provider_error(self, error: ProviderErrorInfo) -> ProviderError:
        return ProviderError(
            error.message,
            retryable=error.retryable,
            http_status=error.http_status,
            provider_code=error.provider_code or error.code,
            request_id=error.request_id,
            technical_details=self._safe_text(error.technical_details or error.message),
        )

    def _cancelled_error(self) -> ProviderError:
        return ProviderError(
            "ElevenLabs request cancelled by user.",
            retryable=False,
            provider_code="cancelled",
            technical_details="cancelled request",
        )

    def _classify(self, status: int, provider_code: str, message: str) -> tuple[str, str, bool]:
        text = f"{provider_code} {message}".lower()
        if status in {401, 403} and ("api" in text or "auth" in text or "key" in text):
            return "invalid_api_key", "Invalid ElevenLabs API key.", False
        if "quota" in text or "character" in text and "exceed" in text:
            return "insufficient_quota", "ElevenLabs character quota is insufficient.", False
        if "paid" in text or "subscription" in text or "upgrade" in text:
            return "paid_plan_required", "This ElevenLabs voice or model requires a paid plan.", False
        if "voice" in text and ("not found" in text or "does not exist" in text or status == 404):
            return "voice_not_found", "Selected ElevenLabs voice was not found or is inaccessible.", False
        if "model" in text and ("not found" in text or "does not exist" in text):
            return "model_not_found", "Selected ElevenLabs model was not found.", False
        if status == 403:
            return "permission_denied", "Permission denied by ElevenLabs.", False
        if status == 429:
            return "rate_limit", "ElevenLabs rate limit reached.", True
        if status in {408, 409, 500, 502, 503, 504}:
            return "server_error", "Temporary ElevenLabs server error.", True
        return "provider_error", "ElevenLabs request failed.", False

    @staticmethod
    def _safe_text(value: str) -> str:
        return SECRET_VALUE.sub("[REDACTED]", value.replace("\r", " ").replace("\n", " ")[:500])

    def _tts_payload(self, text: str, settings: AppSettings) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "text": text,
            "model_id": settings.model_id,
            "voice_settings": {
                "stability": settings.stability,
                "similarity_boost": settings.similarity_boost,
                "style": settings.style,
                "use_speaker_boost": settings.use_speaker_boost,
                "speed": settings.speed,
            },
        }
        if settings.language_code:
            payload["language_code"] = settings.language_code
        if settings.pronunciation_dictionary_locators:
            payload["pronunciation_dictionary_locators"] = settings.pronunciation_dictionary_locators
        return payload

    def synthesize_with_metadata(self, text: str, settings: AppSettings) -> dict[str, Any]:
        if not settings.voice_id:
            raise ConfigurationError("voice_id is missing in settings.json")
        payload = self._tts_payload(text, settings)
        response = self._request(
            "POST",
            f"/v1/text-to-speech/{settings.voice_id}",
            params={"output_format": settings.output_format},
            json=payload,
            headers={"accept": "audio/mpeg"},
        )
        if not response.content:
            raise ProviderError(
                "ElevenLabs returned an empty audio response.",
                retryable=True,
                provider_code="empty_audio",
                technical_details="malformed/empty audio response",
            )
        return {
            "audio": response.content,
            "request_id": response.headers.get("request-id") or response.headers.get("x-request-id"),
            "character_cost": response.headers.get("character-cost") or response.headers.get("x-character-cost"),
            "payload": payload,
        }

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        return bytes(self.synthesize_with_metadata(text, settings)["audio"])

    def list_voices(self) -> list[dict[str, Any]]:
        voices: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100, "include_total_count": False}
            if page_token:
                params["page_token"] = page_token
            response = self._request("GET", "/v2/voices", params=params)
            data = response.json()
            voices.extend(data.get("voices", []))
            if not data.get("has_more"):
                break
            page_token = data.get("next_page_token")
            if not page_token:
                break
        return [
            {
                "voice_id": voice.get("voice_id"),
                "name": voice.get("name"),
                "category": voice.get("category"),
                "description": voice.get("description"),
                "labels": voice.get("labels", {}),
                "preview_url": voice.get("preview_url"),
                "available_for_tiers": voice.get("available_for_tiers", []),
                "compatible_model_ids": voice.get("high_quality_base_model_ids", []),
                "verified_languages": voice.get("verified_languages", []),
                "is_owner": voice.get("is_owner"),
            }
            for voice in voices
        ]

    def list_models(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/models")
        models = response.json()
        return [
            {
                "model_id": model.get("model_id"),
                "name": model.get("name"),
                "can_do_text_to_speech": model.get("can_do_text_to_speech", False),
                "languages": model.get("languages", []),
                "can_use_style": model.get("can_use_style", False),
                "can_use_speaker_boost": model.get("can_use_speaker_boost", False),
                "maximum_text_length": model.get("maximum_text_length"),
                "model_rates": model.get("model_rates", {}),
            }
            for model in models
            if model.get("can_do_text_to_speech", False)
        ]

    def get_subscription(self) -> dict[str, Any]:
        return dict(self._request("GET", "/v1/user/subscription").json())

    def list_pronunciation_dictionaries(self) -> list[dict[str, Any]]:
        dictionaries: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100, "include_archived": False}
            if cursor:
                params["cursor"] = cursor
            response = self._request("GET", "/v1/pronunciation-dictionaries", params=params)
            data = response.json()
            items = data.get("pronunciation_dictionaries", data if isinstance(data, list) else [])
            dictionaries.extend(self._normalize_dictionary(item) for item in items if isinstance(item, dict))
            cursor = data.get("next_cursor") or data.get("next_page_token")
            if not data.get("has_more") or not cursor:
                break
        return dictionaries

    def get_pronunciation_dictionary(self, dictionary_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/v1/pronunciation-dictionaries/{dictionary_id}")
        data = response.json()
        return self._normalize_dictionary(data if isinstance(data, dict) else {})

    def download_pronunciation_dictionary_version(self, dictionary_id: str, version_id: str) -> bytes:
        response = self._request("GET", f"/v1/pronunciation-dictionaries/{dictionary_id}/{version_id}/download")
        return response.content

    def create_pronunciation_dictionary_from_rules(
        self,
        *,
        name: str,
        rules: list[PronunciationRule],
        description: str | None = None,
        workspace_access: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "rules": [self._rule_payload(rule) for rule in rules if rule.enabled]}
        if description:
            payload["description"] = description
        if workspace_access:
            payload["workspace_access"] = workspace_access
        response = self._request("POST", "/v1/pronunciation-dictionaries/add-from-rules", json=payload)
        return self._normalize_dictionary(response.json())

    def create_pronunciation_dictionary_from_file(
        self,
        path: Path,
        *,
        name: str,
        description: str | None = None,
        workspace_access: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"name": name}
        if description:
            data["description"] = description
        if workspace_access:
            data["workspace_access"] = workspace_access
        with path.open("rb") as handle:
            files = {"file": (path.name, handle, "application/pls+xml")}
            response = self._request("POST", "/v1/pronunciation-dictionaries/add-from-file", data=data, files=files)
        return self._normalize_dictionary(response.json())

    def add_pronunciation_dictionary_rules(self, dictionary_id: str, rules: list[PronunciationRule]) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/v1/pronunciation-dictionaries/{dictionary_id}/add-rules",
            json={"rules": [self._rule_payload(rule) for rule in rules if rule.enabled]},
        )
        return self._normalize_dictionary(response.json())

    def set_pronunciation_dictionary_rules(self, dictionary_id: str, rules: list[PronunciationRule]) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/v1/pronunciation-dictionaries/{dictionary_id}/set-rules",
            json={"rules": [self._rule_payload(rule) for rule in rules if rule.enabled]},
        )
        return self._normalize_dictionary(response.json())

    def remove_pronunciation_dictionary_rules(self, dictionary_id: str, rule_strings: list[str]) -> dict[str, Any]:
        response = self._request(
            "POST",
            f"/v1/pronunciation-dictionaries/{dictionary_id}/remove-rules",
            json={"rule_strings": rule_strings},
        )
        return self._normalize_dictionary(response.json())

    def update_pronunciation_dictionary(
        self,
        dictionary_id: str,
        *,
        name: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if archived is not None:
            payload["archived"] = archived
        response = self._request("PATCH", f"/v1/pronunciation-dictionaries/{dictionary_id}", json=payload)
        return self._normalize_dictionary(response.json())

    def delete_pronunciation_dictionary(self, dictionary_id: str) -> None:
        self.update_pronunciation_dictionary(dictionary_id, archived=True)

    @staticmethod
    def _normalize_dictionary(item: dict[str, Any]) -> dict[str, Any]:
        latest_version = item.get("latest_version") if isinstance(item.get("latest_version"), dict) else {}
        version_id = (
            item.get("version_id")
            or item.get("latest_version_id")
            or latest_version.get("version_id")
            or latest_version.get("id")
        )
        return {
            "dictionary_id": item.get("id") or item.get("pronunciation_dictionary_id") or item.get("dictionary_id"),
            "name": item.get("name"),
            "version_id": version_id,
            "language_code": item.get("language_code") or item.get("language"),
            "model_compatibility": item.get("model_compatibility") or "provider_catalog",
            "rule_count": item.get("latest_version_rules_num") or item.get("rule_count") or latest_version.get("rules_num"),
            "permission_on_resource": item.get("permission_on_resource"),
            "archived": item.get("archived"),
        }

    @staticmethod
    def _rule_payload(rule: PronunciationRule) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "string_to_replace": rule.source,
            "case_sensitive": rule.case_sensitive,
            "word_boundaries": rule.word_boundaries,
        }
        if rule.rule_type == "phoneme":
            payload.update({"type": "phoneme", "phoneme": rule.replacement, "alphabet": rule.alphabet or "ipa"})
        else:
            payload.update({"type": "alias", "alias": rule.replacement})
        return payload
