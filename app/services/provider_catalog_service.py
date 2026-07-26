from __future__ import annotations

from dataclasses import dataclass

from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities
from app.models.provider_contract import ProviderConfigurationResult
from app.provider_factory import PROVIDER_CLASSES, available_provider_ids, create_provider


@dataclass(frozen=True)
class ProviderCapabilityCard:
    provider_id: str
    display_name: str
    setup_state: str
    badges: tuple[str, ...]
    missing_dependency: str | None = None
    message: str = ""


class ProviderCatalogService:
    """Builds provider-facing capability summaries without probing secrets."""

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(available_provider_ids())

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
        missing_credential = capabilities.requires_credential and not provider_settings.api_key
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
            message="Credential profile or API key is required." if missing_credential else validation.message,
        )

    @staticmethod
    def _construct_settings(provider_id: str, settings: AppSettings | None) -> AppSettings:
        base = settings.model_copy(update={"provider": provider_id}) if settings else AppSettings(provider=provider_id)
        if provider_id == "elevenlabs" and not base.api_key:
            base.api_key = "capability-placeholder"
        return base

    @staticmethod
    def _fallback_capabilities(provider_id: str, message: str) -> ProviderCapabilities:
        provider_class = PROVIDER_CLASSES.get(provider_id)
        display_name = getattr(provider_class, "display_name", provider_id)
        remote = provider_id not in {"mock", "piper", "kokoro"}
        dependency = {
            "piper": "piper",
            "azure": "azure.cognitiveservices.speech",
            "google": "google.cloud.texttospeech",
            "aws_polly": "boto3",
            "kokoro": "kokoro",
        }.get(provider_id)
        return ProviderCapabilities(
            provider_id=provider_id,
            display_name=display_name,
            remote=remote,
            requires_credential=remote,
            supports_voice_listing=False,
            supports_model_listing=False,
            supports_language_code=provider_id != "openai",
            supports_cancellation=True,
            supported_output_formats=("wav",) if provider_id in {"piper", "kokoro"} else ("mp3", "wav"),
            optional_dependency=dependency if "not installed" in message.lower() or "requires" in message.lower() else dependency,
        )
