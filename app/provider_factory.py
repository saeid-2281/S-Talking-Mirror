from __future__ import annotations

from app.exceptions import ConfigurationError
from app.providers.elevenlabs import ElevenLabsProvider
from app.providers.mock import MockProvider
from app.providers.openai_speech import OpenAISpeechProvider
from app.providers.optional_adapters import AmazonPollyProvider, AzureSpeechProvider, GoogleCloudTTSProvider, KokoroLocalProvider
from app.providers.piper import PiperProvider

PROVIDER_CLASSES = {
    "elevenlabs": ElevenLabsProvider,
    "mock": MockProvider,
    "piper": PiperProvider,
    "openai": OpenAISpeechProvider,
    "azure": AzureSpeechProvider,
    "google": GoogleCloudTTSProvider,
    "aws_polly": AmazonPollyProvider,
    "kokoro": KokoroLocalProvider,
}


def create_provider(settings):
    provider_class = PROVIDER_CLASSES.get(settings.provider)
    if provider_class is None:
        raise ConfigurationError(f"Unsupported provider: {settings.provider}")
    return provider_class(settings)


def available_provider_ids() -> list[str]:
    return list(PROVIDER_CLASSES)
