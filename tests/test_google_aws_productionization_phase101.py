from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.exceptions import ConfigurationError
from app.models import AppSettings
from app.models.api_profile import ApiProfile, ApiProfileStatus
from app.models.provider_health import ProviderHealthState, evaluate_provider_health
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.optional_adapters import AmazonPollyProvider, GoogleCloudTTSProvider
from app.services.api_profile_service import ApiProfileService
from app.services.secure_credentials import SecureCredentialStore
from app.services.voice_service import VoiceService


def _install_google_sdk(monkeypatch, sdk) -> None:
    import sys

    google = ModuleType("google")
    google.__path__ = []
    cloud = ModuleType("google.cloud")
    cloud.__path__ = []
    setattr(cloud, "texttospeech", sdk)
    setattr(google, "cloud", cloud)
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.texttospeech", sdk)


def _install_boto3(monkeypatch, sdk) -> None:
    import sys

    module = ModuleType("boto3")
    for name in dir(sdk):
        if not name.startswith("__"):
            setattr(module, name, getattr(sdk, name))
    monkeypatch.setitem(sys.modules, "boto3", module)


def test_phase101_registry_promotes_google_and_aws_profiles() -> None:
    google = DEFAULT_PROVIDER_REGISTRY.manifest_for("google")
    aws = DEFAULT_PROVIDER_REGISTRY.manifest_for("aws_polly")

    assert google.profile_management_ready is True
    assert google.profile_secret_required is False
    assert google.retry_ready is True
    assert google.profile_metadata_fields == (
        "credential_reference",
        "project_id",
        "api_endpoint",
    )
    assert google.controls.api_profile is True
    assert google.controls.voice_browser_fallback is True
    assert google.controls.model_listing_fallback is True

    assert aws.profile_management_ready is True
    assert aws.profile_secret_required is False
    assert aws.retry_ready is True
    assert aws.profile_metadata_fields == ("aws_profile", "region")
    assert aws.controls.api_profile is True


def test_phase101_external_credential_profiles_are_usable_without_saved_key() -> None:
    google = ApiProfile(
        profile_id="google-profile",
        display_name="Google ADC",
        provider="google",
        active=True,
        status=ApiProfileStatus.READY,
    )
    aws = ApiProfile(
        profile_id="aws-profile",
        display_name="AWS default",
        provider="aws_polly",
        active=True,
        status=ApiProfileStatus.READY,
        metadata={"region": "eu-west-1"},
    )
    openai = ApiProfile(
        profile_id="openai-profile",
        display_name="OpenAI",
        provider="openai",
        active=True,
        status=ApiProfileStatus.READY,
    )

    assert google.credential_ready is True
    assert google.is_usable is True
    assert google.masked_key == "External credentials"
    assert evaluate_provider_health(google).state == ProviderHealthState.HEALTHY

    assert aws.credential_ready is True
    assert aws.is_usable is True
    assert evaluate_provider_health(aws).state == ProviderHealthState.HEALTHY

    assert openai.credential_ready is False
    assert openai.is_usable is False
    assert evaluate_provider_health(openai).state == ProviderHealthState.OFFLINE


def test_phase101_profile_service_applies_only_google_aws_safe_metadata(tmp_path: Path) -> None:
    service = ApiProfileService(
        tmp_path / "profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    google = service.create_profile(
        "Google production",
        provider="google",
        active=True,
        metadata={
            "credential_reference": "C:/credentials/google.json",
            "project_id": "tts-project",
            "api_endpoint": "europe-west4-texttospeech.googleapis.com",
            "last_sync_result": "connected",
        },
    )
    aws = service.create_profile(
        "AWS production",
        provider="aws_polly",
        active=True,
        metadata={
            "aws_profile": "tts-production",
            "region": "eu-west-1",
            "last_sync_result": "connected",
        },
    )

    google_settings = service.apply_profile(
        AppSettings(provider="google", active_api_profile_id=google.profile_id),
        google.profile_id,
    )
    aws_settings = service.apply_profile(
        AppSettings(provider="aws_polly", active_api_profile_id=aws.profile_id),
        aws.profile_id,
    )

    assert google_settings.api_key == ""
    assert google_settings.provider_options == {
        "credential_reference": "C:/credentials/google.json",
        "project_id": "tts-project",
        "api_endpoint": "europe-west4-texttospeech.googleapis.com",
    }
    assert aws_settings.api_key == ""
    assert aws_settings.provider_options == {
        "aws_profile": "tts-production",
        "region": "eu-west-1",
    }
    persisted = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "last_sync_result" in persisted
    assert "api_key" not in persisted.casefold()


def test_phase101_external_profiles_participate_in_same_provider_failover_planning(tmp_path: Path) -> None:
    service = ApiProfileService(
        tmp_path / "profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )
    primary = service.create_profile(
        "Google primary",
        provider="google",
        active=True,
        priority=1,
    )
    backup = service.create_profile(
        "Google backup",
        provider="google",
        active=False,
        priority=2,
    )
    primary.status = ApiProfileStatus.READY
    backup.status = ApiProfileStatus.READY
    service.update_profile(primary)
    service.update_profile(backup)

    decision = service.choose_failover(
        provider="google",
        current_profile_id=primary.profile_id,
        mode="auto",
        error_code="insufficient_quota",
    )

    assert decision.should_switch is True
    assert decision.target_profile_id == backup.profile_id
    assert service.get_profile(backup.profile_id).has_saved_key is False
    assert service.get_profile(backup.profile_id).credential_ready is True


def test_phase101_google_validation_accepts_adc_and_rejects_bad_reference(monkeypatch, tmp_path: Path) -> None:
    provider = GoogleCloudTTSProvider(AppSettings(provider="google"))
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    assert provider.validate_configuration(provider.settings).ok is True

    missing = provider.settings.model_copy(
        update={"provider_options": {"credential_reference": str(tmp_path / "missing.json")}}
    )
    assert provider.validate_configuration(missing).ok is False

    wrong = tmp_path / "credentials.txt"
    wrong.write_text("not a credential", encoding="utf-8")
    wrong_settings = provider.settings.model_copy(
        update={"provider_options": {"credential_reference": str(wrong)}}
    )
    assert provider.validate_configuration(wrong_settings).ok is False

    credential = tmp_path / "service-account.json"
    credential.write_text("{}", encoding="utf-8")
    configured = provider.settings.model_copy(
        update={
            "provider_options": {
                "credential_reference": str(credential),
                "api_endpoint": "europe-west4-texttospeech.googleapis.com",
            }
        }
    )
    assert provider.validate_configuration(configured).ok is True


def test_phase101_google_client_uses_adc_or_service_account_reference(tmp_path: Path) -> None:
    calls: list[tuple[str, object]] = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(("adc", kwargs))

        @classmethod
        def from_service_account_file(cls, filename, **kwargs):
            calls.append(("file", (filename, kwargs)))
            return cls.__new__(cls)

    sdk = SimpleNamespace(TextToSpeechClient=Client)
    GoogleCloudTTSProvider._client(AppSettings(provider="google"), sdk)

    path = tmp_path / "google.json"
    path.write_text("{}", encoding="utf-8")
    GoogleCloudTTSProvider._client(
        AppSettings(
            provider="google",
            provider_options={
                "credential_reference": str(path),
                "api_endpoint": "europe-west4-texttospeech.googleapis.com",
            },
        ),
        sdk,
    )

    assert calls[0] == ("adc", {})
    assert calls[1][0] == "file"
    filename, kwargs = calls[1][1]
    assert filename == str(path)
    assert kwargs == {
        "client_options": {"api_endpoint": "europe-west4-texttospeech.googleapis.com"}
    }


def test_phase101_google_models_cover_default_and_current_gemini_families() -> None:
    provider = GoogleCloudTTSProvider(AppSettings(provider="google"))
    models = provider.list_models()
    ids = tuple(item["model_id"] for item in models)

    assert ids[0] == GoogleCloudTTSProvider.DEFAULT_MODEL
    assert ids[1:] == GoogleCloudTTSProvider.GEMINI_MODELS
    assert "gemini-3.1-flash-tts-preview" in ids
    assert "gemini-2.5-pro-tts" in ids


def test_phase101_google_voice_catalog_normalizes_language_gender_and_family(monkeypatch) -> None:
    provider = GoogleCloudTTSProvider(
        AppSettings(provider="google", language_code="da")
    )
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    voice = SimpleNamespace(
        name="da-DK-Chirp3-HD-Aoede",
        language_codes=("da-DK",),
        ssml_gender=SimpleNamespace(name="FEMALE"),
        natural_sample_rate_hertz=24000,
    )

    class Client:
        def list_voices(self, *, language_code):
            assert language_code == "da-DK"
            return SimpleNamespace(voices=(voice,))

        def close(self):
            pass

    monkeypatch.setattr(provider, "_client", lambda _settings, _sdk: Client())
    _install_google_sdk(monkeypatch, SimpleNamespace())

    voices = provider.list_voices()
    classic = voices[0]
    assert classic == {
        "voice_id": "da-DK-Chirp3-HD-Aoede",
        "name": "da-DK-Chirp3-HD-Aoede",
        "language_codes": ["da-DK"],
        "locale": "da-DK",
        "category": "chirp3-hd",
        "description": "Google Cloud TTS · chirp3-hd",
        "labels": {
            "language": "da-DK",
            "gender": "FEMALE",
            "natural_sample_rate_hertz": "24000",
        },
        "compatible_model_ids": [GoogleCloudTTSProvider.DEFAULT_MODEL],
    }
    gemini = next(item for item in voices if item["voice_id"] == "Kore")
    assert gemini["locale"] == "da-DK"
    assert gemini["category"] == "gemini-tts"
    assert gemini["labels"]["gender"] == "FEMALE"
    assert tuple(gemini["compatible_model_ids"]) == GoogleCloudTTSProvider.GEMINI_MODELS
    assert len(voices) == 1 + len(GoogleCloudTTSProvider.GEMINI_VOICES)


def test_phase101_google_catalog_sync_does_not_require_current_model_voice_pair(monkeypatch) -> None:
    settings = AppSettings(
        provider="google",
        model_id="gemini-2.5-flash-tts",
        voice_id="stale-non-gemini-voice",
        language_code="da-DK",
    )
    provider = GoogleCloudTTSProvider(settings)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    class Client:
        def list_voices(self, *, language_code):
            assert language_code == "da-DK"
            return SimpleNamespace(voices=())

        def close(self):
            pass

    monkeypatch.setattr(provider, "_client", lambda _settings, _sdk: Client())
    _install_google_sdk(monkeypatch, SimpleNamespace())

    voices = provider.list_voices()
    assert any(item["voice_id"] == "Kore" for item in voices)
    assert provider.validate_configuration(settings).ok is False


def test_phase101_google_rejects_incompatible_gemini_voice_and_chirp_rate(monkeypatch) -> None:
    gemini = AppSettings(
        provider="google",
        model_id="gemini-2.5-flash-tts",
        voice_id="da-DK-Chirp3-HD-Kore",
        language_code="da-DK",
    )
    provider = GoogleCloudTTSProvider(gemini)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)
    assert provider.validate_configuration(gemini).ok is False

    chirp = AppSettings(
        provider="google",
        model_id=GoogleCloudTTSProvider.DEFAULT_MODEL,
        voice_id="da-DK-Chirp3-HD-Kore",
        language_code="da-DK",
        speed=1.1,
    )
    assert provider.validate_configuration(chirp).ok is False


def test_phase101_google_gemini_payload_uses_model_prompt_and_mp3(monkeypatch) -> None:
    captured: dict[str, object] = {}
    settings = AppSettings(
        provider="google",
        voice_id="Kore",
        model_id="gemini-2.5-flash-tts",
        language_code="da-DK",
        output_format="mp3",
        speed=1.1,
        provider_options={"prompt": "Speak naturally in Danish."},
    )
    provider = GoogleCloudTTSProvider(settings)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    class SynthesisInput:
        def __init__(self, **kwargs):
            captured["input"] = kwargs

    class VoiceSelectionParams:
        def __init__(self, **kwargs):
            captured["voice"] = kwargs

    class AudioConfig:
        def __init__(self, **kwargs):
            captured["audio"] = kwargs

    class Client:
        def synthesize_speech(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(audio_content=b"google-audio")

        def close(self):
            captured["closed"] = True

    sdk = SimpleNamespace(
        SynthesisInput=SynthesisInput,
        VoiceSelectionParams=VoiceSelectionParams,
        AudioConfig=AudioConfig,
        AudioEncoding=SimpleNamespace(MP3="mp3-enum"),
    )
    monkeypatch.setattr(provider, "_client", lambda _settings, _sdk: Client())
    _install_google_sdk(monkeypatch, sdk)

    assert provider.synthesize("Hej verden", settings) == b"google-audio"
    assert captured["input"] == {
        "text": "Hej verden",
        "prompt": "Speak naturally in Danish.",
    }
    assert captured["voice"] == {
        "language_code": "da-DK",
        "name": "Kore",
        "model_name": "gemini-2.5-flash-tts",
    }
    assert captured["audio"] == {
        "audio_encoding": "mp3-enum",
        "speaking_rate": 1.1,
    }
    assert captured["closed"] is True


def test_phase101_google_input_limits_and_error_normalization() -> None:
    classic = AppSettings(provider="google", model_id=GoogleCloudTTSProvider.DEFAULT_MODEL)
    with pytest.raises(ConfigurationError):
        GoogleCloudTTSProvider._validate_input_size("ø" * 2501, classic)

    gemini = classic.model_copy(
        update={
            "model_id": "gemini-2.5-flash-tts",
            "provider_options": {"prompt": "x" * 4001},
        }
    )
    with pytest.raises(ConfigurationError):
        GoogleCloudTTSProvider._validate_input_size("Hej", gemini)

    provider = GoogleCloudTTSProvider(classic)
    normalized = provider.normalize_error(RuntimeError("429 ResourceExhausted quota"))
    assert normalized.code == "quota_or_rate_limit"
    assert normalized.retryable is True


def test_phase101_aws_session_uses_named_profile_and_region() -> None:
    calls: list[dict[str, str]] = []

    class Session:
        def __init__(self, **kwargs):
            calls.append(dict(kwargs))
            self.region_name = kwargs.get("region_name")

    sdk = SimpleNamespace(Session=Session)
    settings = AppSettings(
        provider="aws_polly",
        provider_options={"aws_profile": "tts-prod", "region": "eu-west-1"},
    )
    session = AmazonPollyProvider._session(settings, sdk)

    assert calls == [{"profile_name": "tts-prod", "region_name": "eu-west-1"}]
    assert session.region_name == "eu-west-1"


def test_phase101_aws_validation_requires_resolved_region(monkeypatch) -> None:
    provider = AmazonPollyProvider(AppSettings(provider="aws_polly"))
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    class Session:
        def __init__(self, *, region_name=None, **_kwargs):
            self.region_name = region_name

    sdk = SimpleNamespace(Session=Session)
    _install_boto3(monkeypatch, sdk)

    assert provider.validate_configuration(provider.settings).ok is False
    configured = provider.settings.model_copy(
        update={"provider_options": {"region": "eu-west-1"}}
    )
    result = provider.validate_configuration(configured)
    assert result.ok is True
    assert "eu-west-1" in result.message


def test_phase101_aws_voice_catalog_paginates_and_preserves_supported_engines(monkeypatch) -> None:
    settings = AppSettings(
        provider="aws_polly",
        language_code="da",
        provider_options={"region": "eu-west-1"},
    )
    provider = AmazonPollyProvider(settings)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    calls: list[dict[str, object]] = []

    class Client:
        def describe_voices(self, **kwargs):
            calls.append(dict(kwargs))
            if "NextToken" not in kwargs:
                return {
                    "Voices": [
                        {
                            "Id": "Naja",
                            "Name": "Naja",
                            "LanguageCode": "da-DK",
                            "Gender": "Female",
                            "SupportedEngines": ["standard"],
                        }
                    ],
                    "NextToken": "next",
                }
            return {
                "Voices": [
                    {
                        "Id": "Sofie",
                        "Name": "Sofie",
                        "LanguageCode": "da-DK",
                        "Gender": "Female",
                        "SupportedEngines": ["neural"],
                    }
                ]
            }

    monkeypatch.setattr(provider, "_client", lambda _settings, _boto: Client())

    class Session:
        def __init__(self, *, region_name=None, **_kwargs):
            self.region_name = region_name

    _install_boto3(monkeypatch, SimpleNamespace(Session=Session))

    voices = provider.list_voices()
    assert [voice["voice_id"] for voice in voices] == ["Naja", "Sofie"]
    assert voices[0]["compatible_model_ids"] == ["standard"]
    assert voices[1]["compatible_model_ids"] == ["neural"]
    assert calls[0]["LanguageCode"] == "da-DK"
    assert calls[0]["IncludeAdditionalLanguageCodes"] is True
    assert calls[1]["NextToken"] == "next"


def test_phase101_aws_models_expose_current_engine_families() -> None:
    provider = AmazonPollyProvider(AppSettings(provider="aws_polly"))
    assert tuple(item["model_id"] for item in provider.list_models()) == (
        "standard",
        "neural",
        "generative",
        "long-form",
    )


def test_phase101_aws_synthesis_requires_explicit_engine(monkeypatch) -> None:
    settings = AppSettings(
        provider="aws_polly",
        voice_id="Sofie",
        model_id="",
        provider_options={"region": "eu-west-1"},
    )
    provider = AmazonPollyProvider(settings)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    class Session:
        region_name = "eu-west-1"

    _install_boto3(monkeypatch, SimpleNamespace(Session=lambda **_kwargs: Session()))
    monkeypatch.setattr(provider, "_client", lambda _settings, _boto: SimpleNamespace())

    with pytest.raises(ConfigurationError, match="will not choose one silently"):
        provider.synthesize("Hej verden", settings)


def test_phase101_aws_synthesis_uses_selected_engine_danish_and_closes_stream(monkeypatch) -> None:
    captured: dict[str, object] = {}
    settings = AppSettings(
        provider="aws_polly",
        voice_id="Sofie",
        model_id="neural",
        language_code="da",
        output_format="mp3",
        provider_options={"region": "eu-west-1"},
    )
    provider = AmazonPollyProvider(settings)
    monkeypatch.setattr(provider, "dependency_available", lambda: True)

    class Stream(BytesIO):
        def close(self):
            captured["stream_closed"] = True
            super().close()

    class Client:
        def synthesize_speech(self, **kwargs):
            captured["params"] = kwargs
            return {"AudioStream": Stream(b"polly-audio")}

    monkeypatch.setattr(provider, "_client", lambda _settings, _boto: Client())

    class Session:
        def __init__(self, *, region_name=None, **_kwargs):
            self.region_name = region_name

    _install_boto3(monkeypatch, SimpleNamespace(Session=Session))

    assert provider.synthesize("Hej verden", settings) == b"polly-audio"
    assert captured["params"] == {
        "Text": "Hej verden",
        "VoiceId": "Sofie",
        "OutputFormat": "mp3",
        "Engine": "neural",
        "TextType": "text",
        "LanguageCode": "da-DK",
    }
    assert captured["stream_closed"] is True


def test_phase101_aws_synchronous_input_limits_plain_text_and_ssml() -> None:
    AmazonPollyProvider._validate_input_size("x" * 3000)
    with pytest.raises(ConfigurationError, match="3,000 billed-character"):
        AmazonPollyProvider._validate_input_size("x" * 3001)

    AmazonPollyProvider._validate_input_size("<speak>" + ("x" * 3000) + "</speak>")
    with pytest.raises(ConfigurationError, match="3,000 billed text"):
        AmazonPollyProvider._validate_input_size("<speak>" + ("x" * 3001) + "</speak>")
    with pytest.raises(ConfigurationError, match="not well formed"):
        AmazonPollyProvider._validate_input_size("<speak>broken")


def test_phase101_aws_error_normalization_distinguishes_throttle_and_credentials() -> None:
    provider = AmazonPollyProvider(AppSettings(provider="aws_polly"))

    class AwsError(RuntimeError):
        def __init__(self, code: str):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    throttled = provider.normalize_error(AwsError("ThrottlingException"))
    denied = provider.normalize_error(AwsError("AccessDeniedException"))

    assert throttled.code == "quota_or_rate_limit"
    assert throttled.retryable is True
    assert denied.code == "credential_or_permission"
    assert denied.retryable is False


def test_phase101_preview_extensions_follow_google_and_aws_output_formats() -> None:
    assert VoiceService._preview_extension(
        AppSettings(provider="google", output_format="wav", file_extension=".mp3")
    ) == ".wav"
    assert VoiceService._preview_extension(
        AppSettings(provider="google", output_format="ogg_opus", file_extension=".mp3")
    ) == ".ogg"
    assert VoiceService._preview_extension(
        AppSettings(provider="aws_polly", output_format="pcm", file_extension=".mp3")
    ) == ".pcm"


def test_phase101_does_not_change_database_schema(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase101-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
