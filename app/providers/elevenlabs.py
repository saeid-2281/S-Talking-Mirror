from __future__ import annotations

import time
from typing import Any

import httpx

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.providers.base import TTSProvider


class ElevenLabsProvider(TTSProvider):
    BASE_URL = "https://api.elevenlabs.io"

    def __init__(self, settings: AppSettings) -> None:
        if not settings.api_key:
            raise ConfigurationError(
                "ElevenLabs API key is missing. Set it in settings.json or "
                "ELEVENLABS_API_KEY."
            )
        self.settings = settings
        self.client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=settings.timeout_seconds,
            headers={"xi-api-key": settings.api_key},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "ElevenLabsProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(self.settings.max_retries + 1):
            try:
                response = self.client.request(method, url, **kwargs)
                if response.status_code < 400:
                    return response

                retryable = response.status_code in {408, 409, 429, 500, 502, 503, 504}
                if not retryable:
                    raise ProviderError(
                        f"ElevenLabs returned HTTP {response.status_code}: "
                        f"{response.text[:500]}"
                    )

                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after else min(2**attempt, 30)
                last_error = ProviderError(
                    f"Retryable HTTP {response.status_code}: {response.text[:300]}"
                )

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                delay = min(2**attempt, 30)
                last_error = exc

            if attempt < self.settings.max_retries:
                time.sleep(delay)

        raise ProviderError(f"ElevenLabs request failed after retries: {last_error}")

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        if not settings.voice_id:
            raise ConfigurationError("voice_id is missing in settings.json")

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

        response = self._request(
            "POST",
            f"/v1/text-to-speech/{settings.voice_id}",
            params={"output_format": settings.output_format},
            json=payload,
            headers={"accept": "audio/mpeg"},
        )
        if not response.content:
            raise ProviderError("ElevenLabs returned an empty audio response.")
        return response.content

    def list_voices(self) -> list[dict]:
        response = self._request("GET", "/v2/voices", params={"page_size": 100})
        data = response.json()
        voices = data.get("voices", [])
        return [
            {
                "voice_id": voice.get("voice_id"),
                "name": voice.get("name"),
                "category": voice.get("category"),
                "description": voice.get("description"),
                "labels": voice.get("labels", {}),
            }
            for voice in voices
        ]

    def list_models(self) -> list[dict]:
        response = self._request("GET", "/v1/models")
        models = response.json()
        return [
            {
                "model_id": model.get("model_id"),
                "name": model.get("name"),
                "can_do_text_to_speech": model.get("can_do_text_to_speech", False),
                "languages": model.get("languages", []),
            }
            for model in models
            if model.get("can_do_text_to_speech", False)
        ]
