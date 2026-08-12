from __future__ import annotations

from datetime import datetime, timezone

from app.models import AppSettings
from app.models.unified_voice_model_catalog import (
    UnifiedCatalogItem,
    UnifiedCatalogSource,
    UnifiedVoiceModelCatalog,
)
from app.services.api_profile_service import ApiProfileService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.voice_service import VoiceCatalog, VoiceModelItem, VoiceService


class UnifiedVoiceModelCatalogService:
    """Compose account-scoped provider catalogs into one read-only selection surface.

    Catalog discovery never changes the active generation provider or profile and never
    performs implicit network work. A provider refresh is an explicit method call. The
    caller must also opt in to any cross-provider selection through ``allow_provider_change``.
    """

    def __init__(
        self,
        profiles: ApiProfileService,
        providers: ProviderCatalogService,
        voices: VoiceService,
    ) -> None:
        self.profiles = profiles
        self.providers = providers
        self.voices = voices

    def snapshot(
        self,
        base_settings: AppSettings,
        *,
        provider_ids: tuple[str, ...] | None = None,
        allow_stale: bool = True,
    ) -> UnifiedVoiceModelCatalog:
        ids = provider_ids or self.providers.provider_ids()
        sources: list[UnifiedCatalogSource] = []
        items: list[UnifiedCatalogItem] = []
        for provider_id in ids:
            source, provider_items = self._provider_snapshot(
                provider_id,
                base_settings,
                allow_stale=allow_stale,
            )
            sources.append(source)
            items.extend(provider_items)
        return UnifiedVoiceModelCatalog(
            sources=tuple(sources),
            items=tuple(items),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def snapshot_explicit_settings(
        self,
        provider_id: str,
        settings: AppSettings,
        *,
        allow_stale: bool = True,
    ) -> UnifiedVoiceModelCatalog:
        """Read one provider using exactly the account context in ``settings``.

        Unlike :meth:`snapshot`, this method never falls back to the provider's
        active profile when ``active_api_profile_id`` is empty. It exists for
        guided setup flows where account selection must stay an explicit user
        decision.
        """
        provider_id = str(provider_id or "").strip().casefold()
        if provider_id != str(settings.provider or "").strip().casefold():
            raise ValueError("Explicit catalog settings must match the requested provider.")
        manifest = self.providers.manifest_for(provider_id)
        profile_name = self._explicit_profile_name(provider_id, settings.active_api_profile_id)
        catalog = self.voices.available_catalog(settings, allow_stale=allow_stale)
        if catalog is not None:
            source = UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="cached",
                voice_count=len(catalog.voices),
                model_count=sum(1 for model in catalog.models if model.can_do_text_to_speech),
                refreshed_at=catalog.refreshed_at,
                message="Explicit account-scoped cached catalog.",
            )
            items = self._items_from_catalog(source, catalog)
        else:
            fallback_models = self._built_in_models(provider_id)
            if fallback_models:
                source = UnifiedCatalogSource(
                    provider_id=provider_id,
                    provider_name=manifest.display_name,
                    profile_id=settings.active_api_profile_id,
                    profile_name=profile_name,
                    state="built_in",
                    voice_count=0,
                    model_count=len(fallback_models),
                    message="Built-in model contract; explicit refresh is required for live voices/metadata.",
                )
                items = tuple(self._model_item(source, model) for model in fallback_models)
            elif self._account_required(manifest, settings):
                source = UnifiedCatalogSource(
                    provider_id=provider_id,
                    provider_name=manifest.display_name,
                    profile_id=settings.active_api_profile_id,
                    profile_name=profile_name,
                    state="account_required",
                    voice_count=0,
                    model_count=0,
                    message="Choose a provider account before explicitly refreshing this catalog.",
                )
                items = ()
            else:
                source = UnifiedCatalogSource(
                    provider_id=provider_id,
                    provider_name=manifest.display_name,
                    profile_id=settings.active_api_profile_id,
                    profile_name=profile_name,
                    state="not_refreshed",
                    voice_count=0,
                    model_count=0,
                    message="No explicit-account catalog snapshot is available yet.",
                )
                items = ()
        return UnifiedVoiceModelCatalog(
            sources=(source,),
            items=tuple(items),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def refresh_provider_explicit_settings(
        self,
        provider_id: str,
        settings: AppSettings,
    ) -> UnifiedCatalogSource:
        """Refresh one provider using exactly the explicitly selected account."""
        provider_id = str(provider_id or "").strip().casefold()
        if provider_id != str(settings.provider or "").strip().casefold():
            raise ValueError("Explicit catalog settings must match the requested provider.")
        manifest = self.providers.manifest_for(provider_id)
        profile_name = self._explicit_profile_name(provider_id, settings.active_api_profile_id)
        if self._account_required(manifest, settings):
            return UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="account_required",
                voice_count=0,
                model_count=0,
                message="Choose a credential-ready provider account before refreshing this catalog.",
            )
        try:
            catalog = self.voices.refresh_catalog(settings, force=True)
        except Exception as exc:
            return UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="error",
                voice_count=0,
                model_count=0,
                message=str(exc),
            )
        return UnifiedCatalogSource(
            provider_id=provider_id,
            provider_name=manifest.display_name,
            profile_id=settings.active_api_profile_id,
            profile_name=profile_name,
            state="refreshed",
            voice_count=len(catalog.voices),
            model_count=sum(1 for model in catalog.models if model.can_do_text_to_speech),
            refreshed_at=catalog.refreshed_at,
            message="Catalog refreshed for the explicitly selected account.",
        )

    def refresh_provider(
        self,
        provider_id: str,
        base_settings: AppSettings,
    ) -> UnifiedCatalogSource:
        settings, profile_name = self.settings_for_provider(provider_id, base_settings)
        manifest = self.providers.manifest_for(provider_id)
        if self._account_required(manifest, settings):
            return UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="account_required",
                voice_count=0,
                model_count=0,
                message="Configure or select a provider account before refreshing this catalog.",
            )
        try:
            catalog = self.voices.refresh_catalog(settings, force=True)
        except Exception as exc:
            return UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="error",
                voice_count=0,
                model_count=0,
                message=str(exc),
            )
        return UnifiedCatalogSource(
            provider_id=provider_id,
            provider_name=manifest.display_name,
            profile_id=settings.active_api_profile_id,
            profile_name=profile_name,
            state="refreshed",
            voice_count=len(catalog.voices),
            model_count=sum(1 for model in catalog.models if model.can_do_text_to_speech),
            refreshed_at=catalog.refreshed_at,
            message="Catalog refreshed explicitly.",
        )

    def filtered_items(
        self,
        catalog: UnifiedVoiceModelCatalog,
        *,
        query: str = "",
        provider_id: str | None = None,
        kind: str | None = None,
        language: str | None = None,
    ) -> tuple[UnifiedCatalogItem, ...]:
        needle = str(query or "").strip().casefold()
        normalized_language = self._base_language(language)
        result: list[UnifiedCatalogItem] = []
        for item in catalog.items:
            if provider_id and item.provider_id != provider_id:
                continue
            if kind in {"voice", "model"} and item.kind != kind:
                continue
            if normalized_language and not any(
                self._base_language(value) == normalized_language for value in item.languages
            ):
                continue
            if needle and needle not in item.search_text:
                continue
            result.append(item)
        return tuple(result)

    def languages(self, catalog: UnifiedVoiceModelCatalog) -> tuple[str, ...]:
        return tuple(
            sorted(
                {language for item in catalog.items for language in item.languages if language},
                key=str.casefold,
            )
        )

    def models_for_provider(
        self,
        provider_id: str,
        base_settings: AppSettings,
    ) -> tuple[VoiceModelItem, ...]:
        settings, _profile_name = self.settings_for_provider(provider_id, base_settings)
        catalog = self.voices.available_catalog(settings, allow_stale=True)
        if catalog is not None and catalog.models:
            return tuple(model for model in catalog.models if model.can_do_text_to_speech)
        return self._built_in_models(provider_id)

    def selection_settings(
        self,
        base_settings: AppSettings,
        item: UnifiedCatalogItem,
        *,
        allow_provider_change: bool = False,
        allow_profile_change: bool = False,
    ) -> AppSettings:
        if item.provider_id != base_settings.provider and not allow_provider_change:
            raise ValueError(
                "Cross-provider catalog selection requires explicit provider-change approval."
            )
        if (
            item.profile_id
            and item.profile_id != base_settings.active_api_profile_id
            and not allow_profile_change
        ):
            raise ValueError(
                "Catalog selection from another account requires explicit account-change approval."
            )
        settings, _profile_name = self.settings_for_provider(item.provider_id, base_settings)
        update: dict[str, object] = {"provider": item.provider_id}
        if item.kind == "voice":
            update["voice_id"] = item.item_id
        else:
            update["model_id"] = item.item_id
        return settings.model_copy(update=update)

    def settings_for_provider(
        self,
        provider_id: str,
        base_settings: AppSettings,
    ) -> tuple[AppSettings, str | None]:
        provider_id = str(provider_id or "").strip().casefold()
        if provider_id == base_settings.provider:
            settings = base_settings.model_copy(update={"provider": provider_id})
        else:
            settings = base_settings.model_copy(
                update={
                    "provider": provider_id,
                    "api_key": "",
                    "active_api_profile_id": None,
                    "provider_options": {},
                }
            )
        manifest = self.providers.manifest_for(provider_id)
        if not manifest.profile_management_ready:
            return settings, None
        if provider_id == base_settings.provider and base_settings.active_api_profile_id:
            try:
                current_profile = self.profiles.get_profile(base_settings.active_api_profile_id)
            except ValueError:
                current_profile = None
            if current_profile is not None and current_profile.provider == provider_id:
                return (
                    self.profiles.apply_profile(settings, current_profile.profile_id),
                    current_profile.display_name,
                )
        profile = self.profiles.active_profile(provider_id)
        if profile is None:
            return settings, None
        return self.profiles.apply_profile(settings, profile.profile_id), profile.display_name

    def _explicit_profile_name(self, provider_id: str, profile_id: str | None) -> str | None:
        profile_id = str(profile_id or "").strip()
        if not profile_id:
            return None
        try:
            profile = self.profiles.get_profile(profile_id)
        except ValueError:
            return None
        if profile.provider != provider_id:
            raise ValueError(
                f"Provider account {profile.display_name!r} belongs to {profile.provider}, not {provider_id}."
            )
        return profile.display_name

    def _provider_snapshot(
        self,
        provider_id: str,
        base_settings: AppSettings,
        *,
        allow_stale: bool,
    ) -> tuple[UnifiedCatalogSource, tuple[UnifiedCatalogItem, ...]]:
        manifest = self.providers.manifest_for(provider_id)
        settings, profile_name = self.settings_for_provider(provider_id, base_settings)
        catalog = self.voices.available_catalog(settings, allow_stale=allow_stale)
        if catalog is not None:
            source = UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="cached",
                voice_count=len(catalog.voices),
                model_count=sum(1 for model in catalog.models if model.can_do_text_to_speech),
                refreshed_at=catalog.refreshed_at,
                message="Account-scoped cached catalog.",
            )
            return source, self._items_from_catalog(source, catalog)

        fallback_models = self._built_in_models(provider_id)
        if fallback_models:
            source = UnifiedCatalogSource(
                provider_id=provider_id,
                provider_name=manifest.display_name,
                profile_id=settings.active_api_profile_id,
                profile_name=profile_name,
                state="built_in",
                voice_count=0,
                model_count=len(fallback_models),
                message="Built-in model contract; refresh the provider for live voices/metadata.",
            )
            return source, tuple(self._model_item(source, model) for model in fallback_models)

        if self._account_required(manifest, settings):
            state = "account_required"
            message = "Provider account required before catalog refresh."
        else:
            state = "not_refreshed"
            message = "No catalog snapshot is available yet."
        source = UnifiedCatalogSource(
            provider_id=provider_id,
            provider_name=manifest.display_name,
            profile_id=settings.active_api_profile_id,
            profile_name=profile_name,
            state=state,
            voice_count=0,
            model_count=0,
            message=message,
        )
        return source, ()

    def _items_from_catalog(
        self,
        source: UnifiedCatalogSource,
        catalog: VoiceCatalog,
    ) -> tuple[UnifiedCatalogItem, ...]:
        items: list[UnifiedCatalogItem] = []
        for voice in catalog.voices:
            languages = self._voice_languages(voice.language, voice.labels)
            items.append(
                UnifiedCatalogItem(
                    key=self._key(source, "voice", voice.voice_id),
                    kind="voice",
                    provider_id=source.provider_id,
                    provider_name=source.provider_name,
                    profile_id=source.profile_id,
                    profile_name=source.profile_name,
                    item_id=voice.voice_id,
                    name=voice.name,
                    languages=languages,
                    category=voice.category,
                    description=voice.description,
                    compatible_model_ids=voice.compatible_model_ids,
                    labels=tuple(sorted((str(k), str(v)) for k, v in voice.labels.items())),
                    is_favorite=voice.is_favorite,
                    source_state=source.state,
                )
            )
        for model in catalog.models:
            if model.can_do_text_to_speech:
                items.append(self._model_item(source, model))
        return tuple(items)

    def _model_item(
        self,
        source: UnifiedCatalogSource,
        model: VoiceModelItem,
    ) -> UnifiedCatalogItem:
        return UnifiedCatalogItem(
            key=self._key(source, "model", model.model_id),
            kind="model",
            provider_id=source.provider_id,
            provider_name=source.provider_name,
            profile_id=source.profile_id,
            profile_name=source.profile_name,
            item_id=model.model_id,
            name=model.name,
            languages=model.languages,
            can_do_text_to_speech=model.can_do_text_to_speech,
            maximum_text_length=model.maximum_text_length,
            cost_factor=model.cost_factor,
            source_state=source.state,
        )

    @staticmethod
    def _key(source: UnifiedCatalogSource, kind: str, item_id: str) -> str:
        profile = source.profile_id or "default"
        return f"{source.provider_id}:{profile}:{kind}:{item_id}"

    @staticmethod
    def _voice_languages(language: str | None, labels: dict[str, str]) -> tuple[str, ...]:
        values: list[str] = []
        if language:
            values.append(str(language))
        for key in ("language", "languages", "locale", "locales"):
            raw = str(labels.get(key) or "")
            values.extend(value.strip() for value in raw.split(",") if value.strip())
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _base_language(language: str | None) -> str:
        return str(language or "").strip().replace("_", "-").split("-", 1)[0].casefold()

    @staticmethod
    def _account_required(manifest, settings: AppSettings) -> bool:
        if not manifest.requires_credential:
            return False
        if settings.active_api_profile_id:
            return False
        return not bool(str(settings.api_key or "").strip()) and manifest.profile_secret_required

    @staticmethod
    def _built_in_models(provider_id: str) -> tuple[VoiceModelItem, ...]:
        if provider_id == "openai":
            from app.providers.openai_speech import OPENAI_SPEECH_MODELS

            return tuple(VoiceModelItem(model, model, ()) for model in OPENAI_SPEECH_MODELS)
        if provider_id == "google":
            from app.providers.optional_adapters import GoogleCloudTTSProvider

            return (
                VoiceModelItem(
                    GoogleCloudTTSProvider.DEFAULT_MODEL,
                    "Google Cloud voice-selected model",
                    (),
                ),
                *tuple(
                    VoiceModelItem(model, model, tuple(sorted(GoogleCloudTTSProvider.GEMINI_LANGUAGE_CODES)))
                    for model in GoogleCloudTTSProvider.GEMINI_MODELS
                ),
            )
        if provider_id == "aws_polly":
            from app.providers.optional_adapters import AmazonPollyProvider

            return tuple(
                VoiceModelItem(engine, f"Amazon Polly {engine.title()} engine", ())
                for engine in AmazonPollyProvider.ENGINES
            )
        if provider_id == "cartesia":
            from app.providers.cartesia import CARTESIA_LANGUAGES, CARTESIA_TTS_MODELS

            return tuple(
                VoiceModelItem(model, model, tuple(CARTESIA_LANGUAGES))
                for model in CARTESIA_TTS_MODELS
            )
        if provider_id == "resemble":
            from app.providers.resemble import RESEMBLE_DOCUMENTED_LOCALES, RESEMBLE_MODEL_ID

            return (
                VoiceModelItem(
                    RESEMBLE_MODEL_ID,
                    "Resemble Ultra (voice-managed)",
                    tuple(RESEMBLE_DOCUMENTED_LOCALES),
                ),
            )
        if provider_id == "murf":
            from app.providers.murf import MURF_MAX_TEXT_CHARACTERS, MURF_MODEL_ID

            return (
                VoiceModelItem(
                    MURF_MODEL_ID,
                    "Murf Gen2 (non-streaming)",
                    (),
                    maximum_text_length=MURF_MAX_TEXT_CHARACTERS,
                ),
            )
        if provider_id == "piper":
            return (VoiceModelItem("piper-local", "Piper local ONNX", ()),)
        return ()
