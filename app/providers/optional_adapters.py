from __future__ import annotations

import importlib.util
import html

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult, ProviderNormalizedError
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

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        message = str(error)
        lower = message.lower()
        retryable = any(token in lower for token in ("timeout", "temporarily", "rate", "throttl", "unavailable", "500", "503"))
        code = "provider_error"
        if "credential" in lower or "auth" in lower or "permission" in lower:
            code = "credential_or_permission"
            retryable = False
        if "quota" in lower or "limit" in lower:
            code = "quota_or_rate_limit"
        return ProviderNormalizedError(code, message, retryable=retryable, safe_details=message[:500])


class AzureSpeechProvider(OptionalSetupProvider):
    provider_id = "azure"
    display_name = "Azure AI Speech"
    dependency_name = "azure.cognitiveservices.speech"
    setup_hint = "Azure Speech requires the optional azure provider dependency plus region and credential metadata."
    credential_fields = ("subscription_key", "region", "endpoint")

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = super().validate_configuration(settings)
        if not base.ok:
            return base
        if not settings.api_key:
            return ProviderConfigurationResult(False, "Azure Speech subscription key is required.")
        if not settings.language_code:
            return ProviderConfigurationResult(False, "Azure Speech region/language metadata is required.")
        return ProviderConfigurationResult(True, "Azure Speech SDK is available.")

    def list_voices(self) -> list[dict]:
        if not self.dependency_available():
            return []
        try:
            import azure.cognitiveservices.speech as speechsdk

            config = speechsdk.SpeechConfig(subscription=self.settings.api_key, region=self.settings.language_code or "westus")
            voices = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None).get_voices_async().get()
            return [
                {"voice_id": voice.short_name, "name": voice.local_name or voice.short_name, "locale": voice.locale}
                for voice in getattr(voices, "voices", [])
            ]
        except Exception:
            return []

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        if not result.ok:
            raise ConfigurationError(result.message)
        try:
            import azure.cognitiveservices.speech as speechsdk

            config = speechsdk.SpeechConfig(subscription=settings.api_key, region=settings.language_code or "westus")
            if settings.voice_id:
                config.speech_synthesis_voice_name = settings.voice_id
            synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
            ssml = self.safe_ssml(text, settings)
            outcome = synthesizer.speak_ssml_async(ssml).get()
            if outcome.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                raise ProviderError("Azure Speech synthesis failed.", provider_code=str(outcome.reason))
            return bytes(outcome.audio_data)
        except Exception as exc:
            raise ProviderError(str(exc), provider_code="azure_synthesis_error") from exc

    @staticmethod
    def safe_ssml(text: str, settings: AppSettings) -> str:
        voice = html.escape(settings.voice_id or "en-US-JennyNeural", quote=True)
        lang = html.escape(settings.language_code or "en-US", quote=True)
        body = html.escape(text, quote=False)
        return f"<speak version='1.0' xml:lang='{lang}'><voice name='{voice}'>{body}</voice></speak>"


class GoogleCloudTTSProvider(OptionalSetupProvider):
    provider_id = "google"
    display_name = "Google Cloud Text-to-Speech"
    dependency_name = "google.cloud.texttospeech"
    setup_hint = "Google Cloud TTS requires the optional google provider dependency and ADC or a safe credential reference."
    credential_fields = ("credential_reference", "project_id")

    def list_voices(self) -> list[dict]:
        if not self.dependency_available():
            return []
        try:
            from google.cloud import texttospeech

            client = texttospeech.TextToSpeechClient()
            response = client.list_voices(language_code=self.settings.language_code or "")
            return [
                {"voice_id": voice.name, "name": voice.name, "language_codes": list(voice.language_codes), "gender": str(voice.ssml_gender)}
                for voice in response.voices
            ]
        except Exception:
            return []

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        if not result.ok:
            raise ConfigurationError(result.message)
        try:
            from google.cloud import texttospeech

            client = texttospeech.TextToSpeechClient()
            input_text = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(language_code=settings.language_code or "en-US", name=settings.voice_id or None)
            audio = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=settings.speed)
            response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio)
            return bytes(response.audio_content)
        except Exception as exc:
            raise ProviderError(str(exc), provider_code="google_synthesis_error") from exc


class AmazonPollyProvider(OptionalSetupProvider):
    provider_id = "aws_polly"
    display_name = "Amazon Polly"
    dependency_name = "boto3"
    setup_hint = "Amazon Polly requires boto3 and standard AWS credential/profile resolution."
    credential_fields = ("aws_profile", "region")

    def list_voices(self) -> list[dict]:
        if not self.dependency_available():
            return []
        try:
            import boto3

            client = boto3.Session().client("polly")
            response = client.describe_voices(LanguageCode=self.settings.language_code) if self.settings.language_code else client.describe_voices()
            return [
                {"voice_id": voice["Id"], "name": voice.get("Name", voice["Id"]), "language_code": voice.get("LanguageCode"), "engines": voice.get("SupportedEngines", [])}
                for voice in response.get("Voices", [])
            ]
        except Exception:
            return []

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        if not result.ok:
            raise ConfigurationError(result.message)
        try:
            import boto3

            client = boto3.Session().client("polly")
            response = client.synthesize_speech(Text=text, VoiceId=settings.voice_id or "Joanna", OutputFormat="mp3", Engine="neural")
            return response["AudioStream"].read()
        except Exception as exc:
            raise ProviderError(str(exc), provider_code="aws_polly_synthesis_error") from exc


class KokoroLocalProvider(OptionalSetupProvider):
    provider_id = "kokoro"
    display_name = "Kokoro Local"
    dependency_name = "kokoro"
    setup_hint = "Kokoro requires the optional local runtime and voice/model assets."
    remote = False
    credential_fields = ()
    output_formats = ("wav",)

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = super().validate_configuration(settings)
        if not base.ok:
            return base
        return ProviderConfigurationResult(True, "Kokoro runtime is available. Language support comes from the installed runtime.")

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        result = self.validate_configuration(settings)
        if not result.ok:
            raise ConfigurationError(result.message)
        try:
            from kokoro import KPipeline
            import soundfile as sf
            import io

            pipeline = KPipeline(lang_code=settings.language_code or "a")
            audio_chunks = []
            for _graphemes, _phonemes, audio in pipeline(text, voice=settings.voice_id or None):
                audio_chunks.extend(audio)
            buffer = io.BytesIO()
            sf.write(buffer, audio_chunks, 24000, format="WAV")
            return buffer.getvalue()
        except Exception as exc:
            raise ProviderError(str(exc), provider_code="kokoro_synthesis_error") from exc
