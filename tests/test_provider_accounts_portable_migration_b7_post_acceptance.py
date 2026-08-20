from __future__ import annotations

import json
from pathlib import Path

from app.services.api_profile_service import ApiProfileService
from app.services.secure_credentials import SecureCredentialStore


def test_api_profile_service_accepts_windows_powershell_utf8_bom(tmp_path: Path) -> None:
    metadata = tmp_path / "api-profiles.json"
    payload = {
        "schema_version": 1,
        "profiles": [
            {
                "profile_id": "migrated-profile",
                "display_name": "Migrated account",
                "provider": "elevenlabs",
                "has_saved_key": True,
            }
        ],
    }
    metadata.write_text(json.dumps(payload), encoding="utf-8-sig")
    service = ApiProfileService(metadata, SecureCredentialStore(tmp_path / "credentials", platform="linux"))
    profiles = service.list_profiles()
    assert [profile.profile_id for profile in profiles] == ["migrated-profile"]


def test_migration_writes_utf8_without_bom_and_runs_frozen_runtime_verification() -> None:
    script = Path("scripts/migrate_provider_accounts_to_portable.ps1").read_text(encoding="utf-8-sig")
    assert "[System.Text.UTF8Encoding]::new($false)" in script
    assert "Set-Content -LiteralPath $TempMetadata -Encoding UTF8" not in script
    assert "--provider-accounts-runtime-verify" in script
    assert "--provider-accounts-expected-saved-count" in script
    assert "PROVIDER_ACCOUNTS_RUNTIME_VERIFY=PASS" in script


def test_frozen_runtime_verifier_reports_counts_not_secret_values() -> None:
    source = Path("app/frozen_main.py").read_text(encoding="utf-8")
    assert "def _handle_provider_accounts_runtime_verify" in source
    assert "PROVIDER_ACCOUNTS_PROFILE_COUNT=" in source
    assert "PROVIDER_ACCOUNTS_SAVED_PROFILE_COUNT=" in source
    assert "PROVIDER_ACCOUNTS_RESOLVED_CREDENTIAL_COUNT=" in source
    assert "PROVIDER_ACCOUNTS_UI_VISIBLE_COUNT=" in source
    assert "PROVIDER_ACCOUNTS_EXPECTED_SAVED_COUNT=" in source
    assert "PROVIDER_ACCOUNTS_RUNTIME_VERIFY=" in source
    assert "print(secret" not in source
    assert "print(api_key" not in source
