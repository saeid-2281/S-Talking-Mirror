from __future__ import annotations

import json
from pathlib import Path

from app.models.domain import AppSettings
from app.services.provider_account_catalog_store import ProviderAccountCatalogStore
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem


def _catalog(profile: str) -> VoiceCatalog:
    return VoiceCatalog(
        voices=(
            VoiceItem(
                provider="elevenlabs",
                voice_id=f"voice-{profile}",
                name=f"Voice {profile}",
                language="da",
                category="premade",
                description="",
                labels={"language": "da"},
                is_favorite=False,
            ),
        ),
        models=(VoiceModelItem(f"model-{profile}", f"Model {profile}", ("da",)),),
        account=AccountUsage("creator", "active", 100, 1000),
        refreshed_at="2026-07-28T00:00:00+00:00",
    )


def test_catalog_store_is_profile_and_credential_specific(tmp_path: Path) -> None:
    store = ProviderAccountCatalogStore(tmp_path, ttl_seconds=3600)
    first = AppSettings(provider="elevenlabs", api_key="same", active_api_profile_id="first")
    second = AppSettings(provider="elevenlabs", api_key="same", active_api_profile_id="second")
    changed_key = AppSettings(provider="elevenlabs", api_key="changed", active_api_profile_id="first")

    store.save(first, _catalog("first"))
    store.save(second, _catalog("second"))

    assert store.load(first).models[0].model_id == "model-first"
    assert store.load(second).models[0].model_id == "model-second"
    assert store.load(changed_key) is None
    assert store.path_for(first) != store.path_for(second)


def test_catalog_store_never_writes_raw_api_key(tmp_path: Path) -> None:
    store = ProviderAccountCatalogStore(tmp_path, ttl_seconds=3600)
    settings = AppSettings(provider="elevenlabs", api_key="sk_SUPERSECRET", active_api_profile_id="prod")
    path = store.save(settings, _catalog("prod"))

    payload = path.read_text(encoding="utf-8")
    assert "sk_SUPERSECRET" not in payload
    assert json.loads(payload)["profile_id"] == "prod"


def test_catalog_store_invalidates_only_selected_profile(tmp_path: Path) -> None:
    store = ProviderAccountCatalogStore(tmp_path, ttl_seconds=3600)
    first = AppSettings(provider="elevenlabs", api_key="a", active_api_profile_id="first")
    second = AppSettings(provider="elevenlabs", api_key="b", active_api_profile_id="second")
    store.save(first, _catalog("first"))
    store.save(second, _catalog("second"))

    store.invalidate(first)

    assert store.load(first) is None
    assert store.load(second) is not None


def test_catalog_store_rejects_malformed_or_stale_snapshots(tmp_path: Path) -> None:
    settings = AppSettings(provider="elevenlabs", api_key="a", active_api_profile_id="first")
    store = ProviderAccountCatalogStore(tmp_path, ttl_seconds=3600)
    path = store.save(settings, _catalog("first"))
    path.write_text("not-json", encoding="utf-8")
    assert store.load(settings) is None

    stale = ProviderAccountCatalogStore(tmp_path / "stale", ttl_seconds=0)
    stale.save(settings, _catalog("first"))
    assert stale.load(settings) is None
    assert stale.load(settings, allow_stale=True) is not None
