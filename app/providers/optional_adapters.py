from __future__ import annotations

import importlib.util

from app.exceptions import ConfigurationError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult
from app.providers.base import TTSProvider


class OptionalSetupProvider(TTSProvider):
    provider_id = "optional"
    display_name = "Optional Provider"
    dependency_name = ""
    setup_hint = "Install the provider optional dependency and configure credentials."
    remote = True
    credential_fields: tuple[str, ...] = ()
    output_formats: tuple[str, ...] = ("mp3", "wav")

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def capabilities(self) -> ProviderCapabilities:
        available = self.dependency_available()
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=self.remote,
            requires_credential=self.remote,
            supports_voice_listing=available,
            supports_model_listing=available,
            supports_language_code=True,
            supports_ssml=self.provider_id in {"azure", "aws_polly"},
            supports_speed=True,
            supports_pitch=self.provider_id in {"azure", "google", "aws_polly"},
            supports_volume=self.provider_id in {"azure", "google"},
            supports_quota_lookup=False,
            supports_cancellation=True,
            supported_output_formats=self.output_formats,
            credential_fields=self.credential_fields,
            optional_dependency=self.dependency_name or None,
        )

    def dependency_available(self) -> bool:
        try:
            return not self.dependency_name or importlib.util.find_spec(self.dependency_name) is not None
        except ModuleNotFoundError:
            return False

    def validate_configuration(self, _settings: AppSettings) -> ProviderConfigurationResult:
        if not self.dependency_available():
            return ProviderConfigurationResult(False, self.setup_hint, missing_dependency=self.dependency_name)
        return ProviderConfigurationResult(True, f"{self.display_name} dependency is available.")

    def test_connection(self) -> ProviderConfigurationResult:
        return self.validate_configuration(self.settings)

    def list_voices(self) -> list[dict]:
        return []

    def list_models(self) -> list[dict]:
        return []

    def synthesize(self, _text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        raise ConfigurationError(result.message)


class AzureSpeechProvider(OptionalSetupProvider):
    provider_id = "azure"
    display_name = "Azure AI Speech"
    dependency_name = "azure.cognitiveservices.speech"
    setup_hint = "Azure Speech requires the optional azure provider dependency plus region and credential metadata."
    credential_fields = ("subscription_key", "region", "endpoint")


class GoogleCloudTTSProvider(OptionalSetupProvider):
    provider_id = "google"
    display_name = "Google Cloud Text-to-Speech"
    dependency_name = "google.cloud.texttospeech"
    setup_hint = "Google Cloud TTS requires the optional google provider dependency and ADC or a safe credential reference."
    credential_fields = ("credential_reference", "project_id")


class AmazonPollyProvider(OptionalSetupProvider):
    provider_id = "aws_polly"
    display_name = "Amazon Polly"
    dependency_name = "boto3"
    setup_hint = "Amazon Polly requires boto3 and standard AWS credential/profile resolution."
    credential_fields = ("aws_profile", "region")


class KokoroLocalProvider(OptionalSetupProvider):
    provider_id = "kokoro"
    display_name = "Kokoro Local"
    dependency_name = "kokoro"
    setup_hint = "Kokoro requires the optional local runtime and voice/model assets."
    remote = False
    credential_fields = ()
    output_formats = ("wav",)
