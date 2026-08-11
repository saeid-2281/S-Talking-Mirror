from __future__ import annotations

from collections.abc import Iterable

from app.models.provider_manifest import ProviderControlPolicy, ProviderManifest


DEFAULT_PROVIDER_MANIFESTS: tuple[ProviderManifest, ...] = (
    ProviderManifest(
        "mock",
        "Mock",
        locality="local",
        credential_mode="none",
        setup_kind="test",
        verified_locally=True,
        fallback_output_formats=("wav",),
        forced_file_extension=".wav",
        controls=ProviderControlPolicy(
            connection_test=False,
            voice_browser_fallback=True,
            model_listing_fallback=True,
            voice_required=False,
        ),
    ),
    ProviderManifest(
        "piper",
        "Piper",
        locality="local",
        credential_mode="none",
        setup_kind="local_model",
        optional_dependency="piper",
        fallback_output_formats=("wav",),
        forced_file_extension=".wav",
        controls=ProviderControlPolicy(
            local_model_path=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
            voice_required=False,
        ),
    ),
    ProviderManifest(
        "elevenlabs",
        "ElevenLabs",
        locality="cloud",
        credential_mode="profile_or_key",
        setup_kind="credential",
        retry_ready=True,
        placeholder_api_key=True,
        profile_management_ready=True,
        controls=ProviderControlPolicy(
            api_profile=True,
            api_key=True,
            account_failover=True,
            stability=True,
            similarity=True,
            style=True,
            speaker_boost=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "openai",
        "OpenAI Speech",
        locality="cloud",
        credential_mode="profile_or_key",
        setup_kind="credential",
        retry_ready=True,
        placeholder_api_key=True,
        supports_language_code_fallback=False,
        profile_management_ready=True,
        synthesis_request_limit=4096,
        synthesis_request_limit_unit="characters",
        synthesis_request_limit_note="OpenAI Speech input limit per synthesis request.",
        controls=ProviderControlPolicy(
            api_profile=True,
            api_key=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "azure",
        "Azure Speech",
        locality="cloud",
        credential_mode="profile",
        setup_kind="optional_cloud",
        optional_dependency="azure.cognitiveservices.speech",
        placeholder_api_key=True,
        retry_ready=True,
        profile_metadata_fields=("region", "endpoint"),
        profile_management_ready=True,
        controls=ProviderControlPolicy(
            api_profile=True,
            voice_browser_fallback=True,
        ),
    ),
    ProviderManifest(
        "google",
        "Google Cloud TTS",
        locality="cloud",
        credential_mode="profile",
        setup_kind="optional_cloud",
        optional_dependency="google.cloud.texttospeech",
        retry_ready=True,
        profile_metadata_fields=("credential_reference", "project_id", "api_endpoint"),
        profile_management_ready=True,
        profile_secret_required=False,
        synthesis_request_limit=5000,
        synthesis_request_limit_unit="bytes",
        synthesis_request_limit_note="Google Cloud classic TTS synchronous input limit; Gemini-TTS has a separate prompt/text contract.",
        controls=ProviderControlPolicy(
            api_profile=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "aws_polly",
        "Amazon Polly",
        locality="cloud",
        credential_mode="profile",
        setup_kind="optional_cloud",
        optional_dependency="boto3",
        retry_ready=True,
        profile_metadata_fields=("aws_profile", "region"),
        profile_management_ready=True,
        profile_secret_required=False,
        synthesis_request_limit=3000,
        synthesis_request_limit_unit="billed_characters",
        synthesis_request_limit_note="Amazon Polly SynthesizeSpeech allows 3,000 billed characters and 6,000 total characters including SSML/whitespace.",
        controls=ProviderControlPolicy(
            api_profile=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "kokoro",
        "Kokoro",
        locality="local",
        credential_mode="none",
        setup_kind="optional_local",
        optional_dependency="kokoro",
        fallback_output_formats=("wav",),
        forced_file_extension=".wav",
        controls=ProviderControlPolicy(
            voice_browser_fallback=True,
            model_listing_fallback=True,
            voice_required=True,
        ),
    ),
    ProviderManifest(
        "cartesia",
        "Cartesia",
        locality="cloud",
        credential_mode="profile_or_key",
        setup_kind="credential",
        retry_ready=True,
        placeholder_api_key=True,
        fallback_output_formats=("mp3", "wav"),
        profile_management_ready=True,
        controls=ProviderControlPolicy(
            api_profile=True,
            api_key=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "deepgram",
        "Deepgram Aura",
        locality="cloud",
        credential_mode="profile_or_key",
        setup_kind="credential",
        retry_ready=True,
        placeholder_api_key=True,
        fallback_output_formats=("mp3", "wav", "opus", "flac", "aac", "pcm"),
        profile_management_ready=True,
        controls=ProviderControlPolicy(
            api_profile=True,
            api_key=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "resemble",
        "Resemble AI",
        locality="cloud",
        credential_mode="profile_or_key",
        setup_kind="credential",
        retry_ready=True,
        placeholder_api_key=True,
        fallback_output_formats=("wav", "mp3"),
        profile_management_ready=True,
        controls=ProviderControlPolicy(
            api_profile=True,
            api_key=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
    ProviderManifest(
        "murf",
        "Murf",
        locality="cloud",
        credential_mode="profile_or_key",
        setup_kind="credential",
        retry_ready=True,
        placeholder_api_key=True,
        fallback_output_formats=("mp3", "wav", "flac", "ogg", "pcm"),
        profile_management_ready=True,
        synthesis_request_limit=3000,
        synthesis_request_limit_unit="characters",
        synthesis_request_limit_note="Murf TTS API request character limit.",
        controls=ProviderControlPolicy(
            api_profile=True,
            api_key=True,
            voice_browser_fallback=True,
            model_listing_fallback=True,
        ),
    ),
)


class ProviderRegistry:
    """Ordered, validated source of static provider architecture metadata."""

    def __init__(self, manifests: Iterable[ProviderManifest] = DEFAULT_PROVIDER_MANIFESTS) -> None:
        ordered = tuple(manifests)
        by_id: dict[str, ProviderManifest] = {}
        for manifest in ordered:
            if manifest.provider_id in by_id:
                raise ValueError(f"Duplicate provider manifest: {manifest.provider_id}")
            by_id[manifest.provider_id] = manifest
        self._ordered = ordered
        self._by_id = by_id
        self._base_provider_ids = frozenset(by_id)
        self._plugin_provider_ids: set[str] = set()

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(manifest.provider_id for manifest in self._ordered)

    def register_plugin_manifest(self, manifest: ProviderManifest) -> None:
        """Append a validated session plugin manifest without replacing built-ins."""

        provider_id = manifest.provider_id
        if provider_id in self._by_id:
            raise ValueError(f"Provider manifest is already registered: {provider_id}")
        self._ordered = (*self._ordered, manifest)
        self._by_id[provider_id] = manifest
        self._plugin_provider_ids.add(provider_id)

    def unregister_plugin_manifest(self, provider_id: str) -> None:
        """Remove a session plugin manifest while built-in manifests remain immutable."""

        normalized = str(provider_id or "").strip().casefold()
        if normalized in self._base_provider_ids:
            raise ValueError(f"Built-in provider manifest cannot be unregistered: {normalized}")
        if normalized not in self._plugin_provider_ids:
            raise ValueError(f"Plugin provider manifest is not registered: {normalized}")
        self._plugin_provider_ids.discard(normalized)
        self._by_id.pop(normalized, None)
        self._ordered = tuple(item for item in self._ordered if item.provider_id != normalized)

    def plugin_provider_ids(self) -> tuple[str, ...]:
        return tuple(
            item.provider_id
            for item in self._ordered
            if item.provider_id in self._plugin_provider_ids
        )

    def ordered_provider_ids(self, registered_ids: Iterable[str]) -> tuple[str, ...]:
        registered = tuple(dict.fromkeys(str(item) for item in registered_ids))
        known = [provider_id for provider_id in self.provider_ids() if provider_id in registered]
        extras = [provider_id for provider_id in registered if provider_id not in self._by_id]
        return tuple(known + extras)

    def manifest_for(self, provider_id: str) -> ProviderManifest:
        normalized = str(provider_id or "unknown").strip().casefold() or "unknown"
        manifest = self._by_id.get(normalized)
        if manifest is not None:
            return manifest
        display_name = normalized.replace("_", " ").title()
        return ProviderManifest(
            normalized,
            display_name,
            locality="cloud",
            credential_mode="profile",
            setup_kind="optional_cloud",
            production_supported=False,
            controls=ProviderControlPolicy(api_profile=True),
        )

    def output_extension(self, provider_id: str, requested: str) -> str:
        manifest = self.manifest_for(provider_id)
        return manifest.forced_file_extension or requested

    def is_local(self, provider_id: str) -> bool:
        return self.manifest_for(provider_id).locality == "local"


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry()
