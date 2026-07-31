from __future__ import annotations

from pathlib import Path


from app.models.domain import AppSettings
from app.services.provider_account_catalog_store import ProviderAccountCatalogStore
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem


def _settings(profile_id: str, key: str = "secret") -> AppSettings:
    return AppSettings(provider="elevenlabs", api_key=key, active_api_profile_id=profile_id)


def test_catalog_snapshot_info_reports_fresh_counts_and_quota(tmp_path: Path) -> None:
    store = ProviderAccountCatalogStore(tmp_path, ttl_seconds=3600)
    catalog = VoiceCatalog(
        voices=(VoiceItem("elevenlabs", "v1", "Voice", "da", None, "", {}, False),),
        models=(VoiceModelItem("m1", "Model", ("da",), True),),
        account=AccountUsage("creator", "active", 250, 1000),
        refreshed_at="2026-07-28T10:00:00+00:00",
    )
    store.save(_settings("profile-a"), catalog)

    info = store.inspect(_settings("profile-a"))

    assert info.exists is True
    assert info.stale is False
    assert info.state_label == "Fresh"
    assert info.voice_count == 1
    assert info.model_count == 1
    assert info.remaining_characters == 750
    assert info.character_limit == 1000


def test_catalog_snapshot_info_rejects_changed_key(tmp_path: Path) -> None:
    store = ProviderAccountCatalogStore(tmp_path, ttl_seconds=3600)
    store.save(_settings("profile-a", "old"), VoiceCatalog((), (), None, "now"))

    info = store.inspect(_settings("profile-a", "new"))

    assert info.exists is False
    assert info.state_label == "Not cached"


def test_provider_accounts_dialog_exposes_catalog_columns() -> None:
    source = Path("app/gui/dialogs/provider_accounts_dialog.py").read_text(encoding="utf-8")
    assert '"Catalog", "Voices", "Models"' in source
    assert "details_catalog_saved" in source
    assert "store.remove_profile(profile.provider, profile.profile_id)" in source
