from __future__ import annotations

from pathlib import Path

import pytest

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.unified_voice_model_catalog_dialog import UnifiedVoiceModelCatalogDialog
from app.gui.main import MainWindow
from app.models import AppSettings
from app.models.unified_voice_model_catalog import UnifiedCatalogItem
from app.services.api_profile_service import ApiProfileService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.secure_credentials import SecureCredentialStore
from app.services.unified_voice_model_catalog_service import UnifiedVoiceModelCatalogService
from app.services.voice_service import VoiceCatalog, VoiceItem, VoiceModelItem


def _profiles(tmp_path) -> ApiProfileService:
    return ApiProfileService(tmp_path / "api-profiles.json", SecureCredentialStore(tmp_path / "credentials"))


class _VoiceService:
    def __init__(self, catalogs):
        self.catalogs = catalogs
        self.refresh_calls = []

    def available_catalog(self, settings, *, allow_stale=False):
        return self.catalogs.get(settings.provider)

    def refresh_catalog(self, settings, *, force=False):
        self.refresh_calls.append(settings.provider)
        return self.catalogs[settings.provider]


def _catalog(provider: str, *, favorite: bool = True) -> VoiceCatalog:
    return VoiceCatalog(
        voices=(
            VoiceItem(
                provider=provider,
                voice_id=f"{provider}-voice",
                name=f"{provider.title()} Danish Voice",
                language="da-DK",
                category="test",
                description="Danish discovery voice",
                labels={"gender": "neutral"},
                is_favorite=favorite,
                compatible_model_ids=(f"{provider}-model",),
            ),
        ),
        models=(
            VoiceModelItem(
                model_id=f"{provider}-model",
                name=f"{provider.title()} Model",
                languages=("da-DK",),
                maximum_text_length=5000,
                cost_factor=1.25,
            ),
        ),
        account=None,
        refreshed_at="2026-08-12T00:00:00+00:00",
    )


def _service(tmp_path):
    profiles = _profiles(tmp_path)
    voices = _VoiceService({"openai": _catalog("openai"), "cartesia": _catalog("cartesia", favorite=False)})
    return UnifiedVoiceModelCatalogService(profiles, ProviderCatalogService(), voices), profiles, voices


def test_a4_discovery_filters_current_provider_language_and_favorites(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    openai = profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    profiles.create_profile("Cartesia", provider="cartesia", api_key="b", active=True)
    base = AppSettings(provider="openai", active_api_profile_id=openai.profile_id, language_code="da-DK", model_id="openai-model")
    catalog = service.snapshot(base, provider_ids=("openai", "cartesia"))

    items = service.discovery_items(
        catalog,
        base,
        current_provider_only=True,
        current_language_only=True,
        favorites_only=True,
    )

    assert {item.provider_id for item in items} == {"openai"}
    assert {item.kind for item in items} == {"voice"}


def test_a4_known_compatibility_filter_uses_current_counterpart(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profile = profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    base = AppSettings(
        provider="openai",
        active_api_profile_id=profile.profile_id,
        voice_id="openai-voice",
        model_id="openai-model",
    )
    catalog = service.snapshot(base, provider_ids=("openai",))
    items = service.discovery_items(catalog, base, compatible_only=True)

    assert {item.kind for item in items} == {"voice", "model"}
    assert all(service.compatibility_state(catalog, base, item) == "compatible" for item in items)


def test_a4_selection_review_is_read_only(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    profiles.create_profile("Cartesia", provider="cartesia", api_key="b", active=True)
    base = AppSettings(provider="openai", voice_id="old", model_id="old-model")
    catalog = service.snapshot(base, provider_ids=("cartesia",))
    item = next(item for item in catalog.items if item.kind == "voice")

    review = service.selection_review(base, item, catalog=catalog)

    assert review.provider_change is True
    assert review.account_change is True
    assert "Provider" in review.change_text
    assert "explicit approval" in review.warning_text
    assert base.provider == "openai"
    assert base.voice_id == "old"


def test_a4_selection_applies_exact_explicit_catalog_account(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    active = profiles.create_profile("Cartesia Active", provider="cartesia", api_key="active", active=True)
    selected = profiles.create_profile("Cartesia Selected", provider="cartesia", api_key="selected", active=False)
    item = UnifiedCatalogItem(
        key=f"cartesia:{selected.profile_id}:voice:v",
        kind="voice",
        provider_id="cartesia",
        provider_name="Cartesia",
        profile_id=selected.profile_id,
        profile_name=selected.display_name,
        item_id="voice-v",
        name="Voice V",
    )
    settings = service.selection_settings(
        AppSettings(provider="openai"),
        item,
        allow_provider_change=True,
        allow_profile_change=True,
    )

    assert active.profile_id != selected.profile_id
    assert settings.active_api_profile_id == selected.profile_id
    assert settings.api_key == "selected"
    assert settings.voice_id == "voice-v"


def test_a4_stale_catalog_profile_id_uses_resolved_active_account_only_after_explicit_approval(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    active = profiles.create_profile(
        "Cartesia Active",
        provider="cartesia",
        api_key="secret",
        active=True,
    )
    item = UnifiedCatalogItem(
        key="cartesia:opaque-profile-id:voice:v",
        kind="voice",
        provider_id="cartesia",
        provider_name="Cartesia",
        profile_id="opaque-profile-id",
        profile_name="Cartesia",
        item_id="voice-v",
        name="Voice V",
    )
    base = AppSettings(provider="openai", voice_id="alloy")

    with pytest.raises(ValueError, match="provider-change approval"):
        service.selection_settings(base, item)

    selected = service.selection_settings(
        base,
        item,
        allow_provider_change=True,
        allow_profile_change=True,
    )

    assert selected.provider == "cartesia"
    assert selected.active_api_profile_id == active.profile_id
    assert selected.api_key == "secret"
    assert selected.voice_id == "voice-v"
    assert base.provider == "openai"


def test_a4_explicit_provider_and_account_approval_remains_required(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    selected = profiles.create_profile("Cartesia", provider="cartesia", api_key="b", active=True)
    item = UnifiedCatalogItem(
        key=f"cartesia:{selected.profile_id}:voice:v",
        kind="voice",
        provider_id="cartesia",
        provider_name="Cartesia",
        profile_id=selected.profile_id,
        profile_name=selected.display_name,
        item_id="voice-v",
        name="Voice V",
    )
    with pytest.raises(ValueError, match="provider-change approval"):
        service.selection_settings(AppSettings(provider="openai"), item)
    with pytest.raises(ValueError, match="account-change approval"):
        service.selection_settings(AppSettings(provider="openai"), item, allow_provider_change=True)


def test_a4_dialog_open_is_cached_first(qt_app, tmp_path) -> None:
    service, profiles, voices = _service(tmp_path)
    profile = profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    settings = AppSettings(
        provider="openai",
        active_api_profile_id=profile.profile_id,
        voice_id="openai-voice",
        model_id="openai-model",
        language_code="da-DK",
    )
    dialog = UnifiedVoiceModelCatalogDialog(service, lambda: settings)
    dialog.show()
    qt_app.processEvents()

    assert dialog.windowTitle() == "Voice & Model Discovery"
    assert dialog.table.rowCount() >= 2
    assert dialog.refresh_button.isEnabled() is False
    assert voices.refresh_calls == []
    assert "Current setup" in dialog.current_setup.text()
    dialog.close()


def test_a4_quick_filters_do_not_refresh_provider(qt_app, tmp_path) -> None:
    service, profiles, voices = _service(tmp_path)
    profile = profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    settings = AppSettings(provider="openai", active_api_profile_id=profile.profile_id, language_code="da-DK", model_id="openai-model")
    dialog = UnifiedVoiceModelCatalogDialog(service, lambda: settings)
    dialog.show()
    qt_app.processEvents()
    dialog.current_provider_only.setChecked(True)
    dialog.current_language_only.setChecked(True)
    dialog.favorites_only.setChecked(True)
    qt_app.processEvents()

    assert dialog.table.rowCount() == 1
    assert voices.refresh_calls == []
    dialog.close()


def test_a4_review_does_not_apply_until_explicit_use(qt_app, tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profile = profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    settings = AppSettings(provider="openai", active_api_profile_id=profile.profile_id, model_id="openai-model")
    dialog = UnifiedVoiceModelCatalogDialog(service, lambda: settings)
    emitted = []
    dialog.settings_selected.connect(emitted.append)
    dialog.show()
    qt_app.processEvents()
    dialog.table.selectRow(0)
    qt_app.processEvents()

    assert emitted == []
    assert "Would change:" in dialog.selection_detail.text()
    dialog.close()


def test_a4_apply_is_blocked_while_generation_active(qt_app, tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    dialog = UnifiedVoiceModelCatalogDialog(
        service,
        lambda: AppSettings(provider="openai"),
        generation_active=lambda: True,
    )
    dialog.show()
    qt_app.processEvents()
    dialog.table.selectRow(0)
    qt_app.processEvents()

    assert dialog.use_button.isEnabled() is False
    dialog.close()


def test_a4_phase106_public_dialog_contract_is_preserved() -> None:
    source = Path("app/gui/dialogs/unified_voice_model_catalog_dialog.py").read_text(encoding="utf-8")
    for token in (
        "self.provider = QComboBox()",
        "self.kind = QComboBox()",
        "self.language = QComboBox()",
        "self.search = QLineEdit()",
        "self.refresh_button = QPushButton",
        "self.table = QTableWidget",
        "self.use_button = QPushButton",
    ):
        assert token in source


def test_a4_main_historical_catalog_action_and_shortcut_stay_available(qt_app, tmp_path) -> None:
    from app.bootstrap import create_application_context

    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    assert "Voice & Model Catalog" in window.actions_by_name
    assert window.actions_by_name["Voice & Model Catalog"].shortcut().toString() == "Ctrl+Alt+V"
    window.close()


def test_a4_onboarding_handoff_uses_discovery_label_without_changing_action_id() -> None:
    from app.services.first_run_onboarding_service import FirstRunOnboardingService

    step = next(step for step in FirstRunOnboardingService.steps() if step.step_id == "voice_model_choice")
    assert step.action_id == "voice_model_catalog"
    assert step.action_label == "Open Voice & Model Discovery"
    assert "cached account-scoped metadata" in step.description


def test_a4_dialog_authority_boundary_has_no_execution_calls() -> None:
    source = Path("app/gui/dialogs/unified_voice_model_catalog_dialog.py").read_text(encoding="utf-8")
    method = source.split("def use_selection", 1)[1].split("def _open_accounts", 1)[0]
    assert ".dry_run(" not in method
    assert ".run_preflight(" not in method
    assert ".start(" not in method
    assert "smart_provider_routing" not in method
    assert "refresh_provider(" not in method
    assert "settings_selected.emit" in method


def test_a4_discovery_service_is_read_only() -> None:
    source = Path("app/services/unified_voice_model_catalog_service.py").read_text(encoding="utf-8")
    method = source.split("def discovery_items", 1)[1].split("def compatibility_state", 1)[0]
    assert "refresh_catalog" not in method
    assert "set_active" not in method
    assert "apply_profile" not in method


def test_a4_database_schema_23_is_preserved(tmp_path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "a4-schema.db")
    database.initialize()
    assert database.expected_schema_version == 23
    assert database.applied_schema_versions()[-1] == 23


def test_a4_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/unified_voice_model_catalog.py"),
        Path("app/services/unified_voice_model_catalog_service.py"),
        Path("app/gui/dialogs/unified_voice_model_catalog_dialog.py"),
        Path("app/services/first_run_onboarding_service.py"),
        Path("docs/VOICE_MODEL_DISCOVERY_SELECTION_UX_ROADMAP2_A4.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
