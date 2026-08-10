from __future__ import annotations

import pytest

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.exceptions import ProviderError
from app.gui.dialogs.provider_cost_quota_limits_dialog import ProviderCostQuotaLimitsDialog
from app.gui.main import MainWindow
from app.models import AppSettings
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.murf import MURF_MAX_TEXT_CHARACTERS, MurfProvider
from app.services.api_profile_service import ApiProfileService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_cost_quota_limits_service import ProviderCostQuotaLimitsService
from app.services.secure_credentials import SecureCredentialStore
from app.services.unified_voice_model_catalog_service import UnifiedVoiceModelCatalogService
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceModelItem


class _FakeVoiceService:
    def __init__(self, catalogs: dict[str, VoiceCatalog] | None = None) -> None:
        self.catalogs = catalogs or {}
        self.refresh_calls: list[str] = []

    def available_catalog(self, settings, *, allow_stale=False):
        return self.catalogs.get(settings.provider)

    def refresh_catalog(self, settings, *, force=False):
        self.refresh_calls.append(settings.provider)
        raise AssertionError("Phase 107 intelligence must not refresh provider catalogs implicitly")


class _FakeCost:
    def __init__(self, rates: dict[tuple[str, str], tuple[float, str, str]] | None = None) -> None:
        self.rates = rates or {}
        self.calls: list[tuple[str, str, int]] = []

    def estimate_cost(self, *, project_id, provider, model, characters, retry_characters=0):
        self.calls.append((provider, model, characters))
        rate, currency, source = self.rates.get(
            (provider, model),
            self.rates.get((provider, "*"), (0.0, "USD", "policy-default")),
        )
        billable = max(0, int(characters)) + max(0, int(retry_characters))
        return billable / 1_000_000.0 * rate, rate, currency, source


def _profiles(tmp_path) -> ApiProfileService:
    return ApiProfileService(
        tmp_path / "api-profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )


def _service(tmp_path, *, catalogs=None, rates=None):
    profiles = _profiles(tmp_path)
    provider_catalog = ProviderCatalogService()
    voices = _FakeVoiceService(catalogs)
    unified = UnifiedVoiceModelCatalogService(profiles, provider_catalog, voices)
    service = ProviderCostQuotaLimitsService(
        profiles,
        provider_catalog,
        unified,
        _FakeCost(rates),
    )
    return service, profiles, voices


def test_phase107_registry_encodes_only_stable_request_limits() -> None:
    registry = DEFAULT_PROVIDER_REGISTRY
    openai = registry.manifest_for("openai")
    google = registry.manifest_for("google")
    polly = registry.manifest_for("aws_polly")
    murf = registry.manifest_for("murf")
    cartesia = registry.manifest_for("cartesia")

    assert (openai.synthesis_request_limit, openai.synthesis_request_limit_unit) == (4096, "characters")
    assert (google.synthesis_request_limit, google.synthesis_request_limit_unit) == (5000, "bytes")
    assert (polly.synthesis_request_limit, polly.synthesis_request_limit_unit) == (3000, "billed_characters")
    assert "6,000 total" in polly.synthesis_request_limit_note
    assert (murf.synthesis_request_limit, murf.synthesis_request_limit_unit) == (3000, "characters")
    assert cartesia.synthesis_request_limit is None


def test_phase107_local_provider_reports_zero_provider_fee_without_inventing_quota(tmp_path) -> None:
    service, _profiles, voices = _service(tmp_path)

    row = service.provider_row(
        "piper",
        AppSettings(provider="piper", model_id="piper-local"),
        project_id=None,
        scoped_characters=25_000,
    )

    assert row.cost.estimated_cost == 0.0
    assert row.cost.source == "local-provider-fee"
    assert row.quota.state == "not_applicable"
    assert row.request_limit.state == "not_applicable"
    assert voices.refresh_calls == []


def test_phase107_unknown_cloud_pricing_stays_unknown_instead_of_becoming_free(tmp_path) -> None:
    service, _profiles, _voices = _service(tmp_path)

    row = service.provider_row(
        "openai",
        AppSettings(provider="openai", model_id="gpt-4o-mini-tts"),
        project_id=None,
        scoped_characters=50_000,
    )

    assert row.cost.estimated_cost is None
    assert row.cost.rate_per_million_characters is None
    assert row.cost.source == "not-configured"
    assert row.state == "warning"


def test_phase107_configured_rate_drives_cost_estimate_without_live_billing_call(tmp_path) -> None:
    service, _profiles, _voices = _service(
        tmp_path,
        rates={
            ("openai", "gpt-4o-mini-tts"): (15.0, "USD", "manual-provider-docs"),
        },
    )

    row = service.provider_row(
        "openai",
        AppSettings(provider="openai", model_id="gpt-4o-mini-tts"),
        project_id=7,
        scoped_characters=100_000,
    )

    assert row.cost.estimated_cost == pytest.approx(1.5)
    assert row.cost.rate_per_million_characters == 15.0
    assert row.cost.currency == "USD"
    assert row.cost.source == "manual-provider-docs"
    assert "not a live invoice" in row.cost.message


def test_phase107_confirmed_profile_quota_detects_shortfall(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profile = profiles.create_profile(
        "ElevenLabs Production",
        provider="elevenlabs",
        api_key="secret",
        active=True,
    )
    profile.remaining_characters = 2_000
    profile.character_limit = 10_000
    profiles.update_profile(profile)

    row = service.provider_row(
        "elevenlabs",
        AppSettings(provider="elevenlabs", active_api_profile_id=profile.profile_id),
        project_id=None,
        scoped_characters=2_500,
    )

    assert row.quota.remaining == 2_000
    assert row.quota.limit == 10_000
    assert row.quota.used == 8_000
    assert row.quota.shortfall == 500
    assert row.quota.state == "blocked"
    assert row.state == "blocked"


def test_phase107_cached_account_catalog_can_confirm_quota_without_network(tmp_path) -> None:
    catalog = VoiceCatalog(
        voices=(),
        models=(VoiceModelItem("eleven_multilingual_v2", "Eleven Multilingual v2", ()),),
        account=AccountUsage("creator", "active", 4_000, 10_000),
        refreshed_at="2026-08-10T12:00:00+00:00",
    )
    service, profiles, voices = _service(tmp_path, catalogs={"elevenlabs": catalog})
    profile = profiles.create_profile("ElevenLabs", provider="elevenlabs", api_key="secret", active=True)

    row = service.provider_row(
        "elevenlabs",
        AppSettings(provider="elevenlabs", active_api_profile_id=profile.profile_id),
        project_id=None,
        scoped_characters=1_000,
    )

    assert row.quota.remaining == 6_000
    assert row.quota.source == "cached-account-catalog"
    assert voices.refresh_calls == []


def test_phase107_missing_cloud_quota_is_unknown_not_zero(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    profile = profiles.create_profile("OpenAI", provider="openai", api_key="secret", active=True)

    row = service.provider_row(
        "openai",
        AppSettings(provider="openai", active_api_profile_id=profile.profile_id, model_id="gpt-4o-mini-tts"),
        project_id=None,
        scoped_characters=10_000,
    )

    assert row.quota.remaining is None
    assert row.quota.state == "unknown"
    assert row.quota.shortfall == 0
    assert row.quota.source == "not-reported"


def test_phase107_model_catalog_limit_overrides_provider_default_when_available(tmp_path) -> None:
    catalog = VoiceCatalog(
        voices=(),
        models=(
            VoiceModelItem(
                "eleven_multilingual_v2",
                "Eleven Multilingual v2",
                (),
                maximum_text_length=10_000,
            ),
        ),
        account=None,
        refreshed_at="2026-08-10T12:00:00+00:00",
    )
    service, profiles, _voices = _service(tmp_path, catalogs={"elevenlabs": catalog})
    profile = profiles.create_profile("ElevenLabs", provider="elevenlabs", api_key="secret", active=True)

    row = service.provider_row(
        "elevenlabs",
        AppSettings(
            provider="elevenlabs",
            active_api_profile_id=profile.profile_id,
            model_id="eleven_multilingual_v2",
        ),
        project_id=None,
        scoped_characters=1_000,
    )

    assert row.request_limit.value == 10_000
    assert row.request_limit.unit == "characters"
    assert row.request_limit.source == "model-catalog"


def test_phase107_google_gemini_limit_keeps_byte_semantics(tmp_path) -> None:
    service, profiles, _voices = _service(tmp_path)
    google = profiles.create_profile("Google ADC", provider="google", active=True)

    row = service.provider_row(
        "google",
        AppSettings(
            provider="google",
            active_api_profile_id=google.profile_id,
            model_id="gemini-2.5-flash-tts",
        ),
        project_id=None,
        scoped_characters=2_000,
    )

    assert row.request_limit.value == 4_000
    assert row.request_limit.unit == "bytes"
    assert "8,000 bytes combined" in row.request_limit.message


def test_phase107_murf_model_limit_is_centralized_and_runtime_enforced() -> None:
    assert MURF_MAX_TEXT_CHARACTERS == 3000
    provider = MurfProvider(
        AppSettings(
            provider="murf",
            api_key="secret",
            voice_id="voice",
            model_id="GEN2",
            language_code="en-US",
            output_format="mp3",
        )
    )
    try:
        with pytest.raises(ProviderError) as exc:
            provider.synthesize("x" * (MURF_MAX_TEXT_CHARACTERS + 1), provider.settings)
    finally:
        provider.close()
    assert exc.value.provider_code == "input_too_large"


def test_phase107_snapshot_and_filters_are_provider_ordered_and_cached_only(tmp_path) -> None:
    service, _profiles, voices = _service(tmp_path)
    snapshot = service.snapshot(
        AppSettings(provider="mock"),
        project_id=None,
        scoped_characters=1234,
        provider_ids=("mock", "openai", "murf"),
    )

    assert [row.provider_id for row in snapshot.rows] == ["mock", "openai", "murf"]
    assert snapshot.provider_count == 3
    assert service.filtered_rows(snapshot, provider_id="openai")[0].provider_id == "openai"
    assert service.filtered_rows(snapshot, query="provider fee")[0].provider_id == "mock"
    empty = service.snapshot(
        AppSettings(provider="mock"),
        project_id=None,
        scoped_characters=0,
        provider_ids=(),
    )
    assert empty.rows == ()
    assert voices.refresh_calls == []


def test_phase107_dialog_is_cached_only_and_surfaces_scope(qt_app, tmp_path) -> None:
    service, _profiles, voices = _service(tmp_path)
    dialog = ProviderCostQuotaLimitsDialog(
        service,
        lambda: AppSettings(provider="mock"),
        project_id=None,
        scoped_characters=4_321,
    )
    dialog.show()
    qt_app.processEvents()

    assert "4,321" in dialog.summary.text()
    assert dialog.table.rowCount() == len(service.providers.provider_ids())
    assert voices.refresh_calls == []
    dialog.close()


def test_phase107_context_wires_intelligence_service(tmp_path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    context = create_application_context(create_service_container(runtime))

    service = context.provider_cost_quota_limits_service
    assert service.profiles is context.api_profile_service
    assert service.catalog is context.unified_voice_model_catalog_service
    assert service.cost_capacity is context.generation_cost_capacity_service


def test_phase107_main_exposes_provider_cost_quota_limits_action(qt_app, tmp_path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    action = window.actions_by_name["Provider Cost / Quota / Limits"]
    assert action.shortcut().toString() == "Ctrl+Alt+C"
    dialog = window.open_provider_cost_quota_limits()
    qt_app.processEvents()
    assert dialog.windowTitle() == "Provider Cost / Quota / Limits Intelligence"
    dialog.close()
    window.close()


def test_phase107_does_not_change_database_schema(tmp_path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase107-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
