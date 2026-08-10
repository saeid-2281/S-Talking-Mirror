from __future__ import annotations

from pathlib import Path

from app.models.api_profile import ApiProfile, ApiProfileStatus
from app.models.domain import AppSettings
from app.models.offline_tts_engine import OfflineEngineSnapshot, OfflineVoiceDescriptor
from app.models.provider_cost_quota_limits import (
    ProviderCostInsight,
    ProviderCostQuotaLimitRow,
    ProviderQuotaInsight,
    ProviderRequestLimitInsight,
)
from app.models.provider_identity import ProviderReadiness
from app.models.provider_manifest import ProviderControlPolicy, ProviderManifest
from app.models.unified_voice_model_catalog import (
    UnifiedCatalogItem,
    UnifiedCatalogSource,
    UnifiedVoiceModelCatalog,
)
from app.provider_registry import ProviderRegistry
from app.services.smart_provider_routing_service import SmartProviderRoutingService
from app.services.voice_service import VoiceModelItem


class _Readiness:
    def __init__(self, states: dict[str, tuple[str, str]] | None = None) -> None:
        self.states = states or {}

    def readiness_for(self, provider_id: str, settings: AppSettings) -> ProviderReadiness:
        state, reason = self.states.get(provider_id, ("Ready", "Configured route ready"))
        return ProviderReadiness(
            provider_id=provider_id,
            display_name=provider_id.title(),
            state=state,
            reason=reason,
            adapter_registered=True,
            dependency_installed=True,
            credential_setup_available=True,
            model_listing_implemented=True,
            voice_listing_implemented=True,
            language_handling_implemented=True,
            synthesis_implemented=True,
            output_format_supported=True,
            cancellation_implemented=True,
            atomic_output_implemented=True,
            retry_implemented=True,
            error_normalization_implemented=True,
            preflight_integration_implemented=True,
            gui_settings_implemented=True,
        )


class _Offline:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    def snapshot(self, engine_id: str, settings: AppSettings) -> OfflineEngineSnapshot:
        assert engine_id == "piper"
        voice = OfflineVoiceDescriptor(
            engine_id="piper",
            voice_id="da",
            display_name="Danish Piper",
            model_path="C:/voices/da.onnx",
            config_path="C:/voices/da.onnx.json",
            language_code="da",
            config_present=True,
            selected=True,
        )
        return OfflineEngineSnapshot(
            engine_id="piper",
            display_name="Piper",
            provider_id="piper",
            dependency_name="piper",
            installed=self.ready,
            module_available=self.ready,
            executable_path=None,
            runtime_mode="python-api" if self.ready else "unavailable",
            configured=self.ready,
            ready=self.ready,
            selected_voice_id="da" if self.ready else None,
            voices=(voice,) if self.ready else (),
            accelerators=("CPU",),
            state="Runtime warm" if self.ready else "Setup required",
            summary="Piper is ready." if self.ready else "Piper needs setup.",
        )


class _Profiles:
    def __init__(self, profiles: dict[str, ApiProfile] | None = None) -> None:
        self.profiles = profiles or {}

    def get_profile(self, profile_id: str) -> ApiProfile:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            raise ValueError(profile_id) from exc

    def active_profile(self, provider_id: str) -> ApiProfile | None:
        return next(
            (profile for profile in self.profiles.values() if profile.provider == provider_id and profile.active),
            None,
        )


class _Catalog:
    def __init__(
        self,
        registry: ProviderRegistry,
        profiles: _Profiles,
        languages: dict[str, tuple[str, ...]] | None = None,
        *,
        missing_catalog: set[str] | None = None,
    ) -> None:
        self.registry = registry
        self.profiles = profiles
        self.languages_by_provider = languages or {}
        self.missing_catalog = missing_catalog or set()
        self.refresh_called = False

    def settings_for_provider(self, provider_id: str, base: AppSettings):
        profile = self.profiles.active_profile(provider_id)
        update = {
            "provider": provider_id,
            "api_key": base.api_key if provider_id == base.provider else "",
            "active_api_profile_id": profile.profile_id if profile else None,
            "provider_options": {},
        }
        if profile and self.registry.manifest_for(provider_id).profile_secret_required:
            update["api_key"] = "profile-secret"
        return base.model_copy(update=update), profile.display_name if profile else None

    def snapshot(self, base: AppSettings, *, provider_ids, allow_stale=True):
        assert allow_stale is True
        provider_id = provider_ids[0]
        manifest = self.registry.manifest_for(provider_id)
        if provider_id in self.missing_catalog:
            return UnifiedVoiceModelCatalog(
                sources=(
                    UnifiedCatalogSource(
                        provider_id=provider_id,
                        provider_name=manifest.display_name,
                        profile_id=None,
                        profile_name=None,
                        state="not_refreshed",
                        voice_count=0,
                        model_count=0,
                    ),
                ),
                items=(),
                generated_at="now",
            )
        languages = self.languages_by_provider.get(provider_id, ("da-DK",))
        items = (
            UnifiedCatalogItem(
                key=f"{provider_id}:voice",
                kind="voice",
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=None,
                profile_name=None,
                item_id=f"{provider_id}-voice",
                name=f"{manifest.display_name} Danish",
                languages=languages,
            ),
            UnifiedCatalogItem(
                key=f"{provider_id}:model",
                kind="model",
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=None,
                profile_name=None,
                item_id=f"{provider_id}-model",
                name=f"{manifest.display_name} model",
                languages=languages,
            ),
        )
        return UnifiedVoiceModelCatalog(
            sources=(
                UnifiedCatalogSource(
                    provider_id=provider_id,
                    provider_name=manifest.display_name,
                    profile_id=None,
                    profile_name=None,
                    state="cached",
                    voice_count=1,
                    model_count=1,
                ),
            ),
            items=items,
            generated_at="now",
        )

    def models_for_provider(self, provider_id: str, base: AppSettings):
        if provider_id in self.missing_catalog:
            return ()
        return (VoiceModelItem(f"{provider_id}-model", f"{provider_id} model", ("da-DK",)),)

    def refresh_provider(self, *_args, **_kwargs):
        self.refresh_called = True
        raise AssertionError("Smart Routing v2 must never refresh provider catalogs")


class _Intelligence:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        costs: dict[str, float | None] | None = None,
        quotas: dict[str, int | None] | None = None,
        limits: dict[str, tuple[int | None, str]] | None = None,
    ) -> None:
        self.registry = registry
        self.costs = costs or {}
        self.quotas = quotas or {}
        self.limits = limits or {}

    def provider_row(self, provider_id: str, _settings, *, project_id, scoped_characters):
        del project_id
        manifest = self.registry.manifest_for(provider_id)
        cost = self.costs.get(provider_id)
        remaining = self.quotas.get(provider_id)
        limit_value, limit_unit = self.limits.get(provider_id, (None, ""))
        shortfall = max(0, scoped_characters - remaining) if remaining is not None else 0
        return ProviderCostQuotaLimitRow(
            provider_id=provider_id,
            provider_name=manifest.display_name,
            locality=manifest.locality,
            profile_id=None,
            profile_name=None,
            model_id=f"{provider_id}-model",
            scoped_characters=scoped_characters,
            cost=ProviderCostInsight(
                state="known" if cost is not None else "unknown",
                estimated_cost=cost,
                rate_per_million_characters=1.0 if cost is not None else None,
                currency="USD" if cost is not None else None,
                source="configured" if cost is not None else "not-configured",
                message="test",
            ),
            quota=ProviderQuotaInsight(
                state="blocked" if shortfall else "known" if remaining is not None else "unknown",
                remaining=remaining,
                limit=remaining,
                used=0 if remaining is not None else None,
                usage_percent=0.0 if remaining is not None else None,
                batch_percent_of_remaining=0.0 if remaining else None,
                shortfall=shortfall,
                source="test",
                message="test quota",
            ),
            request_limit=ProviderRequestLimitInsight(
                state="known" if limit_value is not None else "unknown",
                value=limit_value,
                unit=limit_unit,
                source="test",
                message="test limit",
            ),
            state="blocked" if shortfall else "known",
            summary="test",
        )


def _registry() -> ProviderRegistry:
    common = ProviderControlPolicy(api_profile=True, voice_browser_fallback=True, model_listing_fallback=True)
    return ProviderRegistry(
        (
            ProviderManifest("mock", "Mock", "local", "none", "test", controls=ProviderControlPolicy(voice_required=False)),
            ProviderManifest("piper", "Piper", "local", "none", "local_model", controls=ProviderControlPolicy(local_model_path=True, voice_required=False)),
            ProviderManifest("elevenlabs", "ElevenLabs", "cloud", "profile_or_key", "credential", placeholder_api_key=True, profile_management_ready=True, controls=common),
            ProviderManifest("cartesia", "Cartesia", "cloud", "profile_or_key", "credential", placeholder_api_key=True, profile_management_ready=True, controls=common),
            ProviderManifest("deepgram", "Deepgram", "cloud", "profile_or_key", "credential", placeholder_api_key=True, profile_management_ready=True, controls=common),
        )
    )


def _profile(provider: str, *, remaining: int = 100_000, status=ApiProfileStatus.READY) -> ApiProfile:
    return ApiProfile(
        profile_id=f"{provider}-profile",
        display_name=f"{provider} account",
        provider=provider,
        active=True,
        has_saved_key=True,
        remaining_characters=remaining,
        character_limit=100_000,
        status=status,
    )


def _service(
    *,
    piper_ready: bool = True,
    readiness=None,
    costs=None,
    quotas=None,
    limits=None,
    languages=None,
    missing_catalog=None,
    profiles=None,
):
    registry = _registry()
    profile_service = _Profiles(profiles or {
        "elevenlabs-profile": _profile("elevenlabs"),
        "cartesia-profile": _profile("cartesia"),
        "deepgram-profile": _profile("deepgram"),
    })
    catalog = _Catalog(registry, profile_service, languages, missing_catalog=missing_catalog)
    service = SmartProviderRoutingService(
        _Readiness(readiness),
        _Offline(piper_ready),
        None,
        registry,
        provider_cost_quota_limits_service=_Intelligence(
            registry,
            costs=costs,
            quotas=quotas,
            limits=limits,
        ),
        unified_catalog_service=catalog,
        api_profile_service=profile_service,
    )
    return service, catalog


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="",
        active_api_profile_id="elevenlabs-profile",
        model_id="elevenlabs-model",
        voice_id="elevenlabs-voice",
        language_code="da",
        piper_model_path="C:/voices/da.onnx",
    )
    return base.model_copy(update=updates)


def _analyze(service: SmartProviderRoutingService, **kwargs):
    return service.analyze(
        settings=_settings(),
        scoped_jobs=4,
        scoped_characters=2_000,
        project_id=1,
        current_profile=_profile("elevenlabs"),
        largest_job_characters=600,
        largest_job_bytes=600,
        **kwargs,
    )


def test_phase108_does_not_change_database_schema(tmp_path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase108-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23


def test_phase108_ranks_all_registry_routes_without_refreshing_catalogs() -> None:
    service, catalog = _service(costs={"elevenlabs": 0.2, "cartesia": 0.1}, quotas={"elevenlabs": 50_000, "cartesia": 50_000})
    state = _analyze(service, preference="balanced")

    assert {item.provider_id for item in state.candidates} == {"mock", "piper", "elevenlabs", "cartesia", "deepgram"}
    assert [item.rank for item in state.candidates] == list(range(1, len(state.candidates) + 1))
    assert catalog.refresh_called is False
    assert state.no_automatic_failover is True


def test_phase108_privacy_prefers_ready_piper_but_only_as_explicit_action() -> None:
    service, _ = _service(costs={"elevenlabs": 0.2}, quotas={"elevenlabs": 50_000})
    state = _analyze(service, preference="privacy")

    assert state.recommends_piper
    assert state.action_label == "Use Piper offline"
    assert state.action_enabled is True
    assert "not applied automatically" in state.recommendation


def test_phase108_unknown_current_cloud_price_never_triggers_lowest_cost_switch() -> None:
    service, _ = _service(costs={"cartesia": 0.01}, quotas={"elevenlabs": 50_000, "cartesia": 50_000})
    state = _analyze(service, preference="lowest_cost")

    assert state.recommended_provider_id == "elevenlabs"
    assert state.switch_required is False
    assert "pricing is unknown" in state.recommendation


def test_phase108_confirmed_quota_shortfall_can_recommend_an_evidence_backed_cloud_route() -> None:
    service, _ = _service(
        piper_ready=False,
        costs={"elevenlabs": 0.2, "cartesia": 0.1},
        quotas={"elevenlabs": 1_000, "cartesia": 50_000},
        limits={"cartesia": (5_000, "characters")},
    )
    state = _analyze(service, preference="balanced")

    assert state.current_candidate.blocked is True
    assert state.recommended_provider_id == "cartesia"
    assert state.action_label == "Review Cartesia"
    assert state.action_enabled is True


def test_phase108_danish_certification_failure_blocks_deepgram_even_with_cached_catalog() -> None:
    service, _ = _service(
        readiness={"deepgram": ("Ready", "Deepgram Aura Danish is not certified in S-Talking.")},
        costs={"deepgram": 0.0},
        quotas={"deepgram": 50_000},
    )
    state = _analyze(service, preference="lowest_cost")
    deepgram = next(item for item in state.candidates if item.provider_id == "deepgram")

    assert deepgram.language_state == "blocked"
    assert deepgram.eligible is False
    assert deepgram.score == 0
    assert state.recommended_provider_id != "deepgram"


def test_phase108_request_limit_uses_largest_job_not_total_scope() -> None:
    service, _ = _service(
        costs={"cartesia": 0.01},
        quotas={"cartesia": 50_000},
        limits={"cartesia": (500, "characters")},
    )
    state = service.analyze(
        settings=_settings(),
        scoped_jobs=2,
        scoped_characters=700,
        largest_job_characters=600,
        largest_job_bytes=600,
        project_id=1,
        current_profile=_profile("elevenlabs"),
        preference="balanced",
    )
    cartesia = next(item for item in state.candidates if item.provider_id == "cartesia")

    assert cartesia.request_limit_state == "blocked"
    assert any("Largest job exceeds" in blocker for blocker in cartesia.blockers)


def test_phase108_byte_limit_uses_utf8_byte_measurement_input() -> None:
    service, _ = _service(
        costs={"cartesia": 0.01},
        quotas={"cartesia": 50_000},
        limits={"cartesia": (700, "bytes")},
    )
    state = service.analyze(
        settings=_settings(),
        scoped_jobs=1,
        scoped_characters=400,
        largest_job_characters=400,
        largest_job_bytes=800,
        project_id=1,
        current_profile=_profile("elevenlabs"),
    )
    cartesia = next(item for item in state.candidates if item.provider_id == "cartesia")
    assert cartesia.request_limit_state == "blocked"


def test_phase108_missing_catalog_evidence_does_not_trigger_cross_provider_switch() -> None:
    service, _ = _service(
        costs={"cartesia": 0.0},
        quotas={"cartesia": 50_000},
        missing_catalog={"cartesia"},
    )
    state = _analyze(service, preference="balanced")
    cartesia = next(item for item in state.candidates if item.provider_id == "cartesia")

    assert cartesia.voice_state == "review"
    assert cartesia.model_state == "review"
    assert state.recommended_provider_id != "cartesia"


def test_phase108_generation_active_disables_recommended_action() -> None:
    service, _ = _service(costs={"elevenlabs": 0.2}, quotas={"elevenlabs": 50_000})
    state = _analyze(service, preference="privacy", generation_active=True)
    assert state.recommends_piper
    assert state.action_enabled is False


def test_phase108_cloud_first_keeps_ready_current_cloud_route() -> None:
    service, _ = _service(costs={"elevenlabs": 0.5, "cartesia": 0.01}, quotas={"elevenlabs": 50_000, "cartesia": 50_000})
    state = _analyze(service, preference="cloud_first")
    assert state.recommended_provider_id == "elevenlabs"


def test_phase108_mock_never_becomes_alternative_production_recommendation() -> None:
    service, _ = _service(costs={"mock": 0.0}, quotas={})
    state = _analyze(service, preference="lowest_cost")
    mock = next(item for item in state.candidates if item.provider_id == "mock")
    assert mock.eligible is False
    assert state.recommended_provider_id != "mock"


def test_phase108_unusable_account_blocks_route() -> None:
    profiles = {
        "elevenlabs-profile": _profile("elevenlabs"),
        "cartesia-profile": _profile("cartesia", status=ApiProfileStatus.INVALID),
        "deepgram-profile": _profile("deepgram"),
    }
    service, _ = _service(profiles=profiles, costs={"cartesia": 0.0}, quotas={"cartesia": 50_000})
    state = _analyze(service, preference="balanced")
    cartesia = next(item for item in state.candidates if item.provider_id == "cartesia")
    assert cartesia.eligible is False
    assert any("not usable" in blocker for blocker in cartesia.blockers)


def test_phase108_connection_failure_blocks_current_route_without_hidden_switch() -> None:
    service, _ = _service(costs={"cartesia": 0.1}, quotas={"cartesia": 50_000})
    state = _analyze(service, connection_status="Connection failed: timeout")
    assert state.current_candidate.blocked is True
    assert state.no_automatic_failover is True
    assert "not applied automatically" in state.recommendation or state.recommended_provider_id == "elevenlabs"


def test_phase108_routing_state_exposes_explainable_decision_factors() -> None:
    service, _ = _service(costs={"elevenlabs": 0.2}, quotas={"elevenlabs": 50_000})
    state = _analyze(service, preference="balanced")
    assert state.engine_version == 2
    assert any(item.startswith("preference=") for item in state.decision_factors)
    assert state.confidence in {"low", "medium", "high"}


def test_phase108_normalizes_new_reliability_preference() -> None:
    assert SmartProviderRoutingService.normalize_preference("reliability") == "reliability"
    assert SmartProviderRoutingService.normalize_preference("bogus") == "balanced"


def test_phase108_analysis_does_not_mutate_generation_settings() -> None:
    service, _ = _service(costs={"elevenlabs": 0.2, "cartesia": 0.01}, quotas={"elevenlabs": 50_000, "cartesia": 50_000})
    settings = _settings()
    original = settings.model_dump()
    service.analyze(
        settings=settings,
        scoped_jobs=3,
        scoped_characters=1_500,
        largest_job_characters=500,
        largest_job_bytes=500,
        project_id=1,
        current_profile=_profile("elevenlabs"),
        preference="reliability",
    )
    assert settings.model_dump() == original


def test_phase108_piper_model_path_remains_explicit_selection_payload() -> None:
    service, _ = _service(costs={"elevenlabs": 0.2}, quotas={"elevenlabs": 50_000})
    state = _analyze(service, preference="privacy")
    assert Path(state.piper_candidate.selected_model_path or "").name == "da.onnx"
