from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest

from app.config.runtime import RuntimeConfig
from app.exceptions import ProviderError
from app.models import AppSettings
from app.provider_factory import available_provider_ids, create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.providers.murf import MURF_MODEL_ID, MurfProvider
from app.providers.resemble import (
    RESEMBLE_MODEL_ID,
    ResembleProvider,
)
from app.services.preflight_service import PreflightService
from app.services.voice_service import VoiceService


class _Client:
    def __init__(self, handler, *, base_url: str | None = None) -> None:
        self.calls: list[httpx.Request] = []

        def wrapped(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return handler(request)

        kwargs = {"transport": httpx.MockTransport(wrapped)}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = httpx.Client(**kwargs)

    @property
    def headers(self):
        return self._client.headers

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        return self._client.request(method, url, **kwargs)

    def close(self) -> None:
        self._client.close()


def _replace_client(provider, handler, *, base_url: str | None = None) -> _Client:
    provider.client.close()
    client = _Client(handler, base_url=base_url)
    # Preserve production auth headers in the test client.
    for key, value in provider.client.headers.items():
        if key.casefold() in {"authorization", "api-key", "content-type"}:
            client._client.headers[key] = value
    provider.client = client
    return client


def _resemble_settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="resemble",
        api_key="res_TEST",
        model_id=RESEMBLE_MODEL_ID,
        voice_id="voice-res-da",
        language_code="da-DK",
        output_format="wav",
        file_extension=".wav",
        speed=1.0,
    )
    return base.model_copy(update=updates)


def _murf_settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="murf",
        api_key="murf_TEST",
        model_id=MURF_MODEL_ID,
        voice_id="Natalie",
        language_code="en-US",
        output_format="mp3",
        file_extension=".mp3",
        speed=1.0,
    )
    return base.model_copy(update=updates)


def test_phase104_registry_and_factory_append_extended_cloud_providers() -> None:
    ids = DEFAULT_PROVIDER_REGISTRY.provider_ids()
    assert ids[-2:] == ("resemble", "murf")
    assert available_provider_ids()[-2:] == ["resemble", "murf"]

    resemble = DEFAULT_PROVIDER_REGISTRY.manifest_for("resemble")
    murf = DEFAULT_PROVIDER_REGISTRY.manifest_for("murf")
    assert resemble.profile_management_ready is True
    assert resemble.controls.api_key is True
    assert resemble.retry_ready is True
    assert resemble.fallback_output_formats == ("wav", "mp3")
    assert murf.profile_management_ready is True
    assert murf.controls.api_key is True
    assert murf.retry_ready is True
    assert murf.fallback_output_formats == ("mp3", "wav", "flac", "ogg", "pcm")


def test_phase104_factory_constructs_resemble_and_murf() -> None:
    resemble = create_provider(_resemble_settings())
    murf = create_provider(_murf_settings())
    try:
        assert isinstance(resemble, ResembleProvider)
        assert isinstance(murf, MurfProvider)
    finally:
        resemble.close()
        murf.close()


def test_phase104_resemble_auth_danish_and_voice_managed_model_contract() -> None:
    provider = ResembleProvider(_resemble_settings())
    try:
        assert provider.client.headers["Authorization"] == "Bearer res_TEST"
        assert provider.capabilities().supports_ssml is True
        assert provider.validate_synthesis_configuration(_resemble_settings()).ok is True
        models = provider.list_models()
        assert models[0]["model_id"] == RESEMBLE_MODEL_ID
        assert "da-dk" in models[0]["languages"]
    finally:
        provider.close()


def test_phase104_resemble_voice_catalog_is_paginated_and_tolerant_of_metadata_shapes() -> None:
    pages = [
        {
            "success": True,
            "page": 1,
            "num_pages": 2,
            "items": [
                {
                    "uuid": "voice-res-da",
                    "name": "Freja",
                    "status": "ready",
                    "supported_languages": ["da-dk", "en-us"],
                }
            ],
        },
        {
            "success": True,
            "page": 2,
            "num_pages": 2,
            "items": [
                {
                    "voice_uuid": "voice-res-en",
                    "display_name": "Alex",
                    "languages": [{"locale": "en-us"}],
                    "sample_url": "https://example.test/alex.wav",
                }
            ],
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "app.resemble.ai"
        assert request.url.path == "/api/v2/voices"
        assert request.url.params["advanced"] == "true"
        assert request.url.params["page_size"] == "100"
        page = int(request.url.params["page"])
        return httpx.Response(200, json=pages[page - 1], request=request)

    provider = ResembleProvider(_resemble_settings())
    _replace_client(provider, handler)
    try:
        voices = provider.list_voices()
    finally:
        provider.close()

    assert [item["voice_id"] for item in voices] == ["voice-res-da", "voice-res-en"]
    assert voices[0]["language"] == "da-dk"
    assert voices[0]["compatible_model_ids"] == []
    assert voices[1]["preview_url"] == "https://example.test/alex.wav"


def test_phase104_resemble_synthesis_uses_sync_base64_and_danish_ssml() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["host"] = request.url.host
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "success": True,
                "audio_content": base64.b64encode(b"RIFF-resemble").decode("ascii"),
                "output_format": "wav",
            },
            request=request,
        )

    settings = _resemble_settings(
        provider_options={
            "precision": "PCM_16",
            "use_hd": True,
            "apply_custom_pronunciations": True,
        }
    )
    provider = ResembleProvider(settings)
    _replace_client(provider, handler)
    try:
        audio = provider.synthesize("Hej & velkommen", settings)
    finally:
        provider.close()

    assert audio == b"RIFF-resemble"
    assert captured["host"] == "f.cluster.resemble.ai"
    assert captured["path"] == "/synthesize"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["voice_uuid"] == "voice-res-da"
    assert payload["output_format"] == "wav"
    assert payload["precision"] == "PCM_16"
    assert payload["use_hd"] is True
    assert payload["apply_custom_pronunciations"] is True
    assert "model" not in payload
    assert 'xml:lang="da-dk"' in payload["data"]
    assert "Hej &amp; velkommen" in payload["data"]


def test_phase104_resemble_rejects_stale_model_output_speed_and_precision() -> None:
    provider = ResembleProvider(_resemble_settings())
    try:
        assert provider.validate_synthesis_configuration(
            _resemble_settings(model_id="legacy-model")
        ).ok is False
        assert provider.validate_synthesis_configuration(
            _resemble_settings(output_format="flac")
        ).ok is False
        assert provider.validate_synthesis_configuration(
            _resemble_settings(speed=1.1)
        ).ok is False
        assert provider.validate_synthesis_configuration(
            _resemble_settings(provider_options={"precision": "FLOAT32"})
        ).ok is False
    finally:
        provider.close()


def test_phase104_resemble_connection_probe_does_not_require_voice_selection() -> None:
    settings = _resemble_settings(voice_id="", model_id="")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/voices"
        assert request.url.params["page"] == "1"
        return httpx.Response(
            200,
            json={"success": True, "page": 1, "num_pages": 1, "items": []},
            request=request,
        )

    provider = ResembleProvider(settings)
    _replace_client(provider, handler)
    try:
        assert provider.validate_configuration(settings).ok is True
        assert provider.validate_synthesis_configuration(settings).ok is False
        assert provider.test_connection().ok is True
    finally:
        provider.close()


def test_phase104_resemble_http_errors_are_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"message": "rate limited", "request_id": "res-req"},
            headers={"x-request-id": "res-header"},
            request=request,
        )

    provider = ResembleProvider(_resemble_settings())
    _replace_client(provider, handler)
    try:
        with pytest.raises(ProviderError) as captured:
            provider.synthesize("Hej", _resemble_settings())
        normalized = provider.normalize_error(captured.value)
    finally:
        provider.close()

    assert normalized.code == "quota_or_rate_limit"
    assert normalized.retryable is True
    assert normalized.request_id == "res-header"


def _murf_catalog() -> list[dict[str, object]]:
    return [
        {
            "description": "Adult",
            "displayName": "Natalie (F)",
            "gender": "Female",
            "locale": "en-US",
            "supportedLocales": {
                "en-US": {
                    "availableStyles": ["Conversational", "Promo"],
                    "detail": "English (US)",
                },
                "de-DE": {
                    "availableStyles": ["Promo"],
                    "detail": "German",
                },
            },
            "voiceId": "Natalie",
        },
        {
            "description": "Adult",
            "displayName": "Ken (M)",
            "gender": "Male",
            "locale": "en-US",
            "supportedLocales": {
                "en-US": {"availableStyles": ["Conversational"], "detail": "English"},
            },
            "voiceId": "Ken",
        },
    ]


def test_phase104_murf_auth_and_live_gen2_voice_catalog() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/speech/voices"
        assert request.url.params["model"] == "gen2"
        assert request.headers["api-key"] == "murf_TEST"
        return httpx.Response(200, json=_murf_catalog(), request=request)

    provider = MurfProvider(_murf_settings())
    _replace_client(provider, handler, base_url=MurfProvider.BASE_URL)
    try:
        voices = provider.list_voices()
        models = provider.list_models()
    finally:
        provider.close()

    assert [item["voice_id"] for item in voices] == ["Natalie", "Ken"]
    assert voices[0]["language"] == "en-US"
    assert voices[0]["labels"]["styles"] == "Conversational,Promo"
    assert voices[0]["compatible_model_ids"] == [MURF_MODEL_ID]
    assert models[0]["model_id"] == MURF_MODEL_ID
    assert "de-DE" in models[0]["languages"]


def test_phase104_murf_synthesis_uses_zero_retention_base64_gen2_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "encodedAudio": base64.b64encode(b"murf-mp3").decode("ascii"),
                "remainingCharacterCount": 999,
            },
            request=request,
        )

    settings = _murf_settings(
        speed=1.1,
        provider_options={
            "sample_rate": 44100,
            "pitch": 5,
            "variation": 2,
            "style": "Conversational",
        },
    )
    provider = MurfProvider(settings)
    _replace_client(provider, handler, base_url=MurfProvider.BASE_URL)
    try:
        audio = provider.synthesize("Hello", settings)
    finally:
        provider.close()

    assert audio == b"murf-mp3"
    assert captured["path"] == "/v1/speech/generate"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["voiceId"] == "Natalie"
    assert payload["format"] == "MP3"
    assert payload["modelVersion"] == "GEN2"
    assert payload["sampleRate"] == 44100
    assert payload["channelType"] == "MONO"
    assert payload["encodeAsBase64"] is True
    assert payload["locale"] == "en-US"
    assert payload["rate"] == 10
    assert payload["pitch"] == 5
    assert payload["variation"] == 2
    assert payload["style"] == "Conversational"


def test_phase104_murf_danish_remains_explicitly_uncertified() -> None:
    settings = _murf_settings(language_code="da-DK")
    provider = MurfProvider(settings)
    try:
        result = provider.validate_synthesis_configuration(settings)
    finally:
        provider.close()

    assert result.ok is False
    assert "Danish is not currently certified" in result.message


def test_phase104_murf_rejects_wrong_model_sample_rate_and_variation() -> None:
    provider = MurfProvider(_murf_settings())
    try:
        assert provider.validate_synthesis_configuration(
            _murf_settings(model_id="FALCON2")
        ).ok is False
        assert provider.validate_synthesis_configuration(
            _murf_settings(provider_options={"sample_rate": 22050})
        ).ok is False
        assert provider.validate_synthesis_configuration(
            _murf_settings(provider_options={"variation": 6})
        ).ok is False
    finally:
        provider.close()


def test_phase104_murf_connection_probe_does_not_require_voice_selection() -> None:
    settings = _murf_settings(voice_id="", model_id="")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_murf_catalog(), request=request)

    provider = MurfProvider(settings)
    _replace_client(provider, handler, base_url=MurfProvider.BASE_URL)
    try:
        assert provider.validate_configuration(settings).ok is True
        assert provider.validate_synthesis_configuration(settings).ok is False
        result = provider.test_connection()
    finally:
        provider.close()

    assert result.ok is True
    assert "2 Gen2 voice(s)" in result.message


def test_phase104_murf_credit_and_auth_errors_are_normalized() -> None:
    responses = [402, 403]
    provider = MurfProvider(_murf_settings())

    def handler(request: httpx.Request) -> httpx.Response:
        status = responses.pop(0)
        return httpx.Response(status, json={"message": "blocked"}, request=request)

    _replace_client(provider, handler, base_url=MurfProvider.BASE_URL)
    try:
        with pytest.raises(ProviderError) as credit:
            provider.synthesize("Hello", _murf_settings())
        with pytest.raises(ProviderError) as auth:
            provider.synthesize("Hello", _murf_settings())
        credit_normalized = provider.normalize_error(credit.value)
        auth_normalized = provider.normalize_error(auth.value)
    finally:
        provider.close()

    assert credit_normalized.code == "insufficient_credits"
    assert credit_normalized.retryable is False
    assert auth_normalized.code == "invalid_api_key"
    assert auth_normalized.retryable is False


def test_phase104_preview_output_mapping_covers_resemble_and_murf() -> None:
    assert VoiceService._preview_extension(_resemble_settings(output_format="mp3")) == ".mp3"
    assert VoiceService._preview_extension(_murf_settings(output_format="flac")) == ".flac"


def test_phase104_preflight_accepts_resemble_danish_and_blocks_murf_danish(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = PreflightService(runtime)

    resemble_issues = []
    resemble_ready = service._validate_provider(_resemble_settings(), resemble_issues)
    assert resemble_ready is True
    assert not [
        issue
        for issue in resemble_issues
        if issue.code == "provider_synthesis_configuration_invalid"
    ]

    murf_issues = []
    murf_ready = service._validate_provider(
        _murf_settings(language_code="da-DK"),
        murf_issues,
    )
    assert murf_ready is False
    matching = [
        issue
        for issue in murf_issues
        if issue.code == "provider_synthesis_configuration_invalid"
    ]
    assert matching
    assert "Danish is not currently certified" in matching[-1].message


def test_phase104_registry_drives_cloud_planning_for_extended_providers() -> None:
    from app.services.generation_planning_service import GenerationPlanningService

    plan = GenerationPlanningService().build(
        project_id=None,
        provider="resemble",
        model=RESEMBLE_MODEL_ID,
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


def test_phase104_main_workspace_exposes_extended_cloud_providers(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container
    from app.gui.main import MainWindow

    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    qt_app.processEvents()

    providers = tuple(window.provider.itemText(index) for index in range(window.provider.count()))
    assert providers[-2:] == ("resemble", "murf")

    window.provider.setCurrentText("resemble")
    qt_app.processEvents()
    window.refresh_models()
    assert window.current_model_id() == RESEMBLE_MODEL_ID
    assert window.provider_field_rows["api_profile"].isHidden() is False
    assert window.provider_field_rows["api_key"].isHidden() is False

    window.provider.setCurrentText("murf")
    qt_app.processEvents()
    window.refresh_models()
    assert window.current_model_id() == MURF_MODEL_ID

    window.close()


def test_phase104_no_provider_switch_is_introduced() -> None:
    resemble = ResembleProvider(_resemble_settings())
    murf = MurfProvider(_murf_settings())
    try:
        assert not hasattr(resemble, "fallback_provider")
        assert not hasattr(murf, "fallback_provider")
    finally:
        resemble.close()
        murf.close()


def test_phase104_does_not_change_database_schema(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase104-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
