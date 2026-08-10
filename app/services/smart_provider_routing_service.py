from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.models.api_profile import ApiProfile
from app.models.domain import AppSettings
from app.models.smart_provider_routing import (
    ROUTING_PREFERENCES,
    ProviderRouteCandidate,
    SmartProviderRoutingState,
)
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from app.services.offline_tts_engine_service import OfflineTTSEngineService
from app.services.provider_readiness_service import ProviderReadinessService


class SmartProviderRoutingService:
    """Deterministic, cached/configured-only provider recommendation engine.

    Phase 108 ranks all registered provider routes when the Phase 107 intelligence
    and Phase 106 unified catalog services are available. It does not initiate
    network refreshes, never changes settings, and never executes cross-provider
    failover. The Phase 98 current-vs-Piper behavior remains available for older
    callers.
    """

    SWITCH_SCORE_DELTA = 15

    def __init__(
        self,
        readiness_service: ProviderReadinessService,
        offline_tts_engine_service: OfflineTTSEngineService,
        cost_capacity_service=None,
        registry: ProviderRegistry | None = None,
        *,
        provider_cost_quota_limits_service=None,
        unified_catalog_service=None,
        api_profile_service=None,
    ) -> None:
        self.readiness_service = readiness_service
        self.offline_tts_engine_service = offline_tts_engine_service
        self.cost_capacity_service = cost_capacity_service
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY
        self.provider_cost_quota_limits_service = provider_cost_quota_limits_service
        self.unified_catalog_service = unified_catalog_service
        self.api_profile_service = api_profile_service

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
        largest_job_characters: int = 0,
        largest_job_bytes: int = 0,
    ) -> SmartProviderRoutingState:
        if self.provider_cost_quota_limits_service is None or self.unified_catalog_service is None:
            return self._analyze_legacy(
                settings=settings,
                scoped_jobs=scoped_jobs,
                scoped_characters=scoped_characters,
                project_id=project_id,
                current_profile=current_profile,
                connection_status=connection_status,
                preference=preference,
                generation_active=generation_active,
            )

        preference = self.normalize_preference(preference)
        scoped_jobs = max(0, int(scoped_jobs))
        scoped_characters = max(0, int(scoped_characters))
        largest_job_characters = max(0, int(largest_job_characters))
        largest_job_bytes = max(0, int(largest_job_bytes))
        current_provider = str(settings.provider or "mock").strip().casefold()
        provider_ids = list(self.registry.provider_ids())
        if current_provider not in provider_ids:
            provider_ids.append(current_provider)

        candidates = [
            self._v2_candidate(
                provider_id,
                settings=settings,
                scoped_characters=scoped_characters,
                project_id=project_id,
                current_provider=current_provider,
                current_profile=current_profile,
                connection_status=connection_status,
                largest_job_characters=largest_job_characters,
                largest_job_bytes=largest_job_bytes,
                preference=preference,
            )
            for provider_id in provider_ids
        ]
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.ready and item.eligible,
                item.score,
                item.provider_id == current_provider,
            ),
            reverse=True,
        )
        ranked = [replace(candidate, rank=index + 1) for index, candidate in enumerate(ranked)]
        by_id = {candidate.provider_id: candidate for candidate in ranked}
        current = by_id[current_provider]
        piper = by_id.get("piper") or self._piper_candidate(settings=settings, scoped_characters=scoped_characters)

        recommended = self._choose_v2_recommendation(
            current=current,
            ranked=tuple(ranked),
            preference=preference,
            scoped_jobs=scoped_jobs,
        )
        switch_required = recommended.provider_id != current.provider_id
        confidence = self._confidence(recommended)
        factors = self._decision_factors(current, recommended, preference)

        if scoped_jobs <= 0:
            recommendation = "Add or select jobs before comparing provider routes."
            tone = "neutral"
        elif switch_required:
            recommendation = self._switch_reason(current, recommended, preference, confidence)
            tone = "warning"
        elif current.blocked:
            recommendation = (
                f"{current.provider_name} is blocked and no evidence-backed alternative is ready. "
                "Review provider setup before preflight."
            )
            tone = "error"
        else:
            recommendation = self._stay_reason(current, ranked, preference)
            tone = "success" if current.ready else "warning"

        action_enabled = bool(scoped_jobs > 0 and switch_required and recommended.ready and not generation_active)
        if switch_required and recommended.provider_id == "piper":
            action_label = "Use Piper offline"
        elif switch_required:
            action_label = f"Review {recommended.provider_name}"
        elif current.blocked:
            action_label = "Review providers"
        else:
            action_label = "Current route is best"

        return SmartProviderRoutingState(
            preference=preference,
            current_provider_id=current.provider_id,
            current_provider_name=current.provider_name,
            recommended_provider_id=recommended.provider_id,
            recommended_provider_name=recommended.provider_name,
            route_summary=(
                f"{current.provider_name} → {recommended.provider_name}"
                if switch_required
                else f"Stay on {current.provider_name}"
            ),
            recommendation=recommendation,
            tone=tone,
            switch_required=switch_required,
            action_label=action_label,
            action_enabled=action_enabled,
            current_candidate=current,
            piper_candidate=piper,
            scoped_jobs=scoped_jobs,
            scoped_characters=scoped_characters,
            candidates=tuple(ranked),
            confidence=confidence,
            decision_factors=factors,
        )

    @classmethod
    def normalize_preference(cls, value: str) -> str:
        normalized = str(value or "balanced").strip().casefold().replace("-", "_")
        return normalized if normalized in ROUTING_PREFERENCES else "balanced"

    def _v2_candidate(
        self,
        provider_id: str,
        *,
        settings: AppSettings,
        scoped_characters: int,
        project_id: int | None,
        current_provider: str,
        current_profile: ApiProfile | None,
        connection_status: str,
        largest_job_characters: int,
        largest_job_bytes: int,
        preference: str,
    ) -> ProviderRouteCandidate:
        if provider_id == "piper":
            candidate = self._piper_candidate(settings=settings, scoped_characters=scoped_characters)
            enriched = replace(
                candidate,
                language_state="confirmed" if candidate.ready else "unknown",
                voice_state="confirmed" if candidate.selected_voice_id else "review",
                model_state="confirmed" if candidate.selected_model_path else "review",
                account_state="not_applicable",
                request_limit_state="not_applicable",
            )
            return replace(
                enriched,
                score=self._score(enriched, preference, is_current=provider_id == current_provider),
            )

        manifest = self.registry.manifest_for(provider_id)
        try:
            provider_settings, profile_name = self.unified_catalog_service.settings_for_provider(provider_id, settings)
        except Exception:
            provider_settings, profile_name = settings.model_copy(update={"provider": provider_id}), None
        readiness = self.readiness_service.readiness_for(provider_id, provider_settings)
        blockers: list[str] = []
        warnings: list[str] = []
        ready = not readiness.blocks_generation
        detail = readiness.reason or readiness.state

        if provider_id == "mock" and provider_id != current_provider:
            blockers.append("Mock is a test provider and is never recommended as a production route.")
        if readiness.blocks_generation:
            blockers.append(detail)

        if provider_id == current_provider and manifest.locality == "cloud":
            lowered = str(connection_status or "").casefold()
            if any(token in lowered for token in ("invalid", "error", "failed", "unavailable", "missing")):
                blockers.append(str(connection_status).strip() or "Current provider connection is not ready.")

        profile = (
            current_profile
            if provider_id == current_provider and current_profile is not None
            else self._profile_for(provider_id, provider_settings.active_api_profile_id)
        )
        account_state = "not_applicable" if not manifest.requires_credential else "unknown"
        if manifest.requires_credential:
            if profile is not None:
                account_state = str(profile.status)
                if not profile.is_usable:
                    blockers.append(f"Account {profile.display_name} is not usable ({profile.status}).")
                elif str(profile.status) != "ready":
                    warnings.append(f"Account {profile.display_name} has not been confirmed ready.")
            elif str(provider_settings.api_key or "").strip():
                account_state = "direct_key"
            elif manifest.profile_secret_required:
                blockers.append("No usable provider credential/account is selected.")
            else:
                account_state = "external_credentials"

        try:
            intelligence = self.provider_cost_quota_limits_service.provider_row(
                provider_id,
                settings,
                project_id=project_id,
                scoped_characters=scoped_characters,
            )
        except Exception:
            intelligence = None

        quota_remaining = None
        quota_shortfall = 0
        estimated_cost = None
        currency = None
        cost_source = None
        request_limit_state = "unknown"
        if intelligence is not None:
            quota_remaining = intelligence.quota.remaining
            quota_shortfall = intelligence.quota.shortfall
            estimated_cost = intelligence.cost.estimated_cost
            currency = intelligence.cost.currency
            cost_source = intelligence.cost.source
            if quota_shortfall:
                blockers.append(f"Confirmed quota is short by {quota_shortfall:,} characters.")
            elif intelligence.quota.state == "warning":
                warnings.append(intelligence.quota.message)
            elif intelligence.quota.state == "unknown" and manifest.locality == "cloud":
                warnings.append("Quota is unknown; no capacity is inferred.")

            request = intelligence.request_limit
            if request.known:
                metric = largest_job_bytes if request.unit == "bytes" else largest_job_characters
                if metric and request.value is not None and metric > request.value:
                    blockers.append(
                        f"Largest job exceeds the provider request limit ({metric:,} > {request.value:,} {request.unit})."
                    )
                    request_limit_state = "blocked"
                else:
                    request_limit_state = "confirmed"
            elif request.state == "not_applicable":
                request_limit_state = "not_applicable"
            else:
                warnings.append("Request-size limit is unknown for this route.")

        language_state, voice_state, model_state, recommended_voice, recommended_model = self._catalog_evidence(
            provider_id,
            settings=settings,
            provider_settings=provider_settings,
            readiness_detail=detail,
            current_provider=current_provider,
        )
        if language_state == "blocked":
            blockers.append(f"{readiness.display_name} is not certified for {settings.language_code or 'the requested language'}.")
        elif language_state == "unknown" and provider_id != current_provider:
            warnings.append("Language compatibility is not confirmed in cached/catalog evidence.")
        if voice_state == "review" and manifest.controls.voice_required and provider_id != current_provider:
            warnings.append("A compatible voice still needs explicit review/selection.")
        if model_state == "review" and provider_id != current_provider:
            warnings.append("A compatible TTS model still needs explicit review/selection.")

        eligible = not blockers
        ready = bool(ready and eligible)
        candidate = ProviderRouteCandidate(
            provider_id=provider_id,
            provider_name=readiness.display_name or manifest.display_name,
            locality=manifest.locality,
            ready=ready,
            status=readiness.state if ready else "Blocked",
            detail=detail,
            quota_remaining=quota_remaining,
            quota_shortfall=quota_shortfall,
            estimated_cost=estimated_cost,
            currency=currency,
            cost_source=cost_source,
            selected_voice_id=str(provider_settings.voice_id or "") or None,
            score=0,
            eligible=eligible,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
            language_state=language_state,
            voice_state=voice_state,
            model_state=model_state,
            account_state=account_state,
            request_limit_state=request_limit_state,
            profile_id=(profile.profile_id if profile else provider_settings.active_api_profile_id),
            profile_name=(profile.display_name if profile else profile_name),
            recommended_model_id=recommended_model,
            recommended_voice_id=recommended_voice,
        )
        return replace(
            candidate,
            score=self._score(candidate, preference, is_current=provider_id == current_provider),
        )

    def _catalog_evidence(
        self,
        provider_id: str,
        *,
        settings: AppSettings,
        provider_settings: AppSettings,
        readiness_detail: str,
        current_provider: str,
    ) -> tuple[str, str, str, str | None, str | None]:
        desired = self._base_language(settings.language_code)
        lowered_detail = str(readiness_detail or "").casefold()
        language_state = "unknown"
        if desired and any(token in lowered_detail for token in ("not certified", "not supported", "unsupported language")):
            language_state = "blocked"

        try:
            snapshot = self.unified_catalog_service.snapshot(
                settings,
                provider_ids=(provider_id,),
                allow_stale=True,
            )
            items = snapshot.items
        except Exception:
            items = ()

        voices = tuple(item for item in items if item.kind == "voice")
        models = tuple(item for item in items if item.kind == "model" and item.can_do_text_to_speech)
        matching_voices = tuple(
            item
            for item in voices
            if not desired or not item.languages or any(self._base_language(value) == desired for value in item.languages)
        )
        matching_models = tuple(
            item
            for item in models
            if not desired or not item.languages or any(self._base_language(value) == desired for value in item.languages)
        )

        if language_state != "blocked":
            if desired and any(
                any(self._base_language(value) == desired for value in item.languages)
                for item in (*voices, *models)
            ):
                language_state = "confirmed"
            elif provider_id == current_provider and str(provider_settings.language_code or ""):
                language_state = "configured"

        if provider_id == current_provider and provider_settings.voice_id:
            voice_state = "configured"
            recommended_voice = str(provider_settings.voice_id)
        elif matching_voices:
            voice_state = "confirmed"
            recommended_voice = matching_voices[0].item_id
        else:
            voice_state = "review"
            recommended_voice = None

        if provider_id == current_provider and provider_settings.model_id:
            model_state = "configured"
            recommended_model = str(provider_settings.model_id)
        elif matching_models:
            model_state = "confirmed"
            recommended_model = matching_models[0].item_id
        else:
            try:
                builtins = self.unified_catalog_service.models_for_provider(provider_id, settings)
            except Exception:
                builtins = ()
            if builtins:
                model_state = "confirmed"
                recommended_model = builtins[0].model_id
            else:
                model_state = "review"
                recommended_model = None

        return language_state, voice_state, model_state, recommended_voice, recommended_model

    def _profile_for(self, provider_id: str, profile_id: str | None) -> ApiProfile | None:
        service = self.api_profile_service
        if service is None:
            service = getattr(self.unified_catalog_service, "profiles", None)
        if service is None:
            return None
        if profile_id:
            try:
                profile = service.get_profile(profile_id)
                if profile.provider == provider_id:
                    return profile
            except (ValueError, AttributeError):
                pass
        try:
            return service.active_profile(provider_id)
        except (ValueError, AttributeError):
            return None

    def _score(self, candidate: ProviderRouteCandidate, preference: str, *, is_current: bool) -> int:
        if candidate.blocked:
            return 0
        score = 50
        if candidate.ready:
            score += 10
        if candidate.language_state in {"confirmed", "configured"}:
            score += 12
        if candidate.account_state in {"ready", "direct_key", "external_credentials", "not_applicable"}:
            score += 6
        if candidate.voice_state in {"confirmed", "configured"}:
            score += 4
        if candidate.model_state in {"confirmed", "configured"}:
            score += 4
        if candidate.request_limit_state in {"confirmed", "not_applicable"}:
            score += 4
        if candidate.quota_remaining is not None or candidate.locality == "local":
            score += 4
        if is_current:
            score += 8

        if preference == "privacy":
            score += 24 if candidate.locality == "local" else -4
        elif preference == "cloud_first":
            score += 14 if candidate.locality == "cloud" else -8
        elif preference == "lowest_cost":
            if candidate.estimated_cost is None:
                score -= 4
            elif candidate.estimated_cost <= 0:
                score += 20
            else:
                score += max(0, 12 - min(12, int(candidate.estimated_cost * 20)))
        elif preference == "reliability":
            score += 6 if not candidate.warnings else 0
            score -= min(10, len(candidate.warnings) * 2)
        else:
            score += 2 if candidate.locality == "local" else 0
        return max(0, min(100, score))

    def _choose_v2_recommendation(
        self,
        *,
        current: ProviderRouteCandidate,
        ranked: tuple[ProviderRouteCandidate, ...],
        preference: str,
        scoped_jobs: int,
    ) -> ProviderRouteCandidate:
        if scoped_jobs <= 0:
            return current
        eligible = tuple(candidate for candidate in ranked if candidate.ready and candidate.eligible)
        if not eligible:
            return current
        best = eligible[0]
        if current.blocked:
            return best
        if preference == "lowest_cost" and current.estimated_cost is None:
            return current
        if preference == "cloud_first" and current.locality == "cloud" and current.ready:
            return current
        if best.provider_id == current.provider_id:
            return current
        if (
            preference == "privacy"
            and current.locality == "cloud"
            and best.locality == "local"
            and best.language_state in {"confirmed", "configured"}
        ):
            return best
        if best.score < current.score + self.SWITCH_SCORE_DELTA:
            return current
        if best.language_state not in {"confirmed", "configured"}:
            return current
        if best.provider_id != "piper" and (
            best.voice_state == "review" or best.model_state == "review"
        ):
            return current
        return best

    @staticmethod
    def _confidence(candidate: ProviderRouteCandidate) -> str:
        if candidate.blocked:
            return "low"
        confirmed = sum(
            state in {"confirmed", "configured", "not_applicable"}
            for state in (
                candidate.language_state,
                candidate.voice_state,
                candidate.model_state,
                candidate.request_limit_state,
            )
        )
        if confirmed >= 4 and not candidate.warnings:
            return "high"
        if confirmed >= 2:
            return "medium"
        return "low"

    @staticmethod
    def _decision_factors(
        current: ProviderRouteCandidate,
        recommended: ProviderRouteCandidate,
        preference: str,
    ) -> tuple[str, ...]:
        factors = [f"preference={preference}", f"current_score={current.score}"]
        factors.append(f"recommended_score={recommended.score}")
        factors.append(f"language={recommended.language_state}")
        factors.append(f"account={recommended.account_state}")
        if recommended.estimated_cost is not None:
            factors.append(f"cost={recommended.cost_text}")
        if recommended.quota_remaining is not None:
            factors.append(f"quota={recommended.quota_remaining}")
        return tuple(factors)

    @staticmethod
    def _switch_reason(
        current: ProviderRouteCandidate,
        recommended: ProviderRouteCandidate,
        preference: str,
        confidence: str,
    ) -> str:
        if current.blocked:
            reason = f"{current.provider_name} is blocked; {recommended.provider_name} is the strongest ready route."
        elif preference == "privacy" and recommended.locality == "local":
            reason = f"Privacy-first routing prefers the ready local route {recommended.provider_name}."
        elif preference == "lowest_cost":
            reason = f"Lowest-cost routing prefers {recommended.provider_name} using confirmed/configured cost evidence."
        else:
            reason = f"{recommended.provider_name} has materially stronger cached/configured routing evidence."
        return f"{reason} Confidence: {confidence}. The recommendation is not applied automatically."

    @staticmethod
    def _stay_reason(
        current: ProviderRouteCandidate,
        ranked: list[ProviderRouteCandidate],
        preference: str,
    ) -> str:
        best_other = next((item for item in ranked if item.provider_id != current.provider_id), None)
        if preference == "lowest_cost" and current.estimated_cost is None:
            return "Current provider is kept because its pricing is unknown; Smart Routing never switches on an unknown cost comparison."
        if best_other and best_other.score > current.score:
            return (
                f"{best_other.provider_name} scores higher, but the evidence/score advantage is not sufficient for a switch recommendation. "
                "Keep the current provider until the user reviews the alternative."
            )
        return "The configured provider remains the strongest evidence-backed route for this batch."

    @staticmethod
    def _base_language(value: str | None) -> str:
        return str(value or "").strip().replace("_", "-").split("-", 1)[0].casefold()

    # -----------------------------------------------------------------
    # Phase 98 compatibility path (current provider versus Piper only).
    # -----------------------------------------------------------------
    def _analyze_legacy(
        self,
        *,
        settings: AppSettings,
        scoped_jobs: int,
        scoped_characters: int,
        project_id: int | None,
        current_profile: ApiProfile | None,
        connection_status: str,
        preference: str,
        generation_active: bool,
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
        piper = self._piper_candidate(settings=settings, scoped_characters=scoped_characters)
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
        elif preference in {"balanced", "reliability"} and piper.ready and current.locality == "cloud":
            reason = "Balanced routing keeps the ready cloud provider; Piper remains an explicit offline fallback."
            tone = "success"

        switch_required = recommended.provider_id != current.provider_id
        action_enabled = bool(scoped_jobs > 0 and switch_required and recommended.ready and not generation_active)
        if switch_required and recommended.provider_id == "piper":
            action_label = "Use Piper offline"
        elif current.blocked:
            action_label = "Review providers"
        else:
            action_label = "Current route is best"
        return SmartProviderRoutingState(
            preference=preference,
            current_provider_id=current.provider_id,
            current_provider_name=current.provider_name,
            recommended_provider_id=recommended.provider_id,
            recommended_provider_name=recommended.provider_name,
            route_summary=(f"{current.provider_name} → {recommended.provider_name}" if switch_required else f"Stay on {current.provider_name}"),
            recommendation=reason,
            tone=tone,
            switch_required=switch_required,
            action_label=action_label,
            action_enabled=action_enabled,
            current_candidate=current,
            piper_candidate=piper,
            scoped_jobs=scoped_jobs,
            scoped_characters=scoped_characters,
            candidates=(current, piper),
            confidence="medium",
        )

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
        locality = self.registry.manifest_for(provider_id).locality
        ready = not readiness.blocks_generation
        detail = readiness.reason or readiness.state
        lowered = str(connection_status or "").casefold()
        if locality == "cloud" and any(token in lowered for token in ("invalid", "error", "failed", "unavailable", "missing")):
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

    def _piper_candidate(self, *, settings: AppSettings, scoped_characters: int) -> ProviderRouteCandidate:
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
            return ProviderRouteCandidate(
                provider_id="piper",
                provider_name="Piper",
                locality="local",
                ready=bool(snapshot.ready),
                status=snapshot.state,
                detail=snapshot.summary,
                estimated_cost=0.0,
                currency=None,
                cost_source="local-provider-fee",
                selected_voice_id=(selected.voice_id if selected else snapshot.selected_voice_id),
                selected_model_path=(selected.model_path if selected else settings.piper_model_path),
                eligible=bool(snapshot.ready),
                blockers=() if snapshot.ready else (snapshot.summary,),
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
                eligible=False,
                blockers=(str(exc) or "Piper inventory is unavailable.",),
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
