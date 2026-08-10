from __future__ import annotations

from datetime import datetime, timezone

from app.models import AppSettings
from app.models.api_profile import ApiProfile
from app.models.provider_cost_quota_limits import (
    ProviderCostInsight,
    ProviderCostQuotaLimitRow,
    ProviderCostQuotaLimitsSnapshot,
    ProviderQuotaInsight,
    ProviderRequestLimitInsight,
)
from app.services.api_profile_service import ApiProfileService
from app.services.generation_cost_capacity_service import GenerationCostCapacityService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.unified_voice_model_catalog_service import UnifiedVoiceModelCatalogService
from app.services.voice_service import VoiceModelItem


class ProviderCostQuotaLimitsService:
    """Compose cached/configured cost, quota, and request-limit intelligence.

    Phase 107 deliberately performs no implicit billing, admin, or provider usage API
    calls.  Pricing is trusted only when S-Talking already has a configured rate,
    quota is trusted only when an account/catalog snapshot contains it, and request
    limits come from the provider contract or cached model metadata.
    """

    def __init__(
        self,
        profiles: ApiProfileService,
        providers: ProviderCatalogService,
        catalog: UnifiedVoiceModelCatalogService,
        cost_capacity: GenerationCostCapacityService,
    ) -> None:
        self.profiles = profiles
        self.providers = providers
        self.catalog = catalog
        self.cost_capacity = cost_capacity

    def snapshot(
        self,
        base_settings: AppSettings,
        *,
        project_id: int | None,
        scoped_characters: int,
        provider_ids: tuple[str, ...] | None = None,
    ) -> ProviderCostQuotaLimitsSnapshot:
        scoped = max(0, int(scoped_characters))
        ids = provider_ids if provider_ids is not None else self.providers.provider_ids()
        rows = tuple(
            self.provider_row(
                provider_id,
                base_settings,
                project_id=project_id,
                scoped_characters=scoped,
            )
            for provider_id in ids
        )
        return ProviderCostQuotaLimitsSnapshot(
            rows=rows,
            scoped_characters=scoped,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def provider_row(
        self,
        provider_id: str,
        base_settings: AppSettings,
        *,
        project_id: int | None,
        scoped_characters: int,
    ) -> ProviderCostQuotaLimitRow:
        provider_id = str(provider_id or "").strip().casefold()
        manifest = self.providers.manifest_for(provider_id)
        settings, profile_name = self.catalog.settings_for_provider(provider_id, base_settings)
        profile = self._profile(settings.active_api_profile_id, provider_id)
        models = self.catalog.models_for_provider(provider_id, base_settings)
        model = self._selected_model(
            provider_id,
            settings,
            models,
            current_provider_id=str(base_settings.provider or "").strip().casefold(),
        )
        model_id = (
            model.model_id
            if model is not None
            else str(settings.model_id or "")
            if provider_id == str(base_settings.provider or "").strip().casefold()
            else "*"
        )
        scoped = max(0, int(scoped_characters))

        cost = self._cost(
            project_id=project_id,
            provider_id=provider_id,
            model_id=model_id,
            characters=scoped,
            locality=manifest.locality,
        )
        quota = self._quota(
            provider_id=provider_id,
            profile=profile,
            scoped_characters=scoped,
            locality=manifest.locality,
            settings=settings,
        )
        request_limit = self._request_limit(
            provider_id=provider_id,
            model=model,
            manifest=manifest,
        )
        state, summary = self._state(cost, quota, request_limit)
        return ProviderCostQuotaLimitRow(
            provider_id=provider_id,
            provider_name=manifest.display_name,
            locality=manifest.locality,
            profile_id=profile.profile_id if profile else settings.active_api_profile_id,
            profile_name=profile.display_name if profile else profile_name,
            model_id=model_id,
            scoped_characters=scoped,
            cost=cost,
            quota=quota,
            request_limit=request_limit,
            state=state,
            summary=summary,
        )

    def filtered_rows(
        self,
        snapshot: ProviderCostQuotaLimitsSnapshot,
        *,
        query: str = "",
        provider_id: str | None = None,
        attention_only: bool = False,
    ) -> tuple[ProviderCostQuotaLimitRow, ...]:
        needle = str(query or "").strip().casefold()
        rows: list[ProviderCostQuotaLimitRow] = []
        for row in snapshot.rows:
            if provider_id and row.provider_id != provider_id:
                continue
            if attention_only and row.state not in {"warning", "blocked"}:
                continue
            if needle and needle not in row.search_text:
                continue
            rows.append(row)
        return tuple(rows)

    def _cost(
        self,
        *,
        project_id: int | None,
        provider_id: str,
        model_id: str,
        characters: int,
        locality: str,
    ) -> ProviderCostInsight:
        if locality == "local":
            return ProviderCostInsight(
                state="known",
                estimated_cost=0.0,
                rate_per_million_characters=0.0,
                currency=None,
                source="local-provider-fee",
                message="No provider fee; local hardware/electricity costs are not estimated.",
            )
        try:
            estimate, rate, currency, source = self.cost_capacity.estimate_cost(
                project_id=project_id,
                provider=provider_id,
                model=model_id,
                characters=characters,
            )
        except Exception:
            return ProviderCostInsight(
                state="unknown",
                estimated_cost=None,
                rate_per_million_characters=None,
                currency=None,
                source="unavailable",
                message="Pricing intelligence is unavailable.",
            )
        normalized_source = str(source or "unavailable")
        if rate <= 0 and estimate <= 0 and normalized_source == "policy-default":
            return ProviderCostInsight(
                state="unknown",
                estimated_cost=None,
                rate_per_million_characters=None,
                currency=str(currency or "USD").upper(),
                source="not-configured",
                message="No verified/configured provider rate is available; cost is not inferred.",
            )
        return ProviderCostInsight(
            state="known",
            estimated_cost=max(0.0, float(estimate)),
            rate_per_million_characters=max(0.0, float(rate)),
            currency=str(currency or "USD").upper(),
            source=normalized_source,
            message="Estimate uses the configured S-Talking pricing rate; it is not a live invoice value.",
        )

    def _quota(
        self,
        *,
        provider_id: str,
        profile: ApiProfile | None,
        scoped_characters: int,
        locality: str,
        settings: AppSettings,
    ) -> ProviderQuotaInsight:
        if locality == "local":
            return ProviderQuotaInsight(
                state="not_applicable",
                remaining=None,
                limit=None,
                used=None,
                usage_percent=None,
                batch_percent_of_remaining=None,
                shortfall=0,
                source="local-runtime",
                message="No provider billing quota applies to local synthesis.",
            )

        remaining = profile.remaining_characters if profile else None
        limit = profile.character_limit if profile else None
        source = "account-profile" if remaining is not None else ""
        if remaining is None:
            catalog = self.catalog.voices.available_catalog(settings, allow_stale=True)
            if catalog is not None and catalog.account is not None:
                remaining = catalog.account.remaining_characters
                limit = catalog.account.character_limit
                if remaining is not None:
                    source = "cached-account-catalog"

        if remaining is None:
            capabilities = self.providers.capabilities_for(provider_id, settings)
            if capabilities.supports_quota_lookup:
                message = "Provider supports quota lookup, but no confirmed snapshot is currently cached."
                source = "not-checked"
            else:
                message = "Current S-Talking adapter does not report a provider billing quota."
                source = "not-reported"
            return ProviderQuotaInsight(
                state="unknown",
                remaining=None,
                limit=limit,
                used=None,
                usage_percent=None,
                batch_percent_of_remaining=None,
                shortfall=0,
                source=source,
                message=message,
            )

        remaining = max(0, int(remaining))
        limit = max(0, int(limit)) if limit is not None else None
        used = max(0, limit - remaining) if limit is not None else None
        usage_percent = (
            min(100.0, max(0.0, used / limit * 100.0))
            if used is not None and limit
            else None
        )
        batch_percent = (
            scoped_characters / remaining * 100.0
            if remaining > 0 and scoped_characters > 0
            else (100.0 if scoped_characters > 0 and remaining == 0 else 0.0)
        )
        shortfall = max(0, scoped_characters - remaining)
        state = "blocked" if shortfall else "warning" if batch_percent >= 90 else "known"
        if shortfall:
            message = f"Scope exceeds confirmed remaining quota by {shortfall:,} characters."
        elif batch_percent >= 90 and scoped_characters:
            message = f"Scope uses {batch_percent:.0f}% of confirmed remaining quota."
        else:
            message = "Confirmed account quota snapshot."
        return ProviderQuotaInsight(
            state=state,
            remaining=remaining,
            limit=limit,
            used=used,
            usage_percent=usage_percent,
            batch_percent_of_remaining=batch_percent,
            shortfall=shortfall,
            source=source or "account-profile",
            message=message,
        )

    @staticmethod
    def _request_limit(
        *,
        provider_id: str,
        model: VoiceModelItem | None,
        manifest,
    ) -> ProviderRequestLimitInsight:
        if manifest.locality == "local":
            return ProviderRequestLimitInsight(
                state="not_applicable",
                value=None,
                unit="",
                source="local-runtime",
                message="No cloud request-size limit is applied by the provider contract.",
            )

        if provider_id == "google" and model is not None and model.model_id.startswith("gemini-"):
            return ProviderRequestLimitInsight(
                state="known",
                value=4000,
                unit="bytes",
                source="adapter-contract",
                message="Gemini-TTS text is limited to 4,000 bytes; prompt is separately limited to 4,000 bytes and 8,000 bytes combined.",
            )

        if model is not None and model.maximum_text_length:
            return ProviderRequestLimitInsight(
                state="known",
                value=max(1, int(model.maximum_text_length)),
                unit="characters",
                source="model-catalog",
                message="Request limit comes from the provider model catalog/cache.",
            )

        if manifest.synthesis_request_limit is not None:
            return ProviderRequestLimitInsight(
                state="known",
                value=manifest.synthesis_request_limit,
                unit=manifest.synthesis_request_limit_unit or "characters",
                source="provider-contract",
                message=manifest.synthesis_request_limit_note or "Documented provider request limit.",
            )

        return ProviderRequestLimitInsight(
            state="unknown",
            value=None,
            unit="",
            source="not-documented-in-adapter",
            message="No stable request-size limit is encoded in the current S-Talking provider contract.",
        )

    @staticmethod
    def _selected_model(
        provider_id: str,
        settings: AppSettings,
        models: tuple[VoiceModelItem, ...],
        *,
        current_provider_id: str,
    ) -> VoiceModelItem | None:
        if not models:
            return None
        selected = next((model for model in models if model.model_id == settings.model_id), None)
        if selected is not None:
            return selected
        if provider_id == current_provider_id:
            return None
        return models[0]

    def _profile(self, profile_id: str | None, provider_id: str) -> ApiProfile | None:
        if profile_id:
            try:
                profile = self.profiles.get_profile(profile_id)
            except ValueError:
                profile = None
            if profile is not None and profile.provider == provider_id:
                return profile
        return self.profiles.active_profile(provider_id)

    @staticmethod
    def _state(
        cost: ProviderCostInsight,
        quota: ProviderQuotaInsight,
        request_limit: ProviderRequestLimitInsight,
    ) -> tuple[str, str]:
        if quota.state == "blocked":
            return "blocked", "Confirmed quota is insufficient for the current scope."
        if quota.state == "warning":
            return "warning", "Confirmed quota is close to the current scope requirement."
        unknowns = sum(
            insight.state == "unknown"
            for insight in (cost, quota, request_limit)
        )
        if unknowns:
            return "warning", f"{unknowns} intelligence field(s) remain unknown; no values were inferred."
        return "known", "Known configured/cached intelligence is available for this provider."
