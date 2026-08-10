from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.exceptions import ProviderError
from app.gui.dialogs.unified_voice_model_catalog_dialog import UnifiedVoiceModelCatalogDialog
from app.gui.main import MainWindow
from app.models import AppSettings
from app.models.unified_voice_model_catalog import UnifiedCatalogItem
from app.services.api_profile_service import ApiProfileService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.secure_credentials import SecureCredentialStore
from app.services.unified_voice_model_catalog_service import UnifiedVoiceModelCatalogService
from app.services.voice_service import VoiceCatalog, VoiceItem, VoiceModelItem, VoiceService


def _profiles(tmp_path) -> ApiProfileService:
    return ApiProfileService(
        tmp_path / "api-profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )


class _FakeVoiceService:
    def __init__(self, catalogs: dict[str, VoiceCatalog] | None = None) -> None:
        self.catalogs = catalogs or {}
        self.refresh_calls: list[str] = []

    def available_catalog(self, settings, *, allow_stale=False):
        return self.catalogs.get(settings.provider)

    def refresh_catalog(self, settings, *, force=False):
        self.refresh_calls.append(settings.provider)
        return self.catalogs[settings.provider]


def _catalog(provider: str) -> VoiceCatalog:
    return VoiceCatalog(
        voices=(
            VoiceItem(
                provider=provider,
                voice_id=f"{provider}-voice",
                name=f"{provider.title()} Voice",
                language="da-DK",
                category="test",
                description="Danish catalog voice",
                labels={"gender": "neutral", "languages": "da-DK,en-US"},
                is_favorite=False,
                compatible_model_ids=(f"{provider}-model",),
            ),
        ),
        models=(
            VoiceModelItem(
                model_id=f"{provider}-model",
                name=f"{provider.title()} Model",
                languages=("da-DK", "en-US"),
            ),
        ),
        account=None,
        refreshed_at="2026-08-10T12:00:00+00:00",
    )


def _service(tmp_path, catalogs: dict[str, VoiceCatalog] | None = None):
    profiles = _profiles(tmp_path)
    voices = _FakeVoiceService(catalogs)
    service = UnifiedVoiceModelCatalogService(profiles, ProviderCatalogService(), voices)
    return service, profiles, voices


def test_phase106_snapshot_unifies_account_scoped_provider_catalogs(tmp_path) -> None:
    service, profiles, _voices = _service(
        tmp_path,
        {"openai": _catalog("openai"), "cartesia": _catalog("cartesia")},
    )
    profiles.create_profile("OpenAI", provider="openai", api_key="sk-openai", active=True)
    profiles.create_profile("Cartesia", provider="cartesia", api_key="sk-cartesia", active=True)

    snapshot = service.snapshot(
        AppSettings(provider="openai", api_key="temporary"),
        provider_ids=("openai", "cartesia"),
    )

    assert snapshot.provider_count == 2
    assert snapshot.voice_count == 2
    assert snapshot.model_count == 2
    assert {item.provider_id for item in snapshot.items} == {"openai", "cartesia"}
    assert len({item.key for item in snapshot.items}) == 4


def test_phase106_cross_provider_settings_do_not_leak_current_secret_or_metadata(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    azure = profiles.create_profile(
        "Azure EU",
        provider="azure",
        api_key="azure-secret",
        active=True,
        metadata={"region": "northeurope"},
    )
    base = AppSettings(
        provider="openai",
        api_key="openai-secret",
        provider_options={"private": "openai-only"},
    )

    settings, profile_name = service.settings_for_provider("azure", base)

    assert profile_name == "Azure EU"
    assert settings.active_api_profile_id == azure.profile_id
    assert settings.api_key == "azure-secret"
    assert settings.provider_options == {"region": "northeurope"}
    assert "openai" not in settings.api_key
    assert "private" not in settings.provider_options


def test_phase106_catalog_browsing_does_not_change_active_generation_provider(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path, {"cartesia": _catalog("cartesia")})
    profiles.create_profile("Cartesia", provider="cartesia", api_key="secret", active=True)
    base = AppSettings(provider="openai", api_key="openai-secret", model_id="gpt-4o-mini-tts")

    service.snapshot(base, provider_ids=("cartesia",))

    assert base.provider == "openai"
    assert base.api_key == "openai-secret"
    assert base.model_id == "gpt-4o-mini-tts"


def test_phase106_cross_provider_selection_requires_explicit_approval(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profiles.create_profile("Cartesia", provider="cartesia", api_key="secret", active=True)
    item = UnifiedCatalogItem(
        key="cartesia:p:voice:v",
        kind="voice",
        provider_id="cartesia",
        provider_name="Cartesia",
        profile_id="p",
        profile_name="Cartesia",
        item_id="voice-v",
        name="Voice V",
    )
    base = AppSettings(provider="openai", voice_id="alloy")

    with pytest.raises(ValueError, match="explicit provider-change approval"):
        service.selection_settings(base, item)

    selected = service.selection_settings(base, item, allow_provider_change=True, allow_profile_change=True)
    assert selected.provider == "cartesia"
    assert selected.voice_id == "voice-v"
    assert base.provider == "openai"


def test_phase106_same_provider_selection_is_safe_without_provider_change_flag(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profile = profiles.create_profile("OpenAI", provider="openai", api_key="secret", active=True)
    item = UnifiedCatalogItem(
        key="openai:p:model:m",
        kind="model",
        provider_id="openai",
        provider_name="OpenAI Speech",
        profile_id=profile.profile_id,
        profile_name="OpenAI",
        item_id="gpt-4o-mini-tts",
        name="gpt-4o-mini-tts",
    )
    selected = service.selection_settings(AppSettings(provider="openai", active_api_profile_id=profile.profile_id), item)
    assert selected.provider == "openai"
    assert selected.model_id == "gpt-4o-mini-tts"
    assert selected.active_api_profile_id == profile.profile_id



def test_phase106_same_provider_account_change_requires_explicit_approval(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    first = profiles.create_profile("OpenAI A", provider="openai", api_key="a", active=True)
    second = profiles.create_profile("OpenAI B", provider="openai", api_key="b", active=False)
    item = UnifiedCatalogItem(
        key=f"openai:{second.profile_id}:voice:v",
        kind="voice",
        provider_id="openai",
        provider_name="OpenAI Speech",
        profile_id=second.profile_id,
        profile_name=second.display_name,
        item_id="alloy",
        name="Alloy",
    )
    base = AppSettings(provider="openai", active_api_profile_id=first.profile_id)

    with pytest.raises(ValueError, match="explicit account-change approval"):
        service.selection_settings(base, item)


def test_phase106_search_filters_provider_kind_language_and_text(tmp_path) -> None:
    service, profiles, _voices = _service(
        tmp_path,
        {"openai": _catalog("openai"), "cartesia": _catalog("cartesia")},
    )
    profiles.create_profile("OpenAI", provider="openai", api_key="a", active=True)
    profiles.create_profile("Cartesia", provider="cartesia", api_key="b", active=True)
    snapshot = service.snapshot(AppSettings(provider="openai"), provider_ids=("openai", "cartesia"))

    items = service.filtered_items(
        snapshot,
        query="Danish",
        provider_id="cartesia",
        kind="voice",
        language="da",
    )
    assert len(items) == 1
    assert items[0].provider_id == "cartesia"
    assert items[0].kind == "voice"


def test_phase106_model_fallbacks_are_centralized_and_do_not_require_network(tmp_path) -> None:
    service, _profiles, voices = _service(tmp_path)
    base = AppSettings(provider="mock")

    assert service.models_for_provider("openai", base)[0].model_id == "gpt-4o-mini-tts"
    assert service.models_for_provider("cartesia", base)[0].model_id == "sonic-3.5"
    assert service.models_for_provider("resemble", base)[0].model_id == "resemble-ultra"
    assert service.models_for_provider("murf", base)[0].model_id == "GEN2"
    assert service.models_for_provider("deepgram", base) == ()
    assert voices.refresh_calls == []


def test_phase106_refresh_is_explicit_and_scoped_to_one_provider(tmp_path) -> None:
    service, profiles, voices = _service(tmp_path, {"openai": _catalog("openai")})
    profiles.create_profile("OpenAI", provider="openai", api_key="secret", active=True)

    service.snapshot(AppSettings(provider="openai"), provider_ids=("openai",))
    assert voices.refresh_calls == []

    result = service.refresh_provider("openai", AppSettings(provider="openai"))
    assert result.state == "refreshed"
    assert voices.refresh_calls == ["openai"]


def test_phase106_external_credentials_can_surface_cached_catalog_without_secret(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path, {"google": _catalog("google")})
    google = profiles.create_profile(
        "Google ADC",
        provider="google",
        active=True,
        metadata={"project_id": "demo"},
    )

    snapshot = service.snapshot(AppSettings(provider="openai"), provider_ids=("google",))

    assert snapshot.voice_count == 1
    assert snapshot.sources[0].profile_id == google.profile_id
    assert snapshot.sources[0].profile_name == "Google ADC"




def test_phase106_preview_normalizes_stale_model_only_for_single_model_catalog() -> None:
    voice = VoiceItem(
        provider="mock",
        voice_id="mock-tone",
        name="Local test tone",
        language=None,
        category="free",
        description="",
        labels={},
        is_favorite=False,
    )
    catalog = VoiceCatalog(
        voices=(voice,),
        models=(VoiceModelItem("mock-v1", "Local test generator", ()),),
        account=None,
        refreshed_at="2026-08-10T12:00:00+00:00",
    )
    fake = SimpleNamespace(
        available_catalog=lambda _settings, allow_stale=True: catalog,
    )
    base = AppSettings(provider="mock", model_id="eleven_multilingual_v2", voice_id="")

    preview = VoiceService._preview_settings(fake, voice, base)

    assert preview.model_id == "mock-v1"
    assert preview.voice_id == "mock-tone"
    assert base.model_id == "eleven_multilingual_v2"
    assert base.voice_id == ""


def test_phase106_preview_does_not_auto_choose_when_multiple_models_exist() -> None:
    voice = VoiceItem(
        provider="cartesia",
        voice_id="cartesia-voice",
        name="Cartesia Voice",
        language="da-DK",
        category="test",
        description="",
        labels={},
        is_favorite=False,
    )
    catalog = VoiceCatalog(
        voices=(voice,),
        models=(
            VoiceModelItem("sonic-3.5", "Sonic 3.5", ("da",)),
            VoiceModelItem("sonic-3", "Sonic 3", ("da",)),
        ),
        account=None,
        refreshed_at="2026-08-10T12:00:00+00:00",
    )
    fake = SimpleNamespace(
        available_catalog=lambda _settings, allow_stale=True: catalog,
    )
    base = AppSettings(provider="cartesia", model_id="stale-provider-model")

    preview = VoiceService._preview_settings(fake, voice, base)

    assert preview.model_id == "stale-provider-model"

def test_phase106_general_voice_model_compatibility_validation_is_not_elevenlabs_only() -> None:
    voice = _catalog("cartesia").voices[0]
    catalog = _catalog("cartesia")
    fake = SimpleNamespace(available_catalog=lambda _settings, allow_stale=True: catalog)

    VoiceService.validate_selection(
        fake,
        voice,
        AppSettings(provider="cartesia", model_id="cartesia-model", voice_id=voice.voice_id),
    )

    with pytest.raises(ProviderError) as exc:
        VoiceService.validate_selection(
            fake,
            voice,
            AppSettings(provider="cartesia", model_id="wrong-model", voice_id=voice.voice_id),
        )
    assert exc.value.provider_code == "model_not_found"


def test_phase106_dialog_is_all_provider_cached_first_and_refresh_requires_provider(qt_app, tmp_path) -> None:
    service, profiles, voices = _service(tmp_path, {"openai": _catalog("openai")})
    profiles.create_profile("OpenAI", provider="openai", api_key="secret", active=True)
    dialog = UnifiedVoiceModelCatalogDialog(service, lambda: AppSettings(provider="openai"))
    dialog.show()
    qt_app.processEvents()

    assert dialog.provider.currentData() is None
    assert dialog.refresh_button.isEnabled() is False
    assert dialog.table.rowCount() >= 1
    assert voices.refresh_calls == []
    dialog.close()


def test_phase106_dialog_blocks_use_while_generation_active(qt_app, tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path, {"openai": _catalog("openai")})
    profiles.create_profile("OpenAI", provider="openai", api_key="secret", active=True)
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


def test_phase106_context_wires_unified_catalog_service(tmp_path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    context = create_application_context(create_service_container(runtime))
    assert context.unified_voice_model_catalog_service.voices is context.voice_service
    assert context.unified_voice_model_catalog_service.profiles is context.api_profile_service


def test_phase106_main_workspace_exposes_catalog_and_uses_unified_model_source(qt_app, tmp_path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    assert "Voice & Model Catalog" in window.actions_by_name
    assert window.actions_by_name["Voice & Model Catalog"].shortcut().toString() == "Ctrl+Alt+V"

    window.provider.setCurrentText("cartesia")
    qt_app.processEvents()
    window.refresh_models()
    assert window.current_model_id() == "sonic-3.5"

    window.provider.setCurrentText("resemble")
    qt_app.processEvents()
    window.refresh_models()
    assert window.current_model_id() == "resemble-ultra"
    window.close()


def test_phase106_does_not_change_database_schema(tmp_path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase106-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
