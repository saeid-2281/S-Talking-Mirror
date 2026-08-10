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
    setup_hint = (
        "Azure Speech requires the optional azure provider dependency, "
        "a Speech resource key, and either region or endpoint metadata."
    )
    credential_fields = ("api_key", "region", "endpoint")
    output_formats = ("mp3", "wav", "opus", "pcm")

    def __init__(self, settings: AppSettings) -> None:
        super().__init__(settings)
        self._active_synthesizer = None

    def capabilities(self) -> ProviderCapabilities:
        available = self.dependency_available()
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=True,
            requires_credential=True,
            supports_voice_listing=available,
            supports_model_listing=False,
            supports_language_code=True,
            supports_ssml=True,
            supports_speed=True,
            supports_pitch=True,
            supports_volume=True,
            supports_quota_lookup=False,
            supports_cancellation=True,
            supported_output_formats=self.output_formats,
            credential_fields=self.credential_fields,
            optional_dependency=self.dependency_name,
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = super().validate_configuration(settings)
        if not base.ok:
            return base
        if not settings.api_key.strip():
            return ProviderConfigurationResult(
                False,
                "Azure Speech resource key is required.",
            )
        region = self._option(settings, "region")
        endpoint = self._option(settings, "endpoint")
        if not region and not endpoint:
            return ProviderConfigurationResult(
                False,
                "Azure Speech profile requires a region or endpoint.",
            )
        if endpoint and not endpoint.casefold().startswith("https://"):
            return ProviderConfigurationResult(
                False,
                "Azure Speech endpoint must use HTTPS.",
            )
        return ProviderConfigurationResult(
            True,
            "Azure Speech SDK and resource metadata are configured.",
        )

    def test_connection(self) -> ProviderConfigurationResult:
        validation = self.validate_configuration(self.settings)
        if not validation.ok:
            return validation
        voices = self.list_voices()
        return ProviderConfigurationResult(
            True,
            f"Azure Speech connected; {len(voices)} voice(s) discovered.",
        )

    def list_voices(self) -> list[dict]:
        validation = self.validate_configuration(self.settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        try:
            import azure.cognitiveservices.speech as speechsdk

            config = self._speech_config(self.settings, speechsdk)
            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=config,
                audio_config=None,
            )
            outcome = synthesizer.get_voices_async().get()
            voices = getattr(outcome, "voices", ()) or ()
            return [
                {
                    "voice_id": voice.short_name,
                    "name": voice.local_name or voice.short_name,
                    "locale": voice.locale,
                    "category": "azure-neural",
                    "description": str(getattr(voice, "voice_type", "") or ""),
                    "labels": {
                        "language": str(voice.locale or ""),
                        "gender": str(getattr(voice, "gender", "") or ""),
                    },
                }
                for voice in voices
                if str(getattr(voice, "short_name", "") or "").strip()
            ]
        except ConfigurationError:
            raise
        except Exception as exc:
            raise self._provider_error(exc, "azure_voice_catalog_error") from exc

    def list_languages(self) -> list[dict[str, str]]:
        locales = sorted(
            {
                str(voice.get("locale") or "").strip()
                for voice in self.list_voices()
                if str(voice.get("locale") or "").strip()
            },
            key=str.casefold,
        )
        return [{"language_code": locale, "name": locale} for locale in locales]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        if not str(settings.voice_id or "").strip():
            raise ConfigurationError("Azure Speech voice is required.")
        try:
            import azure.cognitiveservices.speech as speechsdk

            config = self._speech_config(settings, speechsdk)
            config.speech_synthesis_voice_name = settings.voice_id
            output_format = self._sdk_output_format(settings, speechsdk)
            config.set_speech_synthesis_output_format(output_format)

            synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=config,
                audio_config=None,
            )
            self._active_synthesizer = synthesizer
            try:
                outcome = synthesizer.speak_ssml_async(
                    self.safe_ssml(text, settings)
                ).get()
            finally:
                self._active_synthesizer = None

            if outcome.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                audio = bytes(outcome.audio_data)
                if not audio:
                    raise ProviderError(
                        "Azure Speech returned empty audio.",
                        retryable=True,
                        provider_code="empty_audio",
                    )
                return audio

            details = speechsdk.SpeechSynthesisCancellationDetails.from_result(outcome)
            error_details = str(getattr(details, "error_details", "") or "")
            error_code = str(getattr(details, "error_code", "") or "")
            raise ProviderError(
                "Azure Speech synthesis was cancelled by the service.",
                retryable=self._retryable_message(f"{error_code} {error_details}"),
                provider_code="azure_synthesis_cancelled",
                technical_details=f"{error_code}: {error_details}"[:500],
            )
        except (ConfigurationError, ProviderError):
            raise
        except Exception as exc:
            raise self._provider_error(exc, "azure_synthesis_error") from exc

    def cancel(self) -> None:
        synthesizer = self._active_synthesizer
        if synthesizer is None:
            return
        stop = getattr(synthesizer, "stop_speaking_async", None)
        if callable(stop):
            try:
                operation = stop()
                get = getattr(operation, "get", None)
                if callable(get):
                    get()
            except Exception:
                # Cancellation is best effort; generation state remains
                # authoritative and late results are discarded upstream.
                pass

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "azure_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        return super().normalize_error(error)

    @classmethod
    def _speech_config(cls, settings: AppSettings, speechsdk):
        endpoint = cls._option(settings, "endpoint")
        if endpoint:
            return speechsdk.SpeechConfig(
                subscription=settings.api_key,
                endpoint=endpoint,
            )
        return speechsdk.SpeechConfig(
            subscription=settings.api_key,
            region=cls._option(settings, "region"),
        )

    @classmethod
    def _sdk_output_format(cls, settings: AppSettings, speechsdk):
        simple = (settings.output_format or "mp3").split("_", 1)[0].casefold()
        names = {
            "mp3": "Audio24Khz96KBitRateMonoMp3",
            "wav": "Riff24Khz16BitMonoPcm",
            "opus": "Ogg24Khz16BitMonoOpus",
            "pcm": "Raw24Khz16BitMonoPcm",
        }
        name = names.get(simple)
        if not name:
            raise ConfigurationError(
                f"Unsupported Azure Speech output format: {simple}."
            )
        try:
            return getattr(speechsdk.SpeechSynthesisOutputFormat, name)
        except AttributeError as exc:
            raise ConfigurationError(
                f"Installed Azure Speech SDK does not support {simple} output."
            ) from exc

    @classmethod
    def safe_ssml(cls, text: str, settings: AppSettings) -> str:
        voice = html.escape(settings.voice_id or "", quote=True)
        lang = html.escape(cls._ssml_language(settings), quote=True)
        body = html.escape(text, quote=False)
        rate_delta = round((float(settings.speed) - 1.0) * 100)
        rate = f"{rate_delta:+d}%"
        return (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{lang}'>"
            f"<voice name='{voice}'><prosody rate='{rate}'>{body}</prosody></voice>"
            "</speak>"
        )

    @classmethod
    def _ssml_language(cls, settings: AppSettings) -> str:
        language = str(settings.language_code or "").strip()
        if "-" in language:
            return language
        voice = str(settings.voice_id or "").strip()
        parts = voice.split("-")
        if len(parts) >= 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
            return f"{parts[0]}-{parts[1]}"
        common = {"da": "da-DK", "en": "en-US"}
        return common.get(language.casefold(), language or "en-US")

    @staticmethod
    def _option(settings: AppSettings, key: str) -> str:
        value = settings.provider_options.get(key)
        return str(value or "").strip()

    @classmethod
    def _provider_error(cls, error: Exception, code: str) -> ProviderError:
        message = str(error)
        return ProviderError(
            "Azure Speech request failed.",
            retryable=cls._retryable_message(message),
            provider_code=code,
            technical_details=message[:500],
        )

    @staticmethod
    def _retryable_message(message: str) -> bool:
        lower = message.casefold()
        return any(
            token in lower
            for token in (
                "timeout",
                "temporar",
                "throttl",
                "too many requests",
                "429",
                "502",
                "503",
                "service unavailable",
                "connection",
            )
        )


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
