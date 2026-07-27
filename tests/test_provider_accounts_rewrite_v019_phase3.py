from __future__ import annotations

from pathlib import Path


def test_provider_accounts_uses_professional_detail_cards() -> None:
    source = Path("app/gui/dialogs/provider_accounts_dialog.py").read_text(encoding="utf-8")
    for object_name in [
        "providerAccountIdentity",
        "providerAccountQuotaCard",
        "providerAccountCatalogCard",
        "providerAccountMetadataCard",
        "providerQuotaProgress",
        "accountStatusBadge",
    ]:
        assert object_name in source
    assert 'QPushButton("Refresh catalog")' in source


def test_remote_refresh_keeps_new_account_catalog_cached() -> None:
    source = Path("app/gui/dialogs/provider_accounts_dialog.py").read_text(encoding="utf-8")
    assert "self._test_profile(profile, force=True)" in source
    assert "self._changed(invalidate_catalog=False)" in source
    assert "def _changed(self, *, invalidate_catalog: bool = True)" in source


def test_account_test_has_visible_testing_state() -> None:
    source = Path("app/gui/dialogs/provider_accounts_dialog.py").read_text(encoding="utf-8")
    assert "profile.status = ApiProfileStatus.TESTING" in source
    assert "QApplication.processEvents()" in source
    assert 'return "info"' in source
