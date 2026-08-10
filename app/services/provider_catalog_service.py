from __future__ import annotations

from dataclasses import dataclass

from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult
from app.models.provider_manifest import ProviderControlPolicy, ProviderManifest
from app.provider_factory import PROVIDER_CLASSES, available_provider_ids, create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


@dataclass(frozen=True)
class ProviderCapabilityCard:
    provider_id: str
    display_name: str
    setup_state: str
    badges: tuple[str, ...]
    missing_dependency: str | None = None
    message: str = ""


class ProviderCatalogService:
    """Build provider-facing capability summaries without probing secrets.

    Live adapters remain authoritative for runtime capabilities. Phase 99 uses a
    central manifest registry for static metadata and UI policy so missing SDKs
    no longer force provider-id branching throughout the application.
    """

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY

    def provider_ids(self) -> tuple[str, ...]:
        return self.registry.ordered_provider_ids(available_provider_ids())

    def manifest_for(self, provider_id: str) -> ProviderManifest:
        return self.registry.manifest_for(provider_id)

    def control_policy_for(self, provider_id: str) -> ProviderControlPolicy:
        return self.manifest_for(provider_id).controls

    def is_local(self, provider_id: str) -> bool:
        return self.registry.is_local(provider_id)

    def capabilities_for(self, provider_id: str, settings: AppSettings | None = None) -> ProviderCapabilities:
        try:
            provider = create_provider(self._construct_settings(provider_id, settings))
            return provider.capabilities()
        except Exception as exc:
            return self._fallback_capabilities(provider_id, str(exc))

    def cards(self, settings: AppSettings | None = None) -> list[ProviderCapabilityCard]:
        return [self.card_for(provider_id, settings) for provider_id in self.provider_ids()]

    def card_for(self, provider_id: str, settings: AppSettings | None = None) -> ProviderCapabilityCard:
        provider_settings = settings.model_copy(update={"provider": provider_id}) if settings else AppSettings(provider=provider_id)
        capabilities = self.capabilities_for(provider_id, settings)
        try:
            provider = create_provider(self._construct_settings(provider_id, settings))
            validation = provider.validate_configuration(provider_settings)
        except Exception as exc:
            validation = ProviderConfigurationResult(False, str(exc), missing_dependency=capabilities.optional_dependency)
        manifest = self.manifest_for(provider_id)
        missing_credential = (
            capabilities.requires_credential
            and manifest.profile_secret_required
            and not provider_settings.api_key
        )
        badges: list[str] = ["Cloud" if capabilities.remote else "Local"]
        if not capabilities.remote:
            badges.append("Offline")
        if capabilities.supports_voice_listing:
            badges.append("Voice catalog")
        if capabilities.supports_ssml:
            badges.append("SSML")
        if capabilities.supports_pronunciation_dictionary:
            badges.append("Pronunciation dictionaries")
        if capabilities.supports_quota_lookup:
            badges.append("Quota available")
        if capabilities.optional_dependency and validation.missing_dependency:
            badges.append("Setup required")
        return ProviderCapabilityCard(
            provider_id=capabilities.provider_id,
            display_name=capabilities.display_name,
            setup_state="Ready" if validation.ok and not missing_credential else "Setup required",
            badges=tuple(dict.fromkeys(badges)),
            missing_dependency=validation.missing_dependency,
            message="Saved provider credential is required." if missing_credential else validation.message,
        )

    def _construct_settings(self, provider_id: str, settings: AppSettings | None) -> AppSettings:
        base = settings.model_copy(update={"provider": provider_id}) if settings else AppSettings(provider=provider_id)
        manifest = self.manifest_for(provider_id)
        if manifest.placeholder_api_key and not base.api_key:
            base.api_key = "capability-placeholder"
        return base

    def _fallback_capabilities(self, provider_id: str, _message: str) -> ProviderCapabilities:
        manifest = self.manifest_for(provider_id)
        provider_class = PROVIDER_CLASSES.get(provider_id)
        display_name = getattr(provider_class, "display_name", manifest.display_name)
        return ProviderCapabilities(
            provider_id=provider_id,
            display_name=display_name,
            remote=manifest.remote,
            requires_credential=manifest.requires_credential,
            supports_voice_listing=False,
            supports_model_listing=False,
            supports_language_code=manifest.supports_language_code_fallback,
            supports_cancellation=True,
            supported_output_formats=manifest.fallback_output_formats,
            optional_dependency=manifest.optional_dependency,
        )
