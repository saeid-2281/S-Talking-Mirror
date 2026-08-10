from __future__ import annotations

import importlib.util
import html
import threading
from pathlib import Path
import xml.etree.ElementTree as ET

from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities, ProviderConfigurationResult, ProviderNormalizedError
from app.providers.base import TTSProvider
from app.providers.kokoro_runtime import KokoroRuntimeService, shared_kokoro_runtime_service


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
        validation = self._validate_access_configuration(self.settings)
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
    setup_hint = (
        "Google Cloud TTS requires google-cloud-texttospeech and Application Default "
        "Credentials (ADC) or a service-account credential reference."
    )
    credential_fields = ("credential_reference", "project_id", "api_endpoint")
    output_formats = ("mp3", "wav", "ogg_opus")

    GEMINI_MODELS = (
        "gemini-3.1-flash-tts-preview",
        "gemini-2.5-flash-tts",
        "gemini-2.5-flash-lite-preview-tts",
        "gemini-2.5-pro-tts",
    )
    DEFAULT_MODEL = "google-cloud-default"
    GEMINI_VOICES = (
        ("Achernar", "FEMALE"),
        ("Achird", "MALE"),
        ("Algenib", "MALE"),
        ("Algieba", "MALE"),
        ("Alnilam", "MALE"),
        ("Aoede", "FEMALE"),
        ("Autonoe", "FEMALE"),
        ("Callirrhoe", "FEMALE"),
        ("Charon", "MALE"),
        ("Despina", "FEMALE"),
        ("Enceladus", "MALE"),
        ("Erinome", "FEMALE"),
        ("Fenrir", "MALE"),
        ("Gacrux", "FEMALE"),
        ("Iapetus", "MALE"),
        ("Kore", "FEMALE"),
        ("Laomedeia", "FEMALE"),
        ("Leda", "FEMALE"),
        ("Orus", "MALE"),
        ("Pulcherrima", "FEMALE"),
        ("Puck", "MALE"),
        ("Rasalgethi", "MALE"),
        ("Sadachbia", "MALE"),
        ("Sadaltager", "MALE"),
        ("Schedar", "MALE"),
        ("Sulafat", "FEMALE"),
        ("Umbriel", "MALE"),
        ("Vindemiatrix", "FEMALE"),
        ("Zephyr", "FEMALE"),
        ("Zubenelgenubi", "MALE"),
    )
    GEMINI_LANGUAGE_CODES = frozenset(
        {
            "af-ZA", "am-ET", "ar-001", "ar-EG", "az-AZ", "be-BY", "bg-BG",
            "bn-BD", "ca-ES", "ceb-PH", "cmn-CN", "cmn-TW", "cs-CZ", "da-DK",
            "de-DE", "el-GR", "en-AU", "en-GB", "en-IN", "en-US", "es-419",
            "es-ES", "es-MX", "et-EE", "eu-ES", "fa-IR", "fi-FI", "fil-PH",
            "fr-CA", "fr-FR", "gl-ES", "gu-IN", "he-IL", "hi-IN", "hr-HR",
            "ht-HT", "hu-HU", "hy-AM", "id-ID", "is-IS", "it-IT", "ja-JP",
            "jv-JV", "ka-GE", "kn-IN", "ko-KR", "kok-IN", "la-VA", "lb-LU",
            "lo-LA", "lt-LT", "lv-LV", "mai-IN", "mg-MG", "mk-MK", "ml-IN",
            "mn-MN", "mr-IN", "ms-MY", "my-MM", "nb-NO", "ne-NP", "nl-NL",
            "nn-NO", "or-IN", "pa-IN", "pl-PL", "ps-AF", "pt-BR", "pt-PT",
            "ro-RO", "ru-RU", "sd-IN", "si-LK", "sk-SK", "sl-SI", "sq-AL",
            "sr-RS", "sv-SE", "sw-KE", "ta-IN", "te-IN", "th-TH", "tr-TR",
            "uk-UA", "ur-PK", "vi-VN",
        }
    )

    def capabilities(self) -> ProviderCapabilities:
        available = self.dependency_available()
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=True,
            requires_credential=True,
            supports_voice_listing=available,
            supports_model_listing=available,
            supports_language_code=True,
            supports_ssml=True,
            supports_speed=True,
            supports_pitch=True,
            supports_volume=True,
            supports_streaming=False,
            supports_quota_lookup=False,
            supports_cancellation=False,
            supported_output_formats=self.output_formats,
            credential_fields=self.credential_fields,
            optional_dependency=self.dependency_name,
        )

    def _validate_access_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = super().validate_configuration(settings)
        if not base.ok:
            return base
        reference = self._option(settings, "credential_reference")
        if reference:
            path = Path(reference).expanduser()
            if not path.is_file():
                return ProviderConfigurationResult(
                    False,
                    "Google Cloud credential reference does not exist.",
                )
            if path.suffix.casefold() != ".json":
                return ProviderConfigurationResult(
                    False,
                    "Google Cloud credential reference must point to a JSON credential file.",
                )
        endpoint = self._option(settings, "api_endpoint")
        if endpoint and "://" in endpoint:
            return ProviderConfigurationResult(
                False,
                "Google Cloud API endpoint must be a hostname, not a URL.",
            )
        auth = "service-account reference" if reference else "Application Default Credentials"
        return ProviderConfigurationResult(
            True,
            f"Google Cloud TTS is configured for {auth}; live access is verified by catalog sync.",
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = self._validate_access_configuration(settings)
        if not base.ok:
            return base
        model = self._model_id(settings)
        voice_id = str(settings.voice_id or "").strip()
        gemini_voice_ids = {name.casefold() for name, _gender in self.GEMINI_VOICES}
        if model in self.GEMINI_MODELS:
            if not voice_id:
                return ProviderConfigurationResult(False, "Google Gemini-TTS voice is required.")
            if voice_id.casefold() not in gemini_voice_ids:
                return ProviderConfigurationResult(
                    False,
                    "Google Gemini-TTS requires one of the Gemini prebuilt voice names.",
                )
        elif voice_id.casefold() in gemini_voice_ids:
            return ProviderConfigurationResult(
                False,
                "Google Gemini-TTS prebuilt voices require an explicit Gemini-TTS model.",
            )
        if self._is_chirp3_voice(voice_id) and float(settings.speed) != 1.0:
            return ProviderConfigurationResult(
                False,
                "Google Chirp 3 HD voices do not support the speaking-rate parameter.",
            )
        if not 0.25 <= float(settings.speed) <= 2.0:
            return ProviderConfigurationResult(False, "Google Cloud speaking rate must be between 0.25 and 2.0.")
        return base

    def test_connection(self) -> ProviderConfigurationResult:
        validation = self._validate_access_configuration(self.settings)
        if not validation.ok:
            return validation
        voices = self.list_voices()
        return ProviderConfigurationResult(
            True,
            f"Google Cloud TTS connected; {len(voices)} voice(s) discovered.",
        )

    def list_voices(self) -> list[dict]:
        validation = self._validate_access_configuration(self.settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        client = None
        try:
            from google.cloud import texttospeech

            client = self._client(self.settings, texttospeech)
            language = self._language_code(self.settings)
            response = client.list_voices(language_code=language or "")
            voices: list[dict] = []
            for voice in response.voices:
                name = str(getattr(voice, "name", "") or "").strip()
                if not name:
                    continue
                language_codes = tuple(str(item) for item in (getattr(voice, "language_codes", ()) or ()) if item)
                gender = self._enum_label(getattr(voice, "ssml_gender", ""))
                natural_rate = str(getattr(voice, "natural_sample_rate_hertz", "") or "")
                voices.append(
                    {
                        "voice_id": name,
                        "name": name,
                        "language_codes": list(language_codes),
                        "locale": language_codes[0] if language_codes else None,
                        "category": self._voice_family(name),
                        "description": f"Google Cloud TTS · {self._voice_family(name)}",
                        "labels": {
                            "language": language_codes[0] if language_codes else "",
                            "gender": gender,
                            "natural_sample_rate_hertz": natural_rate,
                        },
                        "compatible_model_ids": [self.DEFAULT_MODEL],
                    }
                )
            locale = language or ""
            if locale in self.GEMINI_LANGUAGE_CODES:
                voices.extend(self._gemini_voice_items(locale))
            return voices
        except ConfigurationError:
            raise
        except Exception as exc:
            raise self._provider_error(exc, "google_voice_catalog_error") from exc
        finally:
            self._close_client(client)

    def list_models(self) -> list[dict]:
        return [
            {
                "model_id": self.DEFAULT_MODEL,
                "name": "Google Cloud voice-selected model (Chirp / Neural2 / WaveNet / Standard)",
                "languages": [],
                "can_do_text_to_speech": True,
            },
            *[
                {
                    "model_id": model,
                    "name": model,
                    "languages": [],
                    "can_do_text_to_speech": True,
                    "can_use_style": True,
                    "maximum_text_length": 4000,
                }
                for model in self.GEMINI_MODELS
            ],
        ]

    def list_languages(self) -> list[dict[str, str]]:
        locales = sorted(
            {
                str(code)
                for voice in self.list_voices()
                for code in (voice.get("language_codes") or [])
                if str(code).strip()
            },
            key=str.casefold,
        )
        return [{"language_code": locale, "name": locale} for locale in locales]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        self._validate_input_size(text, settings)
        client = None
        try:
            from google.cloud import texttospeech

            client = self._client(settings, texttospeech)
            stripped = text.lstrip()
            model = self._model_id(settings)
            is_gemini = model in self.GEMINI_MODELS
            is_chirp3 = self._is_chirp3_voice(str(settings.voice_id or ""))
            if stripped.startswith("<speak"):
                if is_gemini:
                    raise ConfigurationError(
                        "Google Gemini-TTS uses text/prompt input rather than SSML."
                    )
                if is_chirp3:
                    raise ConfigurationError(
                        "Google Chirp 3 HD voices do not support SSML input."
                    )
                synthesis_input = texttospeech.SynthesisInput(ssml=text)
            else:
                input_kwargs: dict[str, str] = {"text": text}
                prompt = self._option(settings, "prompt")
                if is_gemini and prompt:
                    input_kwargs["prompt"] = prompt
                synthesis_input = texttospeech.SynthesisInput(**input_kwargs)

            voice_kwargs: dict[str, str] = {
                "language_code": self._language_code(settings) or "en-US",
            }
            if str(settings.voice_id or "").strip():
                voice_kwargs["name"] = str(settings.voice_id).strip()
            if is_gemini:
                voice_kwargs["model_name"] = model
            voice = texttospeech.VoiceSelectionParams(**voice_kwargs)
            audio_kwargs: dict[str, object] = {
                "audio_encoding": self._audio_encoding(settings, texttospeech),
            }
            if not is_chirp3:
                audio_kwargs["speaking_rate"] = float(settings.speed)
            audio = texttospeech.AudioConfig(**audio_kwargs)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio,
            )
            payload = bytes(response.audio_content)
            if not payload:
                raise ProviderError(
                    "Google Cloud TTS returned empty audio.",
                    retryable=True,
                    provider_code="empty_audio",
                )
            return payload
        except (ConfigurationError, ProviderError):
            raise
        except Exception as exc:
            raise self._provider_error(exc, "google_synthesis_error") from exc
        finally:
            self._close_client(client)

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "google_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        message = str(error)
        token = f"{error.__class__.__name__} {message}".casefold()
        retryable = any(item in token for item in ("deadline", "timeout", "resourceexhausted", "unavailable", "429", "503"))
        code = "google_error"
        if any(item in token for item in ("unauthenticated", "permissiondenied", "credential", "forbidden")):
            code = "credential_or_permission"
            retryable = False
        elif any(item in token for item in ("resourceexhausted", "quota", "429")):
            code = "quota_or_rate_limit"
        elif any(item in token for item in ("deadline", "timeout")):
            code = "timeout"
        return ProviderNormalizedError(code, message, retryable=retryable, safe_details=message[:500])

    @classmethod
    def _client(cls, settings: AppSettings, texttospeech):
        reference = cls._option(settings, "credential_reference")
        endpoint = cls._option(settings, "api_endpoint")
        kwargs = {"client_options": {"api_endpoint": endpoint}} if endpoint else {}
        if reference:
            return texttospeech.TextToSpeechClient.from_service_account_file(
                str(Path(reference).expanduser()),
                **kwargs,
            )
        return texttospeech.TextToSpeechClient(**kwargs)

    @classmethod
    def _audio_encoding(cls, settings: AppSettings, texttospeech):
        simple = (settings.output_format or settings.file_extension.strip(".") or "mp3").split("_", 1)[0].casefold()
        names = {
            "mp3": "MP3",
            "wav": "LINEAR16",
            "linear16": "LINEAR16",
            "ogg": "OGG_OPUS",
            "opus": "OGG_OPUS",
            "ogg_opus": "OGG_OPUS",
        }
        name = names.get(simple)
        if not name:
            raise ConfigurationError(f"Unsupported Google Cloud TTS output format: {simple}.")
        try:
            return getattr(texttospeech.AudioEncoding, name)
        except AttributeError as exc:
            raise ConfigurationError(
                f"Installed Google Cloud TTS SDK does not support {simple} output."
            ) from exc

    @classmethod
    def _validate_input_size(cls, text: str, settings: AppSettings) -> None:
        text_bytes = len(text.encode("utf-8"))
        model = cls._model_id(settings)
        if model in cls.GEMINI_MODELS:
            prompt = cls._option(settings, "prompt")
            prompt_bytes = len(prompt.encode("utf-8"))
            if text_bytes > 4000 or prompt_bytes > 4000 or text_bytes + prompt_bytes > 8000:
                raise ConfigurationError(
                    "Google Gemini-TTS text and prompt exceed the synchronous request limit."
                )
        elif text_bytes > 5000:
            raise ConfigurationError(
                "Google Cloud TTS input exceeds the 5,000-byte synchronous request limit."
            )

    @classmethod
    def _model_id(cls, settings: AppSettings) -> str:
        value = str(settings.model_id or "").strip()
        return value if value in cls.GEMINI_MODELS else cls.DEFAULT_MODEL

    @classmethod
    def _language_code(cls, settings: AppSettings) -> str:
        value = str(settings.language_code or "").strip()
        common = {"da": "da-DK", "en": "en-US", "de": "de-DE", "sv": "sv-SE", "no": "nb-NO", "tr": "tr-TR"}
        return common.get(value.casefold(), value)

    @classmethod
    def _gemini_voice_items(cls, locale: str) -> list[dict]:
        return [
            {
                "voice_id": name,
                "name": f"{name} · Gemini-TTS",
                "language_codes": [locale],
                "locale": locale,
                "category": "gemini-tts",
                "description": "Google Gemini-TTS prebuilt voice",
                "labels": {"language": locale, "gender": gender},
                "compatible_model_ids": list(cls.GEMINI_MODELS),
            }
            for name, gender in cls.GEMINI_VOICES
        ]

    @staticmethod
    def _is_chirp3_voice(voice_id: str) -> bool:
        return "-chirp3-hd-" in str(voice_id or "").casefold()

    @staticmethod
    def _voice_family(name: str) -> str:
        lowered = name.casefold()
        if "chirp3-hd" in lowered:
            return "chirp3-hd"
        if "neural2" in lowered:
            return "neural2"
        if "wavenet" in lowered:
            return "wavenet"
        if "studio" in lowered:
            return "studio"
        if "journey" in lowered:
            return "journey"
        return "google-cloud"

    @staticmethod
    def _enum_label(value) -> str:
        name = getattr(value, "name", None)
        return str(name or value or "")

    @staticmethod
    def _close_client(client) -> None:
        if client is None:
            return
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    @staticmethod
    def _option(settings: AppSettings, key: str) -> str:
        value = settings.provider_options.get(key)
        return str(value or "").strip()

    @classmethod
    def _provider_error(cls, error: Exception, code: str) -> ProviderError:
        message = str(error)
        token = f"{error.__class__.__name__} {message}".casefold()
        retryable = any(item in token for item in ("deadline", "timeout", "resourceexhausted", "unavailable", "429", "503"))
        provider_code = code
        if any(item in token for item in ("unauthenticated", "permissiondenied", "credential", "forbidden")):
            provider_code = "credential_or_permission"
            retryable = False
        elif any(item in token for item in ("resourceexhausted", "quota", "429")):
            provider_code = "quota_or_rate_limit"
        elif any(item in token for item in ("deadline", "timeout")):
            provider_code = "timeout"
        return ProviderError(
            "Google Cloud TTS request failed.",
            retryable=retryable,
            provider_code=provider_code,
            technical_details=message[:500],
        )


class AmazonPollyProvider(OptionalSetupProvider):
    provider_id = "aws_polly"
    display_name = "Amazon Polly"
    dependency_name = "boto3"
    setup_hint = (
        "Amazon Polly requires boto3 and AWS credentials resolved by a named profile "
        "or the standard AWS credential chain."
    )
    credential_fields = ("aws_profile", "region")
    output_formats = ("mp3", "ogg_vorbis", "pcm")
    ENGINES = ("standard", "neural", "generative", "long-form")

    def capabilities(self) -> ProviderCapabilities:
        available = self.dependency_available()
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=True,
            requires_credential=True,
            supports_voice_listing=available,
            supports_model_listing=available,
            supports_language_code=True,
            supports_ssml=True,
            supports_speed=False,
            supports_pitch=False,
            supports_volume=False,
            supports_streaming=False,
            supports_quota_lookup=False,
            supports_cancellation=False,
            supported_output_formats=self.output_formats,
            credential_fields=self.credential_fields,
            optional_dependency=self.dependency_name,
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = super().validate_configuration(settings)
        if not base.ok:
            return base
        try:
            import boto3

            session = self._session(settings, boto3)
        except Exception as exc:
            return ProviderConfigurationResult(False, f"Amazon Polly AWS profile configuration failed: {exc}")
        if not str(getattr(session, "region_name", "") or "").strip():
            return ProviderConfigurationResult(
                False,
                "Amazon Polly requires an AWS region in the provider profile or resolved AWS configuration.",
            )
        return ProviderConfigurationResult(
            True,
            f"Amazon Polly SDK is configured for region {session.region_name}; live credentials are verified by catalog sync.",
        )

    def test_connection(self) -> ProviderConfigurationResult:
        validation = self.validate_configuration(self.settings)
        if not validation.ok:
            return validation
        voices = self.list_voices()
        return ProviderConfigurationResult(
            True,
            f"Amazon Polly connected; {len(voices)} voice(s) discovered.",
        )

    def list_voices(self) -> list[dict]:
        validation = self.validate_configuration(self.settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        try:
            import boto3

            client = self._client(self.settings, boto3)
            params: dict[str, object] = {"IncludeAdditionalLanguageCodes": True}
            language = self._language_code(self.settings)
            if language:
                params["LanguageCode"] = language
            voices: list[dict] = []
            while True:
                response = client.describe_voices(**params)
                for voice in response.get("Voices", []):
                    voice_id = str(voice.get("Id") or "").strip()
                    if not voice_id:
                        continue
                    engines = tuple(str(item) for item in (voice.get("SupportedEngines") or []) if item)
                    language_code = str(voice.get("LanguageCode") or "").strip()
                    additional = tuple(str(item) for item in (voice.get("AdditionalLanguageCodes") or []) if item)
                    voices.append(
                        {
                            "voice_id": voice_id,
                            "name": str(voice.get("Name") or voice_id),
                            "language_code": language_code or None,
                            "category": "amazon-polly",
                            "description": str(voice.get("Gender") or ""),
                            "labels": {
                                "language": language_code,
                                "gender": str(voice.get("Gender") or ""),
                                "additional_languages": ",".join(additional),
                            },
                            "compatible_model_ids": list(engines),
                        }
                    )
                token = response.get("NextToken")
                if not token:
                    break
                params["NextToken"] = token
            return voices
        except ConfigurationError:
            raise
        except Exception as exc:
            raise self._provider_error(exc, "aws_polly_voice_catalog_error") from exc

    def list_models(self) -> list[dict]:
        return [
            {
                "model_id": engine,
                "name": f"Amazon Polly {engine.title()} engine",
                "languages": [],
                "can_do_text_to_speech": True,
            }
            for engine in self.ENGINES
        ]

    def list_languages(self) -> list[dict[str, str]]:
        locales = sorted(
            {
                str(voice.get("language_code") or "")
                for voice in self.list_voices()
                if str(voice.get("language_code") or "").strip()
            },
            key=str.casefold,
        )
        return [{"language_code": locale, "name": locale} for locale in locales]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        if not str(settings.voice_id or "").strip():
            raise ConfigurationError("Amazon Polly voice is required.")
        self._validate_input_size(text)
        try:
            import boto3

            client = self._client(settings, boto3)
            output_format = self._output_format(settings)
            engine = self._engine(settings)
            if not engine:
                raise ConfigurationError(
                    "Select an Amazon Polly engine before synthesis; S-Talking will not choose one silently."
                )
            params: dict[str, object] = {
                "Text": text,
                "VoiceId": str(settings.voice_id).strip(),
                "OutputFormat": output_format,
                "Engine": engine,
                "TextType": "ssml" if text.lstrip().startswith("<speak") else "text",
            }
            language = self._language_code(settings)
            if language:
                params["LanguageCode"] = language
            sample_rate = self._option(settings, "sample_rate")
            if sample_rate:
                params["SampleRate"] = sample_rate
            response = client.synthesize_speech(**params)
            stream = response.get("AudioStream")
            if stream is None:
                raise ProviderError(
                    "Amazon Polly returned no audio stream.",
                    retryable=True,
                    provider_code="empty_audio",
                )
            try:
                payload = bytes(stream.read())
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            if not payload:
                raise ProviderError(
                    "Amazon Polly returned empty audio.",
                    retryable=True,
                    provider_code="empty_audio",
                )
            return payload
        except (ConfigurationError, ProviderError):
            raise
        except Exception as exc:
            raise self._provider_error(exc, "aws_polly_synthesis_error") from exc

    def normalize_error(self, error: Exception) -> ProviderNormalizedError:
        if isinstance(error, ProviderError):
            return ProviderNormalizedError(
                error.provider_code or "aws_polly_error",
                error.user_message,
                retryable=error.retryable,
                request_id=error.request_id,
                safe_details=error.technical_details or "",
            )
        provider_error = self._provider_error(error, "aws_polly_error")
        return ProviderNormalizedError(
            provider_error.provider_code or "aws_polly_error",
            provider_error.user_message,
            retryable=provider_error.retryable,
            safe_details=provider_error.technical_details or "",
        )

    @staticmethod
    def _validate_input_size(text: str) -> None:
        stripped = text.lstrip()
        if not stripped.startswith("<speak"):
            if len(text) > 3000:
                raise ConfigurationError(
                    "Amazon Polly synchronous plain-text input exceeds the 3,000 billed-character limit."
                )
            return
        if len(text) > 6000:
            raise ConfigurationError(
                "Amazon Polly synchronous SSML input exceeds the 6,000-character total request limit."
            )
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ConfigurationError(f"Amazon Polly SSML is not well formed: {exc}.") from exc
        billed = "".join(root.itertext())
        if len(billed) > 3000:
            raise ConfigurationError(
                "Amazon Polly synchronous SSML contains more than 3,000 billed text characters."
            )

    @classmethod
    def _session(cls, settings: AppSettings, boto3):
        kwargs: dict[str, str] = {}
        profile = cls._option(settings, "aws_profile")
        region = cls._option(settings, "region")
        if profile:
            kwargs["profile_name"] = profile
        if region:
            kwargs["region_name"] = region
        return boto3.Session(**kwargs)

    @classmethod
    def _client(cls, settings: AppSettings, boto3):
        session = cls._session(settings, boto3)
        region = cls._option(settings, "region") or str(getattr(session, "region_name", "") or "").strip()
        if not region:
            raise ConfigurationError("Amazon Polly AWS region could not be resolved.")
        return session.client("polly", region_name=region)

    @classmethod
    def _engine(cls, settings: AppSettings) -> str:
        model = str(settings.model_id or "").strip().casefold()
        if model in cls.ENGINES:
            return model
        configured = cls._option(settings, "engine").casefold()
        return configured if configured in cls.ENGINES else ""

    @classmethod
    def _output_format(cls, settings: AppSettings) -> str:
        simple = (settings.output_format or settings.file_extension.strip(".") or "mp3").split("_", 1)[0].casefold()
        mapping = {
            "mp3": "mp3",
            "ogg": "ogg_vorbis",
            "ogg_vorbis": "ogg_vorbis",
            "pcm": "pcm",
        }
        output = mapping.get(simple)
        if not output:
            raise ConfigurationError(f"Unsupported Amazon Polly output format: {simple}.")
        return output

    @classmethod
    def _language_code(cls, settings: AppSettings) -> str:
        value = str(settings.language_code or "").strip()
        common = {"da": "da-DK", "en": "en-US", "de": "de-DE", "sv": "sv-SE", "no": "nb-NO", "tr": "tr-TR"}
        return common.get(value.casefold(), value)

    @staticmethod
    def _option(settings: AppSettings, key: str) -> str:
        value = settings.provider_options.get(key)
        return str(value or "").strip()

    @classmethod
    def _provider_error(cls, error: Exception, code: str) -> ProviderError:
        message = str(error)
        response = getattr(error, "response", None)
        error_code = ""
        if isinstance(response, dict):
            details = response.get("Error")
            if isinstance(details, dict):
                error_code = str(details.get("Code") or "")
        token = f"{error_code} {error.__class__.__name__} {message}".casefold()
        retryable = any(
            item in token
            for item in (
                "throttl",
                "toomanyrequests",
                "serviceunavailable",
                "internalfailure",
                "requesttimeout",
                "timeout",
                "429",
                "500",
                "503",
            )
        )
        provider_code = code
        if any(item in token for item in ("unrecognizedclient", "invalidclienttoken", "accessdenied", "credential", "signature")):
            provider_code = "credential_or_permission"
            retryable = False
        elif "throttl" in token or "toomanyrequests" in token or "429" in token:
            provider_code = "quota_or_rate_limit"
        elif "timeout" in token:
            provider_code = "timeout"
        elif "engin" in token or "language" in token or "voice" in token:
            provider_code = "invalid_request"
            retryable = False
        return ProviderError(
            "Amazon Polly request failed.",
            retryable=retryable,
            provider_code=provider_code,
            technical_details=f"{error_code}: {message}"[:500],
        )


class KokoroLocalProvider(OptionalSetupProvider):
    provider_id = "kokoro"
    display_name = "Kokoro Local"
    dependency_name = "kokoro"
    setup_hint = "Kokoro requires kokoro>=0.9.4,<1 and a certified language/voice."
    remote = False
    credential_fields = ()
    output_formats = ("wav",)

    def __init__(
        self,
        settings: AppSettings,
        *,
        runtime: KokoroRuntimeService | None = None,
    ) -> None:
        super().__init__(settings)
        self.runtime = runtime or shared_kokoro_runtime_service()
        self._cancel_event = threading.Event()

    def capabilities(self) -> ProviderCapabilities:
        available = self.dependency_available()
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=False,
            requires_credential=False,
            supports_voice_listing=available,
            supports_model_listing=available,
            supports_language_code=True,
            supports_speed=True,
            supports_cancellation=True,
            supported_output_formats=self.output_formats,
            optional_dependency=self.dependency_name,
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        base = super().validate_configuration(settings)
        if not base.ok:
            return base
        issue = self.runtime.certification_issue(settings.language_code, settings.voice_id or None)
        if issue:
            return ProviderConfigurationResult(False, issue)
        if not settings.voice_id.strip():
            return ProviderConfigurationResult(
                False,
                "Select a certified Kokoro voice for the configured language.",
            )
        return ProviderConfigurationResult(
            True,
            "Kokoro runtime and language/voice certification are ready.",
        )

    def test_connection(self) -> ProviderConfigurationResult:
        validation = self.validate_configuration(self.settings)
        if not validation.ok:
            return validation
        return ProviderConfigurationResult(
            True,
            "Kokoro local runtime configuration is certified. Use explicit warm-up to load model assets.",
        )

    def list_voices(self) -> list[dict]:
        if not self.dependency_available():
            return []
        return [
            {
                "voice_id": voice.voice_id,
                "name": voice.display_name,
                "language_code": voice.language_code,
                "category": "kokoro-v1.0",
                "labels": {"language": voice.language_code, "runtime": "local"},
            }
            for voice in self.runtime.voices_for_language(self.settings.language_code)
        ]

    def list_models(self) -> list[dict]:
        if not self.dependency_available():
            return []
        if self.runtime.language_spec(self.settings.language_code) is None:
            return []
        return [
            {
                "model_id": self.runtime.MODEL_ID,
                "name": "Kokoro 82M v1.0",
                "category": "local-open-weight",
            }
        ]

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        validation = self.validate_configuration(settings)
        if not validation.ok:
            raise ConfigurationError(validation.message)
        self._cancel_event.clear()
        return self.runtime.synthesize(
            text,
            language_code=settings.language_code,
            voice_id=settings.voice_id,
            speed=settings.speed,
            timeout_seconds=settings.timeout_seconds,
            cancel_event=self._cancel_event,
        )

    def cancel(self) -> None:
        self._cancel_event.set()

    def close(self) -> None:
        self._cancel_event.set()
