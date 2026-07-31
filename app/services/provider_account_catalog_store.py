from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.domain import AppSettings
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem


@dataclass(frozen=True)
class ProviderCatalogSnapshotInfo:
    exists: bool
    stale: bool
    saved_at: str | None = None
    refreshed_at: str | None = None
    voice_count: int = 0
    model_count: int = 0
    account_tier: str | None = None
    remaining_characters: int | None = None
    character_limit: int | None = None

    @property
    def state_label(self) -> str:
        if not self.exists:
            return "Not cached"
        return "Stale" if self.stale else "Fresh"


class ProviderAccountCatalogStore:
    """Persist provider catalog snapshots per account without storing secrets.

    The on-disk identity combines provider, profile id, and a one-way API-key
    fingerprint. This prevents two saved accounts from sharing voice/model data
    while allowing the same account to reuse its most recent catalog after an
    application restart.
    """

    SCHEMA_VERSION = 1

    def __init__(self, root: Path, *, ttl_seconds: float = 300.0) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(0.0, float(ttl_seconds))

    def identity_for(self, settings: AppSettings) -> str:
        profile_id = str(settings.active_api_profile_id or "temporary")
        secret_digest = hashlib.sha256((settings.api_key or "").encode("utf-8")).hexdigest()
        payload = f"{settings.provider}:{profile_id}:{secret_digest}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def path_for(self, settings: AppSettings) -> Path:
        provider = self._safe_segment(settings.provider or "provider")
        profile = self._safe_segment(str(settings.active_api_profile_id or "temporary"))
        return self.root / provider / f"{profile}-{self.identity_for(settings)[:16]}.json"

    def save(self, settings: AppSettings, catalog: VoiceCatalog) -> Path:
        path = self.path_for(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "provider": settings.provider,
            "profile_id": settings.active_api_profile_id or "temporary",
            "identity": self.identity_for(settings),
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "catalog": {
                "refreshed_at": catalog.refreshed_at,
                "voices": [asdict(item) for item in catalog.voices],
                "models": [asdict(item) for item in catalog.models],
                "account": asdict(catalog.account) if catalog.account else None,
            },
        }
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return path

    def inspect(self, settings: AppSettings) -> ProviderCatalogSnapshotInfo:
        """Return safe metadata for the account-scoped catalog snapshot.

        This never exposes credentials and deliberately distinguishes a stale
        snapshot from a missing or identity-mismatched snapshot so the UI can
        explain why a refresh is needed.
        """
        path = self.path_for(settings)
        if not path.exists():
            return ProviderCatalogSnapshotInfo(False, False)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("schema_version", 0)) != self.SCHEMA_VERSION:
                return ProviderCatalogSnapshotInfo(False, False)
            if payload.get("identity") != self.identity_for(settings):
                return ProviderCatalogSnapshotInfo(False, False)
            catalog = self._catalog_from_dict(payload.get("catalog"))
            if catalog is None:
                return ProviderCatalogSnapshotInfo(False, False)
            account = catalog.account
            remaining = None
            if account and account.character_limit is not None and account.character_count is not None:
                remaining = max(0, account.character_limit - account.character_count)
            return ProviderCatalogSnapshotInfo(
                exists=True,
                stale=self._is_stale(payload.get("saved_at")),
                saved_at=self._optional_str(payload.get("saved_at")),
                refreshed_at=catalog.refreshed_at,
                voice_count=len(catalog.voices),
                model_count=sum(1 for item in catalog.models if item.can_do_text_to_speech),
                account_tier=account.tier if account else None,
                remaining_characters=remaining,
                character_limit=account.character_limit if account else None,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return ProviderCatalogSnapshotInfo(False, False)

    def load(self, settings: AppSettings, *, allow_stale: bool = False) -> VoiceCatalog | None:
        path = self.path_for(settings)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if int(payload.get("schema_version", 0)) != self.SCHEMA_VERSION:
                return None
            if payload.get("identity") != self.identity_for(settings):
                return None
            if not allow_stale and self._is_stale(payload.get("saved_at")):
                return None
            return self._catalog_from_dict(payload.get("catalog"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def invalidate(self, settings: AppSettings | None = None) -> None:
        if settings is None:
            for path in self.root.rglob("*.json"):
                path.unlink(missing_ok=True)
            return
        self.path_for(settings).unlink(missing_ok=True)

    def remove_profile(self, provider: str, profile_id: str) -> None:
        folder = self.root / self._safe_segment(provider)
        prefix = f"{self._safe_segment(profile_id)}-"
        if not folder.exists():
            return
        for path in folder.glob(f"{prefix}*.json"):
            path.unlink(missing_ok=True)

    def _is_stale(self, saved_at: Any) -> bool:
        if self.ttl_seconds <= 0:
            return True
        if not saved_at:
            return True
        try:
            timestamp = datetime.fromisoformat(str(saved_at).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
        return age > self.ttl_seconds

    @staticmethod
    def _catalog_from_dict(data: Any) -> VoiceCatalog | None:
        if not isinstance(data, dict):
            return None
        voices = tuple(
            VoiceItem(
                provider=str(item.get("provider") or ""),
                voice_id=str(item.get("voice_id") or ""),
                name=str(item.get("name") or item.get("voice_id") or ""),
                language=ProviderAccountCatalogStore._optional_str(item.get("language")),
                category=ProviderAccountCatalogStore._optional_str(item.get("category")),
                description=str(item.get("description") or ""),
                labels={str(key): str(value) for key, value in (item.get("labels") or {}).items()},
                is_favorite=bool(item.get("is_favorite", False)),
                preview_url=ProviderAccountCatalogStore._optional_str(item.get("preview_url")),
                available_for_tiers=tuple(str(value) for value in item.get("available_for_tiers") or []),
                compatible_model_ids=tuple(str(value) for value in item.get("compatible_model_ids") or []),
                is_owner=item.get("is_owner") if isinstance(item.get("is_owner"), bool) else None,
            )
            for item in data.get("voices") or []
            if isinstance(item, dict) and item.get("voice_id")
        )
        models = tuple(
            VoiceModelItem(
                model_id=str(item.get("model_id") or ""),
                name=str(item.get("name") or item.get("model_id") or ""),
                languages=tuple(str(value) for value in item.get("languages") or []),
                can_do_text_to_speech=bool(item.get("can_do_text_to_speech", True)),
                can_use_style=bool(item.get("can_use_style", False)),
                can_use_speaker_boost=bool(item.get("can_use_speaker_boost", False)),
                maximum_text_length=ProviderAccountCatalogStore._optional_int(item.get("maximum_text_length")),
                cost_factor=ProviderAccountCatalogStore._optional_float(item.get("cost_factor")),
            )
            for item in data.get("models") or []
            if isinstance(item, dict) and item.get("model_id")
        )
        account_data = data.get("account")
        account = None
        if isinstance(account_data, dict):
            account = AccountUsage(
                tier=ProviderAccountCatalogStore._optional_str(account_data.get("tier")),
                status=ProviderAccountCatalogStore._optional_str(account_data.get("status")),
                character_count=ProviderAccountCatalogStore._optional_int(account_data.get("character_count")),
                character_limit=ProviderAccountCatalogStore._optional_int(account_data.get("character_limit")),
            )
        return VoiceCatalog(
            voices=voices,
            models=models,
            account=account,
            refreshed_at=ProviderAccountCatalogStore._optional_str(data.get("refreshed_at")),
        )

    @staticmethod
    def _safe_segment(value: str) -> str:
        cleaned = "".join(char if char.isalnum() or char in "-_." else "_" for char in value.strip())
        return cleaned or "default"

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

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
