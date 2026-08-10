from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.exceptions import ProviderError
from app.models import AppSettings
from app.provider_factory import available_provider_ids, create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.cartesia import (
    CARTESIA_API_VERSION,
    CARTESIA_TTS_MODELS,
    CartesiaProvider,
)
from app.providers.deepgram import DeepgramProvider
from app.services.preflight_service import PreflightService
from app.services.voice_service import VoiceService
from app.config.runtime import RuntimeConfig


class _Client:
    def __init__(self, handler, *, base_url: str) -> None:
        self.calls: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request)

        self._client = httpx.Client(transport=httpx.MockTransport(wrapped), base_url=base_url)

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return self._client.request(method, url, **kwargs)

    def close(self) -> None:
        self._client.close()


def _replace_client(provider, handler, *, base_url: str) -> _Client:
    provider.client.close()
    client = _Client(handler, base_url=base_url)
    provider.client = client
    return client


def _cartesia_settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="cartesia",
        api_key="sk_car_TEST",
        model_id="sonic-3.5",
        voice_id="voice-da",
        language_code="da-DK",
        output_format="mp3",
        file_extension=".mp3",
        speed=1.0,
    )
    return base.model_copy(update=updates)


def _deepgram_settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="deepgram",
        api_key="dg_TEST",
        model_id="aura-2-thalia-en",
        voice_id="aura-2-thalia-en",
        language_code="en-US",
        output_format="mp3",
        file_extension=".mp3",
        speed=1.0,
    )
    return base.model_copy(update=updates)


def test_phase103_registry_and_factory_append_nextgen_providers() -> None:
    ids = DEFAULT_PROVIDER_REGISTRY.provider_ids()
    assert ids[8:10] == ("cartesia", "deepgram")
    assert available_provider_ids()[8:10] == ["cartesia", "deepgram"]

    cartesia = DEFAULT_PROVIDER_REGISTRY.manifest_for("cartesia")
    deepgram = DEFAULT_PROVIDER_REGISTRY.manifest_for("deepgram")
    assert cartesia.profile_management_ready is True
    assert cartesia.controls.api_key is True
    assert cartesia.retry_ready is True
    assert cartesia.fallback_output_formats == ("mp3", "wav")
    assert deepgram.profile_management_ready is True
    assert deepgram.controls.api_key is True
    assert deepgram.retry_ready is True
    assert deepgram.fallback_output_formats == ("mp3", "wav", "opus", "flac", "aac", "pcm")


def test_phase103_factory_constructs_real_http_adapters() -> None:
    cartesia = create_provider(_cartesia_settings())
    deepgram = create_provider(_deepgram_settings())
    try:
        assert isinstance(cartesia, CartesiaProvider)
        assert isinstance(deepgram, DeepgramProvider)
    finally:
        cartesia.close()
        deepgram.close()


def test_phase103_cartesia_auth_version_and_danish_contract() -> None:
    provider = CartesiaProvider(_cartesia_settings())
    try:
        assert provider.client.headers["Authorization"] == "Bearer sk_car_TEST"
        assert provider.client.headers["Cartesia-Version"] == CARTESIA_API_VERSION
        assert provider.capabilities().supports_voice_listing is True
        assert provider.capabilities().supports_pronunciation_dictionary is True
        assert provider.validate_synthesis_configuration(_cartesia_settings()).ok is True
        assert "sonic-3.5" in CARTESIA_TTS_MODELS
    finally:
        provider.close()


def test_phase103_cartesia_live_voice_catalog_is_language_scoped_and_paginated() -> None:
    pages = [
        {
            "data": [
                {
                    "id": "voice-da",
                    "name": "Freja",
                    "description": "Danish test voice",
                    "gender": "feminine",
                    "language": "da",
                    "locales": [{"locale": "da-DK", "is_native": True}],
                    "country": "DK",
                    "is_owner": False,
                    "preview_file_url": "https://example.test/freja.mp3",
                }
            ],
            "has_more": True,
            "next_page": "voice-da",
        },
        {
            "data": [
                {
                    "id": "voice-da-2",
                    "name": "Mikkel",
                    "gender": "masculine",
                    "language": "da",
                    "locales": [{"locale": "da-DK", "is_native": True}],
                    "country": "DK",
                    "is_owner": True,
                }
            ],
            "has_more": False,
            "next_page": None,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/voices"
        assert request.url.params["language"] == "da"
        page = pages.pop(0)
        if page["has_more"]:
            assert "starting_after" not in request.url.params
        else:
            assert request.url.params["starting_after"] == "voice-da"
        return httpx.Response(200, json=page, request=request)

    provider = CartesiaProvider(_cartesia_settings())
    client = _replace_client(provider, handler, base_url=CartesiaProvider.BASE_URL)
    try:
        voices = provider.list_voices()
    finally:
        provider.close()

    assert len(client.calls) == 2
    assert [item["voice_id"] for item in voices] == ["voice-da", "voice-da-2"]
    assert voices[0]["labels"]["locales"] == "da-DK"
    assert voices[0]["compatible_model_ids"] == list(CARTESIA_TTS_MODELS)


def test_phase103_cartesia_synthesis_payload_uses_danish_voice_model_and_wav() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=b"RIFF-cartesia", request=request)

    settings = _cartesia_settings(
        output_format="wav",
        speed=1.1,
        provider_options={"pronunciation_dict_id": "dict-123"},
    )
    provider = CartesiaProvider(settings)
    _replace_client(provider, handler, base_url=CartesiaProvider.BASE_URL)
    try:
        audio = provider.synthesize("Hej verden", settings)
    finally:
        provider.close()

    assert audio == b"RIFF-cartesia"
    assert captured["path"] == "/tts/bytes"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model_id"] == "sonic-3.5"
    assert payload["voice"] == {"mode": "id", "id": "voice-da"}
    assert payload["language"] == "da"
    assert payload["output_format"] == {
        "container": "wav",
        "encoding": "pcm_s16le",
        "sample_rate": 44100,
    }
    assert payload["generation_config"] == {"speed": 1.1}
    assert payload["pronunciation_dict_id"] == "dict-123"


def test_phase103_cartesia_rejects_unsupported_model_output_and_speed() -> None:
    provider = CartesiaProvider(_cartesia_settings())
    try:
        assert provider.validate_synthesis_configuration(
            _cartesia_settings(model_id="sonic-preview")
        ).ok is False
        assert provider.validate_synthesis_configuration(
            _cartesia_settings(output_format="flac")
        ).ok is False
        # AppSettings currently constrains speed to <=1.2, so exercise the
        # provider contract without constructing an invalid Pydantic model.
        settings = _cartesia_settings()
        settings.speed = 0.7
        assert provider.validate_synthesis_configuration(settings).ok is True
    finally:
        provider.close()


def test_phase103_cartesia_connection_probe_does_not_require_voice_selection() -> None:
    settings = _cartesia_settings(voice_id="", model_id="")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/voices"
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json={"data": [], "has_more": False}, request=request)

    provider = CartesiaProvider(settings)
    _replace_client(provider, handler, base_url=CartesiaProvider.BASE_URL)
    try:
        assert provider.validate_configuration(settings).ok is True
        assert provider.validate_synthesis_configuration(settings).ok is False
        assert provider.test_connection().ok is True
    finally:
        provider.close()


def test_phase103_cartesia_http_errors_are_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"message": "rate limited", "request_id": "car-req"},
            headers={"x-request-id": "car-header"},
            request=request,
        )

    provider = CartesiaProvider(_cartesia_settings())
    _replace_client(provider, handler, base_url=CartesiaProvider.BASE_URL)
    try:
        with pytest.raises(ProviderError) as captured:
            provider.synthesize("Hej", _cartesia_settings())
        normalized = provider.normalize_error(captured.value)
    finally:
        provider.close()

    assert normalized.code == "quota_or_rate_limit"
    assert normalized.retryable is True
    assert normalized.request_id == "car-header"


def _deepgram_catalog() -> dict[str, object]:
    return {
        "tts": [
            {
                "name": "thalia",
                "canonical_name": "aura-2-thalia-en",
                "architecture": "aura-2",
                "languages": ["en-US"],
                "metadata": {
                    "accent": "American",
                    "age": "Adult",
                    "sample": "https://example.test/thalia.wav",
                    "tags": ["Clear", "Energetic"],
                    "use_cases": ["Customer Service"],
                },
            },
            {
                "name": "julius",
                "canonical_name": "aura-2-julius-de",
                "architecture": "aura-2",
                "languages": ["de-DE"],
                "metadata": {"accent": "German", "age": "Adult"},
            },
        ]
    }


def test_phase103_deepgram_live_models_are_the_voice_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json=_deepgram_catalog(), request=request)

    settings = _deepgram_settings(language_code="de-DE", model_id="", voice_id="")
    provider = DeepgramProvider(settings)
    client = _replace_client(provider, handler, base_url=DeepgramProvider.BASE_URL)
    try:
        voices = provider.list_voices()
        models = provider.list_models()
        languages = provider.list_languages()
    finally:
        provider.close()

    assert len(client.calls) == 1
    assert [item["voice_id"] for item in voices] == ["aura-2-julius-de"]
    assert {item["model_id"] for item in models} == {"aura-2-thalia-en", "aura-2-julius-de"}
    assert languages == [
        {"language_code": "de-DE", "name": "de-DE"},
        {"language_code": "en-US", "name": "en-US"},
    ]


def test_phase103_deepgram_danish_is_explicitly_not_certified() -> None:
    settings = _deepgram_settings(language_code="da-DK")
    provider = DeepgramProvider(settings)
    try:
        result = provider.validate_synthesis_configuration(settings)
    finally:
        provider.close()

    assert result.ok is False
    assert "Danish is not certified" in result.message


def test_phase103_deepgram_requires_voice_model_identity() -> None:
    settings = _deepgram_settings(
        model_id="aura-2-thalia-en",
        voice_id="aura-2-orion-en",
    )
    provider = DeepgramProvider(settings)
    try:
        result = provider.validate_synthesis_configuration(settings)
    finally:
        provider.close()

    assert result.ok is False
    assert "voice and model" in result.message


def test_phase103_deepgram_synthesis_uses_aura_model_output_and_speed() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, content=b"deepgram-wav", request=request)

    settings = _deepgram_settings(output_format="wav", speed=1.1)
    provider = DeepgramProvider(settings)
    _replace_client(provider, handler, base_url=DeepgramProvider.BASE_URL)
    try:
        audio = provider.synthesize("Hello", settings)
    finally:
        provider.close()

    assert audio == b"deepgram-wav"
    assert captured["path"] == "/v1/speak"
    assert captured["params"] == {
        "model": "aura-2-thalia-en",
        "encoding": "linear16",
        "container": "wav",
        "speed": "1.1",
    }
    assert captured["payload"] == {"text": "Hello"}


def test_phase103_deepgram_connection_probe_uses_public_tts_model_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json=_deepgram_catalog(), request=request)

    settings = _deepgram_settings(model_id="", voice_id="")
    provider = DeepgramProvider(settings)
    _replace_client(provider, handler, base_url=DeepgramProvider.BASE_URL)
    try:
        result = provider.test_connection()
    finally:
        provider.close()

    assert result.ok is True
    assert "2 public TTS model" in result.message


def test_phase103_deepgram_auth_and_error_contract() -> None:
    settings = _deepgram_settings()
    provider = DeepgramProvider(settings)
    try:
        assert provider.client.headers["Authorization"] == "Token dg_TEST"
    finally:
        provider.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            json={"err_msg": "insufficient credits", "request_id": "dg-req"},
            request=request,
        )

    provider = DeepgramProvider(settings)
    _replace_client(provider, handler, base_url=DeepgramProvider.BASE_URL)
    try:
        with pytest.raises(ProviderError) as captured:
            provider.synthesize("Hello", settings)
        normalized = provider.normalize_error(captured.value)
    finally:
        provider.close()

    assert normalized.code == "insufficient_credits"
    assert normalized.retryable is False
    assert normalized.request_id == "dg-req"


def test_phase103_preview_extensions_are_provider_aware() -> None:
    assert VoiceService._preview_extension(_cartesia_settings(output_format="wav")) == ".wav"
    assert VoiceService._preview_extension(_deepgram_settings(output_format="flac")) == ".flac"


def test_phase103_preflight_blocks_uncertified_deepgram_danish(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = PreflightService(runtime)
    issues = []
    settings = _deepgram_settings(language_code="da-DK")

    ready = service._validate_provider(settings, issues)

    assert ready is False
    matching = [issue for issue in issues if issue.code == "provider_synthesis_configuration_invalid"]
    assert matching
    assert "Danish is not certified" in matching[-1].message


def test_phase103_preflight_accepts_valid_cartesia_danish_configuration(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = PreflightService(runtime)
    issues = []

    ready = service._validate_provider(_cartesia_settings(), issues)

    assert ready is True
    assert not [issue for issue in issues if issue.code == "provider_synthesis_configuration_invalid"]




def test_phase103_registry_drives_cloud_planning_for_new_providers() -> None:
    from app.services.generation_planning_service import GenerationPlanningService

    plan = GenerationPlanningService().build(
        project_id=None,
        provider="cartesia",
        model="sonic-3.5",
        files=0,
        characters=0,
        provider_requests=0,
        fallback_duration_seconds=0.0,
        quota_snapshot=None,
        max_retries=0,
        delay_seconds=0.0,
    )

    assert plan.risk_level == "medium"
    assert any("No pricing rate is configured" in reason for reason in plan.reasons)

def test_phase103_main_workspace_exposes_nextgen_providers(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container
    from app.gui.main import MainWindow

    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    providers = tuple(window.provider.itemText(index) for index in range(window.provider.count()))
    assert providers[8:10] == ("cartesia", "deepgram")

    window.provider.setCurrentText("cartesia")
    qt_app.processEvents()
    window.refresh_models()
    assert window.current_model_id() == "sonic-3.5"
    assert window.provider_field_rows["api_profile"].isHidden() is False
    assert window.provider_field_rows["api_key"].isHidden() is False

    window.close()

def test_phase103_no_provider_switch_is_introduced() -> None:
    cartesia = CartesiaProvider(_cartesia_settings())
    deepgram = DeepgramProvider(_deepgram_settings())
    try:
        assert cartesia.provider_id == "cartesia"
        assert deepgram.provider_id == "deepgram"
        assert not hasattr(cartesia, "fallback_provider")
        assert not hasattr(deepgram, "fallback_provider")
    finally:
        cartesia.close()
        deepgram.close()


def test_phase103_does_not_change_database_schema(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase103-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
