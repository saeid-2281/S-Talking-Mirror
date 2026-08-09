from __future__ import annotations

from app.models.api_profile import ApiProfile
from app.models.domain import AppSettings
from app.models.provider_intelligence import (
    ProviderIntelligenceState,
    ProviderSelectionSuggestion,
)
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_readiness_service import ProviderReadinessService
from app.services.voice_service import VoiceCatalog, VoiceItem, VoiceModelItem, VoiceService


class ProviderIntelligenceService:
    """Build a read-only provider/model/voice decision snapshot.

    The service never changes provider settings and never performs a live provider
    call.  It uses readiness metadata, the current cached voice catalog, confirmed
    quota snapshots and the existing cost policy to explain the next useful choice.
    """

    LOCAL_DEFAULT_VOICE_PROVIDERS = {"mock", "piper", "kokoro"}

    def __init__(
        self,
        readiness_service: ProviderReadinessService,
        catalog_service: ProviderCatalogService,
        voice_service: VoiceService,
        cost_capacity_service=None,
    ) -> None:
        self.readiness_service = readiness_service
        self.catalog_service = catalog_service
        self.voice_service = voice_service
        self.cost_capacity_service = cost_capacity_service

    def analyze(
        self,
        *,
        settings: AppSettings,
        scoped_jobs: int,
        scoped_characters: int,
        project_id: int | None,
        profile: ApiProfile | None = None,
        connection_status: str = "",
    ) -> ProviderIntelligenceState:
        provider_id = str(settings.provider or "mock").strip().casefold()
        scoped_jobs = max(0, int(scoped_jobs))
        scoped_characters = max(0, int(scoped_characters))

        readiness = self.readiness_service.readiness_for(provider_id, settings)
        capabilities = self.catalog_service.capabilities_for(provider_id, settings)
        catalog = self.voice_service.cached_catalog(settings)
        provider_name = readiness.display_name or capabilities.display_name or provider_id

        status, tone = self._readiness_status(
            readiness.state,
            readiness.reason,
            connection_status,
        )
        selection_summary = self._selection_summary(settings, catalog)
        (
            compatibility_text,
            compatibility_tone,
            suggestion,
            selection_problem,
        ) = self._selection_analysis(settings, capabilities.supports_voice_listing, catalog)

        remaining, limit = self._quota(profile, catalog)
        quota_text, quota_tone, quota_shortfall = self._quota_text(
            remaining=remaining,
            limit=limit,
            scoped_characters=scoped_characters,
            quota_supported=capabilities.supports_quota_lookup,
        )
        batch_text = f"{scoped_jobs:,} jobs · {scoped_characters:,} characters"
        cost_text = self._cost_text(
            project_id=project_id,
            provider=provider_id,
            model=suggestion.model_id or settings.model_id,
            characters=scoped_characters,
        )

        action_code, action_label, recommendation = self._recommendation(
            readiness_blocks=readiness.blocks_generation,
            readiness_reason=readiness.reason,
            supports_catalog_refresh=(
                capabilities.remote
                and (
                    capabilities.supports_voice_listing
                    or capabilities.supports_model_listing
                )
            ),
            catalog=catalog,
            selection_problem=selection_problem,
            suggestion=suggestion,
            quota_shortfall=quota_shortfall,
            scoped_jobs=scoped_jobs,
        )

        if tone != "error" and quota_tone == "error":
            tone = "error"
            status = "Quota blocked"
        elif tone == "success" and compatibility_tone == "warning":
            tone = "warning"
            status = "Selection review"

        return ProviderIntelligenceState(
            provider_id=provider_id,
            provider_name=provider_name,
            status=status,
            tone=tone,
            selection_summary=selection_summary,
            compatibility_text=compatibility_text,
            compatibility_tone=compatibility_tone,
            quota_text=quota_text,
            quota_tone=quota_tone,
            batch_text=batch_text,
            cost_text=cost_text,
            recommendation=recommendation,
            primary_action_code=action_code,
            primary_action_label=action_label,
            suggestion=suggestion,
            catalog_available=catalog is not None,
            scoped_jobs=scoped_jobs,
            scoped_characters=scoped_characters,
        )

    @staticmethod
    def _readiness_status(
        readiness_state: str,
        readiness_reason: str,
        connection_status: str,
    ) -> tuple[str, str]:
        connection = str(connection_status or "").strip()
        lowered = connection.casefold()
        if connection and any(token in lowered for token in ("invalid", "error", "failed", "missing")):
            return "Connection issue", "error"
        if connection and ("connected" in lowered or "ready" in lowered):
            return "Connected", "success"

        state = str(readiness_state or "Review").strip()
        if state in {"Ready", "Ready but unverified live", "Connected"}:
            return state, "success" if state == "Ready" else "warning"
        if state in {"Setup required", "Dependency missing", "Partial implementation", "Not production-ready"}:
            return state, "error"
        if readiness_reason:
            return state or "Review", "warning"
        return "Review", "neutral"

    @staticmethod
    def _selection_summary(settings: AppSettings, catalog: VoiceCatalog | None) -> str:
        model_name = settings.model_id or "No model"
        voice_name = settings.voice_id or "No voice"
        if catalog is not None:
            model = next((item for item in catalog.models if item.model_id == settings.model_id), None)
            voice = next((item for item in catalog.voices if item.voice_id == settings.voice_id), None)
            if model is not None:
                model_name = model.name
            if voice is not None:
                voice_name = voice.name
        return f"{model_name} · {voice_name}"

    def _selection_analysis(
        self,
        settings: AppSettings,
        supports_voice_listing: bool,
        catalog: VoiceCatalog | None,
    ) -> tuple[str, str, ProviderSelectionSuggestion, bool]:
        voice_required = (
            supports_voice_listing
            and settings.provider not in self.LOCAL_DEFAULT_VOICE_PROVIDERS
        )
        if catalog is None:
            if voice_required and not settings.voice_id:
                return (
                    "Voice required · catalog not loaded",
                    "warning",
                    ProviderSelectionSuggestion(),
                    True,
                )
            return (
                "Compatibility not checked · refresh catalog",
                "neutral",
                ProviderSelectionSuggestion(),
                False,
            )

        models = [item for item in catalog.models if item.can_do_text_to_speech]
        current_model = next(
            (item for item in models if item.model_id == settings.model_id),
            None,
        )
        model_ok = self._model_supports_language(current_model, settings.language_code)
        recommended_model = current_model if model_ok else self._recommended_model(
            models,
            settings.language_code,
        )
        recommended_model_id = recommended_model.model_id if recommended_model else None

        current_voice = next(
            (item for item in catalog.voices if item.voice_id == settings.voice_id),
            None,
        )
        voice_ok = not voice_required
        if voice_required:
            voice_ok = self._voice_compatible(
                current_voice,
                settings.model_id,
                settings.language_code,
            )
        recommended_voice = current_voice if voice_ok else self._recommended_voice(
            list(catalog.voices),
            recommended_model_id or settings.model_id,
            settings.language_code,
        )

        suggestion = ProviderSelectionSuggestion(
            model_id=(
                recommended_model.model_id
                if recommended_model is not None and recommended_model.model_id != settings.model_id
                else None
            ),
            model_name=(
                recommended_model.name
                if recommended_model is not None and recommended_model.model_id != settings.model_id
                else None
            ),
            voice_id=(
                recommended_voice.voice_id
                if recommended_voice is not None and recommended_voice.voice_id != settings.voice_id
                else None
            ),
            voice_name=(
                recommended_voice.name
                if recommended_voice is not None and recommended_voice.voice_id != settings.voice_id
                else None
            ),
        )

        problems: list[str] = []
        if not model_ok:
            problems.append("model/language mismatch")
        if not voice_ok:
            problems.append("voice/model mismatch" if settings.voice_id else "voice missing")

        if problems:
            suffix = f" · suggested {suggestion.summary}" if suggestion.has_changes else ""
            return (
                f"Review {' + '.join(problems)}{suffix}",
                "warning",
                suggestion,
                True,
            )

        model_label = current_model.name if current_model else settings.model_id or "provider default"
        voice_label = current_voice.name if current_voice else settings.voice_id or "provider default"
        return (
            f"Compatible · {model_label} · {voice_label}",
            "success",
            ProviderSelectionSuggestion(),
            False,
        )

    @staticmethod
    def _model_supports_language(
        model: VoiceModelItem | None,
        language_code: str | None,
    ) -> bool:
        if model is None:
            return False
        if not language_code or not model.languages:
            return True
        return str(language_code) in model.languages

    def _recommended_model(
        self,
        models: list[VoiceModelItem],
        language_code: str | None,
    ) -> VoiceModelItem | None:
        if not models:
            return None
        language = str(language_code or "").strip()
        if language:
            exact = next((item for item in models if language in item.languages), None)
            if exact is not None:
                return exact
            generic = next((item for item in models if not item.languages), None)
            if generic is not None:
                return generic
        return models[0]

    @staticmethod
    def _voice_compatible(
        voice: VoiceItem | None,
        model_id: str,
        language_code: str | None,
    ) -> bool:
        if voice is None:
            return False
        if voice.compatible_model_ids and model_id not in voice.compatible_model_ids:
            return False
        if language_code and voice.language and voice.language != language_code:
            return False
        return True

    def _recommended_voice(
        self,
        voices: list[VoiceItem],
        model_id: str,
        language_code: str | None,
    ) -> VoiceItem | None:
        compatible = [
            item
            for item in voices
            if (not item.compatible_model_ids or model_id in item.compatible_model_ids)
        ]
        if not compatible:
            return None
        language = str(language_code or "").strip()
        if language:
            language_matches = [item for item in compatible if item.language == language]
            if language_matches:
                compatible = language_matches
        compatible.sort(
            key=lambda item: (
                not item.is_favorite,
                item.name.casefold(),
                item.voice_id.casefold(),
            )
        )
        return compatible[0]

    @staticmethod
    def _quota(
        profile: ApiProfile | None,
        catalog: VoiceCatalog | None,
    ) -> tuple[int | None, int | None]:
        if profile is not None and profile.remaining_characters is not None:
            return profile.remaining_characters, profile.character_limit
        if catalog is not None and catalog.account is not None:
            return catalog.account.remaining_characters, catalog.account.character_limit
        return None, None

    @staticmethod
    def _quota_text(
        *,
        remaining: int | None,
        limit: int | None,
        scoped_characters: int,
        quota_supported: bool,
    ) -> tuple[str, str, int]:
        if remaining is None:
            return (
                "Not checked" if quota_supported else "Not reported by provider",
                "neutral",
                0,
            )

        shortfall = max(0, scoped_characters - remaining)
        if shortfall:
            return f"{remaining:,} remaining · short by {shortfall:,}", "error", shortfall

        usage = (scoped_characters / remaining * 100.0) if remaining > 0 else 0.0
        limit_text = f" / {limit:,}" if limit is not None else ""
        if scoped_characters and usage >= 90:
            return (
                f"{remaining:,}{limit_text} remaining · batch uses {usage:.0f}%",
                "warning",
                0,
            )
        return f"{remaining:,}{limit_text} remaining", "success", 0

    def _cost_text(
        self,
        *,
        project_id: int | None,
        provider: str,
        model: str,
        characters: int,
    ) -> str:
        if self.cost_capacity_service is None:
            return "Pricing unavailable"
        try:
            estimate, rate, currency, source = self.cost_capacity_service.estimate_cost(
                project_id=project_id,
                provider=provider,
                model=model,
                characters=characters,
            )
        except Exception:
            return "Pricing unavailable"
        if rate <= 0 and estimate <= 0:
            return "Pricing not configured"
        return f"{currency} {estimate:.4f} · {rate:.2f}/1M · {source}"

    @staticmethod
    def _recommendation(
        *,
        readiness_blocks: bool,
        readiness_reason: str,
        supports_catalog_refresh: bool,
        catalog: VoiceCatalog | None,
        selection_problem: bool,
        suggestion: ProviderSelectionSuggestion,
        quota_shortfall: int,
        scoped_jobs: int,
    ) -> tuple[str, str, str]:
        if readiness_blocks:
            return "provider", "Review provider", readiness_reason or "Provider setup blocks generation."
        if suggestion.has_changes:
            return (
                "apply-suggestion",
                "Apply suggestion",
                f"Use the compatible cached selection: {suggestion.summary}.",
            )
        if selection_problem:
            return "browse-voices", "Choose compatible voice", "Review the cached voice/model compatibility before preflight."
        if quota_shortfall:
            return (
                "quota-scope",
                "Use quota-sized scope",
                "The current scope exceeds confirmed provider quota. Use the existing quota-sized batch scope before preflight.",
            )
        if supports_catalog_refresh and catalog is None:
            return (
                "refresh-catalog",
                "Refresh catalog",
                "Refresh provider catalog data to validate model, voice and account quota before preflight.",
            )
        if scoped_jobs <= 0:
            return "queue", "Review queue", "Add or select jobs before provider intelligence can evaluate the batch."
        return (
            "preflight",
            "Run preflight",
            "Provider, model, voice and known quota are ready for the authoritative preflight checks.",
        )
