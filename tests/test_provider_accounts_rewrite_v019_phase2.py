from __future__ import annotations

from pathlib import Path


def test_voice_browser_uses_account_specific_catalog_snapshot() -> None:
    source = Path("app/gui/voice_browser.py").read_text(encoding="utf-8")
    assert "self.items = list(cached.voices)" in source
    assert "self.items = self.service.list(provider=settings.provider)" not in source
    assert "Refreshing account-specific voice catalog" in source
    assert "profile_name_provider" in source


def test_provider_account_details_show_catalog_counts_and_force_refresh() -> None:
    source = Path("app/gui/dialogs/provider_accounts_dialog.py").read_text(encoding="utf-8")
    assert 'self.details_form.addRow("Voices", self.details_voices)' in source
    assert 'self.details_form.addRow("TTS models", self.details_models)' in source
    assert "force_refresh=force" in source


def test_voice_catalog_is_built_from_current_response_not_provider_wide_repository() -> None:
    source = Path("app/services/voice_service.py").read_text(encoding="utf-8")
    assert "account_voices: list[VoiceItem]" in source
    assert "voices=tuple(account_voices)" in source
    assert "catalog_profile_id" in source
