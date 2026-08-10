from __future__ import annotations

from pathlib import Path

from app.models.api_profile import ApiProfile
from app.models.domain import AppSettings
from app.models.smart_provider_routing import (
    ROUTING_PREFERENCES,
    ProviderRouteCandidate,
    SmartProviderRoutingState,
)
from app.services.offline_tts_engine_service import OfflineTTSEngineService
from app.services.provider_readiness_service import ProviderReadinessService


class SmartProviderRoutingService:
    """Build a deterministic, read-only cloud/offline routing recommendation.

    Phase 98 never changes provider settings and never probes the network.  The
    recommendation compares the currently configured provider with the already
    configured Piper runtime using cached/local readiness, confirmed quota and
    the existing cost policy.  Applying a recommendation remains a MainWindow
    user action before preflight.
    """

    LOCAL_PROVIDERS = {"mock", "piper", "kokoro"}

    def __init__(
        self,
        readiness_service: ProviderReadinessService,
        offline_tts_engine_service: OfflineTTSEngineService,
        cost_capacity_service=None,
    ) -> None:
        self.readiness_service = readiness_service
        self.offline_tts_engine_service = offline_tts_engine_service
        self.cost_capacity_service = cost_capacity_service

    def analyze(
        self,
        *,
        settings: AppSettings,
        scoped_jobs: int,
        scoped_characters: int,
        project_id: int | None,
        current_profile: ApiProfile | None = None,
        connection_status: str = "",
        preference: str = "balanced",
        generation_active: bool = False,
    ) -> SmartProviderRoutingState:
        preference = self.normalize_preference(preference)
        scoped_jobs = max(0, int(scoped_jobs))
        scoped_characters = max(0, int(scoped_characters))
        current = self._current_candidate(
            settings=settings,
            scoped_characters=scoped_characters,
            project_id=project_id,
            profile=current_profile,
            connection_status=connection_status,
        )
        piper = self._piper_candidate(
            settings=settings,
            scoped_characters=scoped_characters,
        )

        recommended = current
        reason = "The configured provider remains the safest route for this batch."
        tone = "success" if current.ready else "warning"

        if scoped_jobs <= 0:
            reason = "Add or select jobs before comparing the current provider with the offline route."
            tone = "neutral"
        elif current.provider_id == "piper":
            if current.ready:
                reason = "Piper is already selected and its configured offline voice is ready."
                tone = "success"
            else:
                reason = "Piper needs setup. Choose or repair an offline voice before preflight."
                tone = "error"
        elif current.blocked:
            if piper.ready:
                recommended = piper
                reason = self._blocked_fallback_reason(current)
                tone = "warning"
            else:
                reason = (
                    f"{current.provider_name} is not ready and Piper is not ready either. "
                    "Review provider setup before preflight."
                )
                tone = "error"
        elif preference == "privacy" and piper.ready:
            recommended = piper
            reason = "Privacy-first routing prefers the configured offline Piper voice."
            tone = "warning"
        elif preference == "lowest_cost" and piper.ready:
            if current.estimated_cost is None:
                reason = (
                    "Cloud pricing is not confirmed, so the current provider is kept instead of "
                    "switching on an unknown comparison."
                )
                tone = "neutral"
            elif current.estimated_cost > 0:
                recommended = piper
                reason = (
                    f"Piper has no provider fee for this local batch versus "
                    f"{current.cost_text} on the configured provider."
                )
                tone = "warning"
            else:
                reason = "The configured provider has no higher confirmed provider fee than Piper."
                tone = "success"
        elif preference == "cloud_first":
            if current.locality == "cloud":
                reason = "Cloud-first routing keeps the configured cloud provider while it remains ready."
                tone = "success"
            else:
                reason = "No configured cloud route is inferred automatically; keep the current local provider."
                tone = "neutral"
        elif preference == "balanced" and piper.ready and current.locality == "cloud":
            reason = (
                "Balanced routing keeps the ready cloud provider; Piper remains an explicit offline fallback."
            )
            tone = "success"

        switch_required = recommended.provider_id != current.provider_id
        action_enabled = bool(
            scoped_jobs > 0
            and switch_required
            and recommended.ready
            and not generation_active
        )
        if switch_required and recommended.provider_id == "piper":
            action_label = "Use Piper offline"
        elif current.blocked:
            action_label = "Review providers"
        else:
            action_label = "Current route is best"

        route_summary = (
            f"{current.provider_name} → {recommended.provider_name}"
            if switch_required
            else f"Stay on {current.provider_name}"
        )
        return SmartProviderRoutingState(
            preference=preference,
            current_provider_id=current.provider_id,
            current_provider_name=current.provider_name,
            recommended_provider_id=recommended.provider_id,
            recommended_provider_name=recommended.provider_name,
            route_summary=route_summary,
            recommendation=reason,
            tone=tone,
            switch_required=switch_required,
            action_label=action_label,
            action_enabled=action_enabled,
            current_candidate=current,
            piper_candidate=piper,
            scoped_jobs=scoped_jobs,
            scoped_characters=scoped_characters,
        )

    @classmethod
    def normalize_preference(cls, value: str) -> str:
        normalized = str(value or "balanced").strip().casefold().replace("-", "_")
        return normalized if normalized in ROUTING_PREFERENCES else "balanced"

    def _current_candidate(
        self,
        *,
        settings: AppSettings,
        scoped_characters: int,
        project_id: int | None,
        profile: ApiProfile | None,
        connection_status: str,
    ) -> ProviderRouteCandidate:
        provider_id = str(settings.provider or "mock").strip().casefold()
        readiness = self.readiness_service.readiness_for(provider_id, settings)
        locality = "local" if provider_id in self.LOCAL_PROVIDERS else "cloud"
        ready = not readiness.blocks_generation
        detail = readiness.reason or readiness.state
        lowered = str(connection_status or "").casefold()
        if locality == "cloud" and any(
            token in lowered for token in ("invalid", "error", "failed", "unavailable", "missing")
        ):
            ready = False
            detail = str(connection_status).strip() or detail

        remaining = profile.remaining_characters if profile is not None else None
        shortfall = max(0, scoped_characters - remaining) if remaining is not None else 0
        if shortfall:
            ready = False
            detail = f"Confirmed quota is short by {shortfall:,} characters."

        estimate, currency, source = self._cost(
            project_id=project_id,
            provider=provider_id,
            model=settings.model_id,
            characters=scoped_characters,
            local=locality == "local",
        )
        return ProviderRouteCandidate(
            provider_id=provider_id,
            provider_name=readiness.display_name or provider_id,
            locality=locality,
            ready=ready,
            status=readiness.state,
            detail=detail,
            quota_remaining=remaining,
            quota_shortfall=shortfall,
            estimated_cost=estimate,
            currency=currency,
            cost_source=source,
        )

    def _piper_candidate(
        self,
        *,
        settings: AppSettings,
        scoped_characters: int,
    ) -> ProviderRouteCandidate:
        piper_settings = settings.model_copy(
            update={
                "provider": "piper",
                "model_id": "piper-local",
                "voice_id": Path(settings.piper_model_path).stem if settings.piper_model_path else "",
            }
        )
        try:
            snapshot = self.offline_tts_engine_service.snapshot("piper", piper_settings)
            selected = next((voice for voice in snapshot.voices if voice.selected), None)
            detail = snapshot.summary
            return ProviderRouteCandidate(
                provider_id="piper",
                provider_name="Piper",
                locality="local",
                ready=bool(snapshot.ready),
                status=snapshot.state,
                detail=detail,
                estimated_cost=0.0,
                currency=None,
                cost_source="local-provider-fee",
                selected_voice_id=(selected.voice_id if selected else snapshot.selected_voice_id),
                selected_model_path=(selected.model_path if selected else settings.piper_model_path),
            )
        except Exception as exc:
            return ProviderRouteCandidate(
                provider_id="piper",
                provider_name="Piper",
                locality="local",
                ready=False,
                status="Unavailable",
                detail=str(exc) or "Piper inventory is unavailable.",
                estimated_cost=0.0,
                currency=None,
                cost_source="local-provider-fee",
            )

    def _cost(
        self,
        *,
        project_id: int | None,
        provider: str,
        model: str,
        characters: int,
        local: bool,
    ) -> tuple[float | None, str | None, str | None]:
        if local:
            return 0.0, None, "local-provider-fee"
        if self.cost_capacity_service is None:
            return None, None, None
        try:
            estimate, rate, currency, source = self.cost_capacity_service.estimate_cost(
                project_id=project_id,
                provider=provider,
                model=model,
                characters=characters,
            )
        except Exception:
            return None, None, None
        if rate <= 0 and estimate <= 0 and source == "policy-default":
            return None, currency, source
        return max(0.0, float(estimate)), str(currency), str(source)

    @staticmethod
    def _blocked_fallback_reason(current: ProviderRouteCandidate) -> str:
        if current.quota_shortfall:
            return (
                f"{current.provider_name} is short by {current.quota_shortfall:,} confirmed quota characters. "
                "Use the configured Piper voice for this batch, then run preflight again."
            )
        return (
            f"{current.provider_name} is not ready ({current.detail}). "
            "Use the configured Piper voice as an explicit offline fallback, then run preflight again."
        )
