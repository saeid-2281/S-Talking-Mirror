from __future__ import annotations

from pathlib import Path

from app.models.provider_identity import ProviderIdentity
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


PROVIDER_IDENTITIES: dict[str, ProviderIdentity] = {
    "mock": ProviderIdentity(
        "mock",
        "Mock / Test Provider",
        "Mock",
        "play",
        "Local",
        "docs/PROVIDER_BRAND_ASSETS.md#mock--test-provider",
    ),
    "piper": ProviderIdentity("piper", "Piper", "Piper", "settings", "Local", "https://github.com/OHF-Voice/piper1-gpl"),
    "elevenlabs": ProviderIdentity("elevenlabs", "ElevenLabs", "ElevenLabs", "settings", "Cloud", "https://elevenlabs.io/docs"),
    "openai": ProviderIdentity("openai", "OpenAI", "OpenAI", "settings", "Cloud", "https://platform.openai.com/docs/guides/text-to-speech"),
    "azure": ProviderIdentity("azure", "Microsoft Azure Speech", "Azure Speech", "settings", "Cloud", "https://learn.microsoft.com/azure/ai-services/speech-service/"),
    "google": ProviderIdentity("google", "Google Cloud Text-to-Speech", "Google TTS", "settings", "Cloud", "https://cloud.google.com/text-to-speech/docs"),
    "aws_polly": ProviderIdentity("aws_polly", "Amazon Polly", "Polly", "settings", "Cloud", "https://docs.aws.amazon.com/polly/"),
    "kokoro": ProviderIdentity("kokoro", "Kokoro", "Kokoro", "settings", "Local", "https://github.com/hexgrad/kokoro"),
    "cartesia": ProviderIdentity("cartesia", "Cartesia", "Cartesia", "settings", "Cloud", "https://docs.cartesia.ai/"),
    "deepgram": ProviderIdentity("deepgram", "Deepgram Aura", "Deepgram", "settings", "Cloud", "https://developers.deepgram.com/docs/text-to-speech"),
    "resemble": ProviderIdentity("resemble", "Resemble AI", "Resemble", "settings", "Cloud", "https://docs.resemble.ai/"),
    "murf": ProviderIdentity("murf", "Murf", "Murf", "settings", "Cloud", "https://murf.ai/api/docs/introduction/overview"),
}


class ProviderIdentityService:
    """Central user-facing provider names and asset provenance."""

    def __init__(
        self,
        brand_dir: Path | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.brand_dir = brand_dir
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY

    def identity_for(self, provider_id: str) -> ProviderIdentity:
        identity = PROVIDER_IDENTITIES.get(provider_id)
        if identity is not None:
            return identity
        manifest = self.registry.manifest_for(provider_id)
        locality = "Local" if manifest.locality == "local" else "Cloud"
        return ProviderIdentity(
            manifest.provider_id,
            manifest.display_name,
            manifest.display_name,
            "settings",
            locality,
            "",
        )

    def display_name(self, provider_id: str) -> str:
        return self.identity_for(provider_id).display_name

    def all(self) -> tuple[ProviderIdentity, ...]:
        return tuple(PROVIDER_IDENTITIES.values())
