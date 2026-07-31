from __future__ import annotations

from pathlib import Path

from app.models.api_profile import ApiProfile, ApiProfileStatus, FailoverSettings
from app.models.provider_health import ProviderHealthState, evaluate_provider_health
from app.services.api_profile_service import ApiProfileService
from app.services.provider_account_catalog_store import ProviderCatalogSnapshotInfo
from app.services.secure_credentials import SecureCredentialStore


def _service(tmp_path: Path) -> ApiProfileService:
    return ApiProfileService(tmp_path / "profiles.json", SecureCredentialStore(tmp_path / "credentials"))


def test_health_states_cover_stale_exhausted_and_offline() -> None:
    profile = ApiProfile("a", "Primary", has_saved_key=True, status=ApiProfileStatus.READY)
    stale = ProviderCatalogSnapshotInfo(True, True)
    assert evaluate_provider_health(profile, stale).state == ProviderHealthState.STALE

    profile.remaining_characters = 0
    profile.character_limit = 1000
    assert evaluate_provider_health(profile).state == ProviderHealthState.EXHAUSTED

    profile.remaining_characters = 500
    profile.status = ApiProfileStatus.UNAVAILABLE
    assert evaluate_provider_health(profile).state == ProviderHealthState.OFFLINE


def test_manual_failover_order_is_persistent_and_respected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    primary = service.create_profile("Primary", api_key="one", active=True)
    backup_a = service.create_profile("Backup A", api_key="two")
    backup_b = service.create_profile("Backup B", api_key="three")
    for profile in (primary, backup_a, backup_b):
        profile.status = ApiProfileStatus.READY
        profile.remaining_characters = 1000
        profile.character_limit = 1000
        service.update_profile(profile)

    service.save_failover_settings(
        "elevenlabs",
        FailoverSettings(
            mode="auto",
            sequence_mode="manual",
            manual_sequence=[primary.profile_id, backup_b.profile_id, backup_a.profile_id],
            allow_unknown_quota_override=False,
        ),
    )

    decision = service.choose_failover(
        provider="elevenlabs",
        current_profile_id=primary.profile_id,
        mode="auto",
        error_code="insufficient_quota",
    )
    assert decision.target_profile_id == backup_b.profile_id


def test_failover_is_deferred_while_generation_is_active(tmp_path: Path) -> None:
    service = _service(tmp_path)
    primary = service.create_profile("Primary", api_key="one", active=True)
    backup = service.create_profile("Backup", api_key="two")
    backup.status = ApiProfileStatus.READY
    backup.remaining_characters = 1000
    backup.character_limit = 1000
    service.update_profile(backup)

    decision = service.activate_failover_target(
        provider="elevenlabs",
        current_profile_id=primary.profile_id,
        mode="auto",
        error_code="insufficient_quota",
        generation_active=True,
    )
    assert not decision.should_switch
    assert service.active_profile("elevenlabs").profile_id == primary.profile_id
