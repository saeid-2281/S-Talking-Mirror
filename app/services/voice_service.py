from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.exceptions import ConfigurationError, ProviderError
from app.models.domain import AppSettings
from app.models.elevenlabs import ProviderCapability, ProviderConnectionResult
from app.models.persistence import VoiceRecord
from app.provider_factory import create_provider
from app.repositories.voice_repository import VoiceRepository
from app.services.pronunciation_service import PronunciationService
from app.services.preview_service import PreviewService


@dataclass(frozen=True)
class VoiceItem:
    provider: str
    voice_id: str
    name: str
    language: str | None
    category: str | None
    description: str
    labels: dict[str, str]
    is_favorite: bool
    preview_url: str | None = None
    available_for_tiers: tuple[str, ...] = ()
    compatible_model_ids: tuple[str, ...] = ()
    is_owner: bool | None = None

    @classmethod
    def from_record(cls, record: VoiceRecord) -> "VoiceItem":
        try:
            metadata = json.loads(record.metadata_json or "{}")
        except json.JSONDecodeError:
            metadata = {}
        labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
        tiers = metadata.get("available_for_tiers") or []
        models = metadata.get("compatible_model_ids") or metadata.get("high_quality_base_model_ids") or []
        return cls(
            provider=record.provider,
            voice_id=record.voice_id,
            name=record.name,
            language=record.language,
            category=record.category,
            description=str(metadata.get("description") or ""),
            labels={str(key): str(value) for key, value in labels.items()},
            is_favorite=bool(record.is_favorite),
            preview_url=str(metadata.get("preview_url") or "") or None,
            available_for_tiers=tuple(str(value) for value in tiers if value),
            compatible_model_ids=tuple(str(value) for value in models if value),
            is_owner=metadata.get("is_owner") if isinstance(metadata.get("is_owner"), bool) else None,
        )

    @property
    def accent(self) -> str:
        return self.labels.get("accent", "")

    @property
    def gender(self) -> str:
        return self.labels.get("gender", "")

    @property
    def age(self) -> str:
        return self.labels.get("age", "")

    @property
    def use_case(self) -> str:
        return self.labels.get("use_case", "") or self.labels.get("description", "")


@dataclass(frozen=True)
class VoiceModelItem:
    model_id: str
    name: str
    languages: tuple[str, ...]
    can_do_text_to_speech: bool = True
    can_use_style: bool = False
    can_use_speaker_boost: bool = False
    maximum_text_length: int | None = None
    cost_factor: float | None = None


@dataclass(frozen=True)
class AccountUsage:
    tier: str | None
    status: str | None
    character_count: int | None
    character_limit: int | None

    @property
    def remaining_characters(self) -> int | None:
        if self.character_count is None or self.character_limit is None:
            return None
        return max(self.character_limit - self.character_count, 0)


@dataclass(frozen=True)
class VoiceCatalog:
    voices: tuple[VoiceItem, ...]
    models: tuple[VoiceModelItem, ...]
    account: AccountUsage | None
    refreshed_at: str | None = None


class VoiceService:
    """Loads, caches, filters, favorites, and previews provider voices."""

    def __init__(self, repository: VoiceRepository, preview_directory: Path, preview_service: PreviewService | None = None) -> None:
        self.repository = repository
        self.preview_directory = preview_directory
        self.preview_directory.mkdir(parents=True, exist_ok=True)
        self.preview_service = preview_service or PreviewService(preview_directory / "index.json")
        self._catalog_cache: dict[tuple[str, str], tuple[float, VoiceCatalog]] = {}
        self.cache_ttl_seconds = 300.0

    def refresh_catalog(self, settings: AppSettings) -> VoiceCatalog:
        key = self._cache_key(settings)
        cached = self._catalog_cache.get(key)
        if cached and time.monotonic() - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        provider = create_provider(settings)
        try:
            raw_voices = provider.list_voices()
            raw_models = provider.list_models()
            account_data = self._optional_provider_call(provider, "get_subscription")
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

        for voice in raw_voices:
            voice_id = str(voice.get("voice_id") or "").strip()
            if not voice_id:
                continue
            labels = voice.get("labels") if isinstance(voice.get("labels"), dict) else {}
            language = self._language_from(labels, voice)
            self.repository.upsert(
                provider=settings.provider,
                voice_id=voice_id,
                name=str(voice.get("name") or voice_id),
                language=language,
                category=str(voice.get("category") or "") or None,
                metadata={
                    "description": voice.get("description") or "",
                    "labels": labels,
                    "preview_url": voice.get("preview_url"),
                    "available_for_tiers": voice.get("available_for_tiers") or [],
                    "compatible_model_ids": voice.get("compatible_model_ids")
                    or voice.get("high_quality_base_model_ids")
                    or [],
                    "is_owner": voice.get("is_owner"),
                },
            )
        catalog = VoiceCatalog(
            voices=tuple(self.list(provider=settings.provider)),
            models=tuple(self._normalize_models(raw_models)),
            account=self._normalize_account(account_data),
            refreshed_at=datetime.now(timezone.utc).isoformat(),
        )
        self._catalog_cache[key] = (time.monotonic(), catalog)
        return catalog

    def invalidate_provider_cache(self, settings: AppSettings | None = None) -> None:
        if settings is None:
            self._catalog_cache.clear()
            return
        self._catalog_cache.pop(self._cache_key(settings), None)

    def cached_catalog(self, settings: AppSettings) -> VoiceCatalog | None:
        cached = self._catalog_cache.get(self._cache_key(settings))
        if cached and time.monotonic() - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        return None

    def test_connection(self, settings: AppSettings) -> ProviderConnectionResult:
        if settings.provider != "elevenlabs":
            return ProviderConnectionResult("network_error", "Connection test is only available for ElevenLabs.")
        try:
            catalog = self.refresh_catalog(settings)
            capability = ProviderCapability(
                voice_count=len(catalog.voices),
                tts_model_count=sum(1 for model in catalog.models if model.can_do_text_to_speech),
                account_tier=catalog.account.tier if catalog.account else None,
                character_count=catalog.account.character_count if catalog.account else None,
                character_limit=catalog.account.character_limit if catalog.account else None,
            )
            remaining = capability.remaining_characters
            quota = f" {remaining:,} characters remaining." if remaining is not None else ""
            return ProviderConnectionResult(
                "connected",
                f"Connected. {capability.voice_count} voice(s), {capability.tts_model_count} TTS model(s).{quota}",
                capability,
            )
        except ProviderError as exc:
            status = self._connection_status(exc)
            return ProviderConnectionResult(
                status,
                exc.user_message,
                retryable=exc.retryable,
                http_status=exc.http_status,
                provider_code=exc.provider_code,
                request_id=exc.request_id,
            )
        except ConfigurationError as exc:
            return ProviderConnectionResult("invalid_key", str(exc), retryable=False)
        except Exception as exc:
            return ProviderConnectionResult("network_error", f"Network error: {exc}", retryable=True)

    def refresh(self, settings: AppSettings) -> list[VoiceItem]:
        """Backward-compatible voice-only refresh."""
        return list(self.refresh_catalog(settings).voices)

    def list(
        self,
        *,
        provider: str,
        query: str = "",
        favorites_only: bool = False,
        sort_mode: str = "provider_order",
        language: str | None = None,
        category: str | None = None,
        accent: str | None = None,
        gender: str | None = None,
        age: str | None = None,
    ) -> list[VoiceItem]:
        items = [
            VoiceItem.from_record(record)
            for record in self.repository.list(
                provider=provider,
                language=language or None,
                favorites_only=favorites_only,
            )
        ]
        needle = query.strip().casefold()
        result: list[VoiceItem] = []
        for item in items:
            if needle and needle not in self._search_text(item):
                continue
            if category and item.category != category:
                continue
            if accent and item.accent != accent:
                continue
            if gender and item.gender != gender:
                continue
            if age and item.age != age:
                continue
            result.append(item)
        return self._sort_items(result, sort_mode)

    def available_filters(self, provider: str) -> dict[str, list[str]]:
        items = self.list(provider=provider)
        return {
            "language": self._distinct(item.language for item in items),
            "category": self._distinct(item.category for item in items),
            "accent": self._distinct(item.accent for item in items),
            "gender": self._distinct(item.gender for item in items),
            "age": self._distinct(item.age for item in items),
        }

    def set_favorite(self, item: VoiceItem, favorite: bool) -> None:
        self.repository.set_favorite(item.provider, item.voice_id, favorite)

    def preview(self, item: VoiceItem, text: str, settings: AppSettings) -> Path:
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("Preview text cannot be empty.")
        preview_settings = settings.model_copy(update={"voice_id": item.voice_id})
        self.validate_selection(item, preview_settings)
        cached = self.preview_service.find_cached(item.provider, item.voice_id, preview_settings.model_id, normalized_text, preview_settings)
        if cached is not None:
            return cached.file_path
        extension = ".mp3" if item.provider == "elevenlabs" else ".wav"
        cache_key = self._preview_cache_key(item, normalized_text, preview_settings)
        safe_name = re.sub(r"[^\w.-]+", "_", item.name, flags=re.UNICODE).strip("._") or "voice"
        target = self.preview_directory / f"{item.provider}-{safe_name}-{cache_key[:16]}{extension}"
        if target.exists() and target.stat().st_size > 0:
            return target

        provider = create_provider(preview_settings)
        try:
            prepared = PronunciationService().prepare(normalized_text, preview_settings)
            audio = provider.synthesize(prepared.provider_text, preview_settings)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            if not audio:
                raise ProviderError("Provider returned an empty preview.", retryable=True, provider_code="empty_audio")
            tmp.write_bytes(audio)
            tmp.replace(target)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        self.preview_service.index_preview(
            provider=item.provider,
            voice_id=item.voice_id,
            model_id=preview_settings.model_id,
            preview_text=normalized_text,
            settings=preview_settings,
            file_path=target,
            duration_seconds=None,
        )
        return target

    def saved_previews(self, item: VoiceItem):
        return self.preview_service.list_for_voice(item.provider, item.voice_id)

    def mark_preview_played(self, record) -> None:
        self.preview_service.mark_played(record)

    def delete_preview(self, record) -> None:
        self.preview_service.delete(record)

    def clear_previews_for_voice(self, item: VoiceItem) -> int:
        return self.preview_service.clear_for_voice(item.provider, item.voice_id)

    def validate_selection(self, item: VoiceItem, settings: AppSettings) -> None:
        if item.provider != "elevenlabs":
            return
        catalog = self.cached_catalog(settings)
        voices = {voice.voice_id: voice for voice in catalog.voices} if catalog else {}
        models = {model.model_id: model for model in catalog.models} if catalog else {}
        if voices and item.voice_id not in voices:
            raise ProviderError("Selected ElevenLabs voice was not found or is inaccessible.", provider_code="voice_not_found")
        selected = voices.get(item.voice_id, item)
        if models and settings.model_id not in models:
            raise ProviderError("Selected ElevenLabs model was not found.", provider_code="model_not_found")
        model = models.get(settings.model_id)
        if model and not model.can_do_text_to_speech:
            raise ProviderError("Selected ElevenLabs model does not support text-to-speech.", provider_code="model_not_found")
        if selected.compatible_model_ids and settings.model_id not in selected.compatible_model_ids:
            raise ProviderError("Selected ElevenLabs model is not compatible with this voice.", provider_code="model_voice_incompatible")

    def cached_preview_path(self, item: VoiceItem, text: str, settings: AppSettings) -> Path | None:
        normalized_text = text.strip()
        if not normalized_text:
            return None
        preview_settings = settings.model_copy(update={"voice_id": item.voice_id})
        extension = ".mp3" if item.provider == "elevenlabs" else ".wav"
        cache_key = self._preview_cache_key(item, normalized_text, preview_settings)
        safe_name = re.sub(r"[^\w.-]+", "_", item.name, flags=re.UNICODE).strip("._") or "voice"
        target = self.preview_directory / f"{item.provider}-{safe_name}-{cache_key[:16]}{extension}"
        return target if target.exists() and target.stat().st_size > 0 else None

    @staticmethod
    def _sort_items(items: list[VoiceItem], sort_mode: str) -> list[VoiceItem]:
        if sort_mode == "name":
            return sorted(items, key=lambda item: item.name.casefold())
        if sort_mode == "language":
            return sorted(items, key=lambda item: ((item.language or "").casefold(), item.name.casefold()))
        if sort_mode == "recent":
            return sorted(items, key=lambda item: item.voice_id, reverse=True)
        return items

    @staticmethod
    def _optional_provider_call(provider: Any, method_name: str) -> Any:
        method = getattr(provider, method_name, None)
        if not callable(method):
            return None
        try:
            return method()
        except Exception:
            return None

    @staticmethod
    def _normalize_models(raw_models: list[dict[str, Any]]) -> list[VoiceModelItem]:
        result: list[VoiceModelItem] = []
        for model in raw_models:
            model_id = str(model.get("model_id") or "").strip()
            if not model_id:
                continue
            languages: list[str] = []
            for value in model.get("languages") or []:
                if isinstance(value, dict):
                    language = value.get("language_id") or value.get("language") or value.get("name")
                else:
                    language = value
                if language:
                    languages.append(str(language))
            result.append(
                VoiceModelItem(
                    model_id=model_id,
                    name=str(model.get("name") or model_id),
                    languages=tuple(languages),
                    can_do_text_to_speech=bool(model.get("can_do_text_to_speech", True)),
                    can_use_style=bool(model.get("can_use_style", False)),
                    can_use_speaker_boost=bool(model.get("can_use_speaker_boost", False)),
                    maximum_text_length=VoiceService._optional_int(model.get("maximum_text_length")),
                    cost_factor=VoiceService._optional_float(model.get("model_rates", {}).get("character_cost_multiplier") if isinstance(model.get("model_rates"), dict) else model.get("cost_factor")),
                )
            )
        return result

    @staticmethod
    def _normalize_account(data: Any) -> AccountUsage | None:
        if not isinstance(data, dict):
            return None
        return AccountUsage(
            tier=str(data.get("tier") or "") or None,
            status=str(data.get("status") or "") or None,
            character_count=VoiceService._optional_int(data.get("character_count")),
            character_limit=VoiceService._optional_int(data.get("character_limit")),
        )

    @staticmethod
    def _connection_status(error: ProviderError) -> str:
        code = (error.provider_code or "").lower()
        if code == "invalid_api_key":
            return "invalid_key"
        if code in {"permission_denied", "paid_plan_required"}:
            return "permission_issue"
        return "network_error" if error.retryable else "permission_issue"

    @staticmethod
    def _cache_key(settings: AppSettings) -> tuple[str, str]:
        digest = hashlib.sha256((settings.api_key or "").encode("utf-8")).hexdigest()
        return settings.provider, digest

    @staticmethod
    def _preview_cache_key(item: VoiceItem, text: str, settings: AppSettings) -> str:
        payload = {
            "provider": item.provider,
            "voice_id": item.voice_id,
            "text": text,
            "model_id": settings.model_id,
            "stability": settings.stability,
            "similarity_boost": settings.similarity_boost,
            "style": settings.style,
            "speaker_boost": settings.use_speaker_boost,
            "speed": settings.speed,
            "language_code": settings.language_code,
            "output_format": settings.output_format,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _language_from(labels: dict[str, Any], voice: dict[str, Any]) -> str | None:
        for key in ("language", "locale"):
            value = labels.get(key) or voice.get(key)
            if value:
                return str(value)
        verified = voice.get("verified_languages")
        if isinstance(verified, list) and verified:
            first = verified[0]
            if isinstance(first, dict):
                value = first.get("language") or first.get("locale")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _search_text(item: VoiceItem) -> str:
        values = [
            item.name,
            item.voice_id,
            item.language or "",
            item.category or "",
            item.description,
            *item.labels.keys(),
            *item.labels.values(),
        ]
        return " ".join(values).casefold()

    @staticmethod
    def _distinct(values: Any) -> list[str]:
        return sorted({str(value) for value in values if value}, key=str.casefold)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None
