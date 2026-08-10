from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.models import AppSettings
from app.models.provider_contract import ProviderConfigurationResult
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.openai_speech import OpenAISpeechProvider
from app.providers.optional_adapters import AzureSpeechProvider
from app.services.api_profile_service import ApiProfileService
from app.services.provider_account_catalog_store import ProviderAccountCatalogStore
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.secure_credentials import SecureCredentialStore
from app.services.voice_service import VoiceCatalog, VoiceService


def test_phase100_provider_options_round_trip_and_registry_contract() -> None:
    settings = AppSettings(
        provider="azure",
        provider_options={"region": "northeurope", "endpoint": ""},
    )
    assert settings.model_copy().provider_options["region"] == "northeurope"

    openai = DEFAULT_PROVIDER_REGISTRY.manifest_for("openai")
    azure = DEFAULT_PROVIDER_REGISTRY.manifest_for("azure")
    assert openai.retry_ready is True
    assert openai.controls.api_profile is True
    assert openai.profile_management_ready is True
    assert azure.retry_ready is True
    assert azure.profile_management_ready is True
    assert azure.profile_metadata_fields == ("region", "endpoint")
    assert azure.controls.api_profile is True
    # Later provider phases may promote Google/AWS without changing the Phase 100
    # OpenAI/Azure contract asserted above.


def test_phase100_profile_applies_only_declared_provider_metadata(tmp_path: Path) -> None:
    service = ApiProfileService(
        tmp_path / "profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    profile = service.create_profile(
        "Azure production",
        provider="azure",
        api_key="azure-secret",
        active=True,
        metadata={
            "region": "northeurope",
            "endpoint": "https://example.cognitiveservices.azure.com/",
            "last_sync_result": "connected",
            "voice_count": "42",
        },
    )

    applied = service.apply_profile(
        AppSettings(
            provider="azure",
            active_api_profile_id=profile.profile_id,
            provider_options={"runtime_hint": "keep-me", "region": "stale"},
        ),
        profile.profile_id,
    )

    assert applied.api_key == "azure-secret"
    assert applied.provider_options == {
        "runtime_hint": "keep-me",
        "region": "northeurope",
        "endpoint": "https://example.cognitiveservices.azure.com/",
    }
    assert "last_sync_result" not in applied.provider_options
    assert "azure-secret" not in (tmp_path / "profiles.json").read_text(encoding="utf-8")


def test_phase100_catalog_identity_changes_with_safe_provider_options(tmp_path: Path) -> None:
    store = ProviderAccountCatalogStore(tmp_path / "catalogs")
    first = AppSettings(
        provider="azure",
        api_key="same-secret",
        active_api_profile_id="azure-a",
        provider_options={"region": "northeurope"},
    )
    second = first.model_copy(update={"provider_options": {"region": "westeurope"}})
    assert store.identity_for(first) != store.identity_for(second)


def test_phase100_openai_voice_catalog_respects_legacy_model_limits() -> None:
    modern = AppSettings(
        provider="openai",
        api_key="sk_TEST",
        model_id="gpt-4o-mini-tts",
        voice_id="marin",
    )
    legacy = modern.model_copy(update={"model_id": "tts-1"})
    custom_legacy = legacy.model_copy(update={"voice_id": "voice_custom123"})

    provider = OpenAISpeechProvider(modern)
    try:
        assert provider.validate_configuration(modern).ok is True
        assert provider.validate_configuration(legacy).ok is False
        assert provider.validate_configuration(custom_legacy).ok is False
    finally:
        provider.close()


def test_phase100_openai_live_connection_uses_model_access_probe(monkeypatch) -> None:
    settings = AppSettings(
        provider="openai",
        api_key="sk_TEST",
        model_id="gpt-4o-mini-tts",
        voice_id="alloy",
    )
    provider = OpenAISpeechProvider(settings)
    calls: list[str] = []

    def fake_get(url: str, **_kwargs):
        calls.append(url)
        return httpx.Response(
            200,
            json={"id": "gpt-4o-mini-tts"},
            request=httpx.Request("GET", f"https://api.openai.com{url}"),
        )

    monkeypatch.setattr(provider.client, "get", fake_get)
    try:
        result = provider.test_connection()
    finally:
        provider.close()

    assert result.ok is True
    assert calls == ["/v1/models/gpt-4o-mini-tts"]


def test_phase100_openai_custom_voice_instructions_and_format(monkeypatch) -> None:
    captured: dict[str, object] = {}
    settings = AppSettings(
        provider="openai",
        api_key="sk_TEST",
        model_id="gpt-4o-mini-tts",
        voice_id="voice_custom123",
        output_format="flac",
        provider_options={"instructions": "Speak calmly in Danish."},
    )
    provider = OpenAISpeechProvider(settings)

    def fake_post(url: str, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return httpx.Response(
            200,
            content=b"audio",
            request=httpx.Request("POST", "https://api.openai.com/v1/audio/speech"),
        )

    monkeypatch.setattr(provider.client, "post", fake_post)
    try:
        assert provider.synthesize("Hej", settings) == b"audio"
    finally:
        provider.close()

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["voice"] == {"id": "voice_custom123"}
    assert payload["instructions"] == "Speak calmly in Danish."
    assert captured["headers"] == {"Accept": "audio/flac"}


def test_phase100_openai_transport_error_is_normalized(monkeypatch) -> None:
    settings = AppSettings(
        provider="openai",
        api_key="sk_TEST",
        model_id="gpt-4o-mini-tts",
        voice_id="alloy",
    )
    provider = OpenAISpeechProvider(settings)

    def fail_post(_url: str, **_kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(provider.client, "post", fail_post)
    try:
        with pytest.raises(Exception) as captured:
            provider.synthesize("Hej", settings)
        normalized = provider.normalize_error(captured.value)
    finally:
        provider.close()

    assert normalized.code == "timeout"
    assert normalized.retryable is True


def test_phase100_azure_requires_region_or_endpoint(monkeypatch) -> None:
    settings = AppSettings(provider="azure", api_key="azure-secret")
    provider = AzureSpeechProvider(settings)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    missing = provider.validate_configuration(settings)
    configured = provider.validate_configuration(
        settings.model_copy(update={"provider_options": {"region": "northeurope"}})
    )
    unsafe = provider.validate_configuration(
        settings.model_copy(update={"provider_options": {"endpoint": "http://example.test"}})
    )

    assert missing.ok is False
    assert "region or endpoint" in missing.message
    assert configured.ok is True
    assert unsafe.ok is False
    assert "HTTPS" in unsafe.message


def test_phase100_azure_speech_config_uses_profile_region_or_endpoint() -> None:
    calls: list[dict[str, str]] = []

    class SpeechConfig:
        def __init__(self, **kwargs):
            calls.append(dict(kwargs))

    sdk = SimpleNamespace(SpeechConfig=SpeechConfig)

    AzureSpeechProvider._speech_config(
        AppSettings(
            provider="azure",
            api_key="secret",
            provider_options={"region": "northeurope"},
        ),
        sdk,
    )
    AzureSpeechProvider._speech_config(
        AppSettings(
            provider="azure",
            api_key="secret",
            provider_options={"endpoint": "https://resource.cognitiveservices.azure.com/"},
        ),
        sdk,
    )

    assert calls[0] == {"subscription": "secret", "region": "northeurope"}
    assert calls[1] == {
        "subscription": "secret",
        "endpoint": "https://resource.cognitiveservices.azure.com/",
    }


def test_phase100_azure_ssml_is_safe_and_danish() -> None:
    settings = AppSettings(
        provider="azure",
        voice_id="da-DK-ChristelNeural",
        language_code="da",
        speed=1.1,
    )
    ssml = AzureSpeechProvider.safe_ssml("A & B < C", settings)

    assert "xmlns='http://www.w3.org/2001/10/synthesis'" in ssml
    assert "xml:lang='da-DK'" in ssml
    assert "name='da-DK-ChristelNeural'" in ssml
    assert "rate='+10%'" in ssml
    assert "A &amp; B &lt; C" in ssml


def test_phase100_azure_output_format_mapping() -> None:
    formats = SimpleNamespace(
        Audio24Khz96KBitRateMonoMp3="mp3-enum",
        Riff24Khz16BitMonoPcm="wav-enum",
        Ogg24Khz16BitMonoOpus="opus-enum",
        Raw24Khz16BitMonoPcm="pcm-enum",
    )
    sdk = SimpleNamespace(SpeechSynthesisOutputFormat=formats)

    assert AzureSpeechProvider._sdk_output_format(
        AppSettings(provider="azure", output_format="mp3_44100_128"), sdk
    ) == "mp3-enum"
    assert AzureSpeechProvider._sdk_output_format(
        AppSettings(provider="azure", output_format="wav"), sdk
    ) == "wav-enum"


def test_phase100_voice_service_live_connection_is_provider_generic(monkeypatch) -> None:
    settings = AppSettings(
        provider="openai",
        api_key="sk_TEST",
        model_id="gpt-4o-mini-tts",
        voice_id="alloy",
    )

    class FakeProvider:
        def validate_configuration(self, _settings):
            return ProviderConfigurationResult(True, "valid")

        def test_connection(self):
            return ProviderConfigurationResult(True, "connected")

        def close(self):
            return None

    service = object.__new__(VoiceService)
    service.refresh_catalog = lambda _settings, force=False: VoiceCatalog((), (), None, "now")
    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: FakeProvider())

    result = VoiceService.test_connection(service, settings, force_refresh=True)
    assert result.status == "connected"
    assert result.capability is not None


def test_phase100_provider_accounts_exposes_core_cloud_profiles(qt_app, tmp_path: Path) -> None:
    from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog

    profile_service = ApiProfileService(
        tmp_path / "profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    dialog = ProviderAccountsDialog(
        profile_service,
        voice_service=SimpleNamespace(catalog_store=None, invalidate_provider_cache=lambda *_args, **_kwargs: None),
        settings_provider=lambda: AppSettings(provider="openai", api_key="sk_TEMP"),
        provider_catalog_service=ProviderCatalogService(),
    )
    values = {dialog.provider.itemData(index) for index in range(dialog.provider.count())}
    assert {"elevenlabs", "openai", "azure"}.issubset(values)
    assert dialog.provider.currentData() == "openai"
    dialog.close()


def test_phase100_main_profile_selector_follows_current_provider(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.config.runtime import RuntimeConfig
    from app.container import create_service_container
    from app.gui.main import MainWindow

    runtime = RuntimeConfig.from_root(tmp_path)
    context = create_application_context(create_service_container(runtime))
    profile = context.api_profile_service.create_profile(
        "OpenAI production",
        provider="openai",
        api_key="sk_TEST",
        active=True,
    )
    window = MainWindow(context)
    window.show()
    window.provider.setCurrentText("openai")
    qt_app.processEvents()

    assert window.api_profile.findData(profile.profile_id) >= 0
    window.api_profile.setCurrentIndex(window.api_profile.findData(profile.profile_id))
    assert window.settings().api_key == "sk_TEST"
    window.close()


def test_phase100_does_not_change_database_schema(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase100-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
