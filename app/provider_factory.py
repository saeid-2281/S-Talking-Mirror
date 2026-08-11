from __future__ import annotations

from app.exceptions import ConfigurationError
from app.providers.cartesia import CartesiaProvider
from app.providers.deepgram import DeepgramProvider
from app.providers.murf import MurfProvider
from app.providers.resemble import ResembleProvider
from app.providers.elevenlabs import ElevenLabsProvider
from app.providers.mock import MockProvider
from app.providers.openai_speech import OpenAISpeechProvider
from app.providers.optional_adapters import AmazonPollyProvider, AzureSpeechProvider, GoogleCloudTTSProvider, KokoroLocalProvider
from app.providers.piper import PiperProvider
from app.providers.base import TTSProvider

PROVIDER_CLASSES = {
    "elevenlabs": ElevenLabsProvider,
    "mock": MockProvider,
    "piper": PiperProvider,
    "openai": OpenAISpeechProvider,
    "azure": AzureSpeechProvider,
    "google": GoogleCloudTTSProvider,
    "aws_polly": AmazonPollyProvider,
    "kokoro": KokoroLocalProvider,
    "cartesia": CartesiaProvider,
    "deepgram": DeepgramProvider,
    "resemble": ResembleProvider,
    "murf": MurfProvider,
}

_BUILTIN_PROVIDER_IDS = frozenset(PROVIDER_CLASSES)
_PLUGIN_PROVIDER_IDS: set[str] = set()


def register_provider_class(provider_id: str, provider_class: type[TTSProvider]) -> None:
    """Register one explicitly approved session plugin provider class."""

    normalized = str(provider_id or "").strip().casefold()
    if not normalized or normalized != provider_id:
        raise ConfigurationError("Plugin provider_id must be a non-empty lowercase stable identifier.")
    if normalized in _BUILTIN_PROVIDER_IDS:
        raise ConfigurationError(f"Built-in provider cannot be overridden: {normalized}")
    if normalized in PROVIDER_CLASSES:
        raise ConfigurationError(f"Provider is already registered: {normalized}")
    if not isinstance(provider_class, type) or not issubclass(provider_class, TTSProvider):
        raise ConfigurationError("Plugin provider class must inherit TTSProvider.")
    if str(getattr(provider_class, "provider_id", "")).strip() != normalized:
        raise ConfigurationError("Plugin provider class provider_id does not match its manifest.")
    PROVIDER_CLASSES[normalized] = provider_class
    _PLUGIN_PROVIDER_IDS.add(normalized)


def unregister_provider_class(provider_id: str) -> None:
    """Remove a session plugin provider without touching built-in adapters."""

    normalized = str(provider_id or "").strip().casefold()
    if normalized in _BUILTIN_PROVIDER_IDS:
        raise ConfigurationError(f"Built-in provider cannot be unregistered: {normalized}")
    if normalized not in _PLUGIN_PROVIDER_IDS:
        raise ConfigurationError(f"Plugin provider is not registered: {normalized}")
    PROVIDER_CLASSES.pop(normalized, None)
    _PLUGIN_PROVIDER_IDS.discard(normalized)


def plugin_provider_ids() -> tuple[str, ...]:
    return tuple(provider_id for provider_id in PROVIDER_CLASSES if provider_id in _PLUGIN_PROVIDER_IDS)


def create_provider(settings):
    provider_class = PROVIDER_CLASSES.get(settings.provider)
    if provider_class is None:
        raise ConfigurationError(f"Unsupported provider: {settings.provider}")
    return provider_class(settings)


def available_provider_ids() -> list[str]:
    return list(PROVIDER_CLASSES)
