from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.config.runtime import RuntimeConfig
from app.models.domain import AppSettings
from app.models.pronunciation_dictionary import PronunciationRule
from app.providers.elevenlabs import ElevenLabsProvider
from app.services.provider_verification_service import ProviderVerificationService
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem


class FakeResponse:
    def __init__(self, data=None, content: bytes = b"audio", headers=None) -> None:
        self._data = data if data is not None else {}
        self.content = content
        self.headers = headers or {}
        self.status_code = 200
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


def _provider(monkeypatch, calls, responses=None) -> ElevenLabsProvider:
    provider = ElevenLabsProvider(AppSettings(provider="elevenlabs", api_key="sk_SECRET", voice_id="voice", model_id="model"))

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if responses:
            response = responses.pop(0)
            return response
        return FakeResponse({"id": "dict", "name": "Danish", "latest_version_id": "v2", "latest_version_rules_num": 1})

    monkeypatch.setattr(provider, "_request", fake_request)
    return provider


def test_pronunciation_dictionary_endpoint_paths_and_payloads(monkeypatch) -> None:
    calls = []
    provider = _provider(monkeypatch, calls, [FakeResponse({"pronunciation_dictionaries": [], "has_more": False})])
    provider.list_pronunciation_dictionaries()
    assert calls[-1][0:2] == ("GET", "/v1/pronunciation-dictionaries")
    assert calls[-1][2]["params"]["include_archived"] is False

    alias = PronunciationRule("mad", "maat", "alias", "da", case_sensitive=True)
    phoneme = PronunciationRule("tak", "tɑk", "phoneme", "da", alphabet="ipa")
    provider.create_pronunciation_dictionary_from_rules(name="Danish", rules=[alias, phoneme])
    payload = calls[-1][2]["json"]
    assert calls[-1][0:2] == ("POST", "/v1/pronunciation-dictionaries/add-from-rules")
    assert payload["rules"][0] == {
        "type": "alias",
        "string_to_replace": "mad",
        "alias": "maat",
        "case_sensitive": True,
        "word_boundaries": True,
    }
    assert payload["rules"][1]["type"] == "phoneme"
    assert payload["rules"][1]["phoneme"] == "tɑk"
    assert payload["rules"][1]["alphabet"] == "ipa"


def test_rule_crud_and_archive_use_documented_endpoints(monkeypatch) -> None:
    calls = []
    provider = _provider(monkeypatch, calls)
    rule = PronunciationRule("en ø", "en oe")

    provider.add_pronunciation_dictionary_rules("dict", [rule])
    provider.set_pronunciation_dictionary_rules("dict", [rule])
    provider.remove_pronunciation_dictionary_rules("dict", ["en ø"])
    provider.delete_pronunciation_dictionary("dict")

    assert [call[1] for call in calls] == [
        "/v1/pronunciation-dictionaries/dict/add-rules",
        "/v1/pronunciation-dictionaries/dict/set-rules",
        "/v1/pronunciation-dictionaries/dict/remove-rules",
        "/v1/pronunciation-dictionaries/dict",
    ]
    assert calls[-1][0] == "PATCH"
    assert calls[-1][2]["json"] == {"archived": True}


def test_tts_payload_matches_preview_and_batch_with_locators(monkeypatch) -> None:
    calls = []
    provider = _provider(
        monkeypatch,
        calls,
        [
            FakeResponse(content=b"preview", headers={"request-id": "req-1"}),
            FakeResponse(content=b"batch", headers={"request-id": "req-2"}),
        ],
    )
    settings = AppSettings(
        provider="elevenlabs",
        api_key="sk_SECRET",
        voice_id="voice",
        model_id="eleven_v3",
        language_code="da",
        pronunciation_dictionary_locators=[{"pronunciation_dictionary_id": "dict", "version_id": "v1"}],
    )

    preview = provider.synthesize_with_metadata("mad", settings)
    batch = provider.synthesize("mad", settings)

    assert preview["request_id"] == "req-1"
    assert batch == b"batch"
    assert calls[0][2]["json"] == calls[1][2]["json"]
    assert calls[0][2]["json"]["language_code"] == "da"
    assert calls[0][2]["json"]["pronunciation_dictionary_locators"] == [
        {"pronunciation_dictionary_id": "dict", "version_id": "v1"}
    ]


def test_dictionary_service_remote_sync_and_stale_version(tmp_path: Path) -> None:
    service = PronunciationDictionaryService(tmp_path / "dicts")
    dictionary = service.create("Danish", rules=[PronunciationRule("mad", "maat")], version_id="v1")

    class Provider:
        def create_pronunciation_dictionary_from_rules(self, *, name, rules):
            return {"dictionary_id": "remote-dict", "name": name, "version_id": "v2", "rule_count": len(rules)}

        def get_pronunciation_dictionary(self, dictionary_id):
            return {"dictionary_id": dictionary_id, "name": "Danish", "version_id": "v3"}

    synced = service.sync_remote(Provider(), dictionary, model_id="eleven_v3")
    ok, message = service.verify_remote_version(Provider(), synced.dictionary_id, synced.version_id)

    assert synced.dictionary_id == "remote-dict"
    assert synced.version_id == "v2"
    assert service.load("remote-dict").source == "Stale"
    assert ok is False
    assert "v3" in message


def test_provider_verification_report_is_redacted(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()

    class VoiceServiceFake:
        def __init__(self) -> None:
            self.invalidated = 0

        def invalidate_provider_cache(self, _settings=None) -> None:
            self.invalidated += 1

        def refresh_catalog(self, _settings) -> VoiceCatalog:
            return VoiceCatalog(
                voices=(VoiceItem("elevenlabs", "voice", "Danish Voice", "da", None, "", {}, False),),
                models=(VoiceModelItem("eleven_v3", "Eleven v3", ("da",), True),),
                account=AccountUsage("creator", "active", 10, 1000),
                refreshed_at="now",
            )

    class ProviderFake:
        def list_pronunciation_dictionaries(self):
            return []

        def create_pronunciation_dictionary_from_rules(self, **_kwargs):
            return {}

        def create_pronunciation_dictionary_from_file(self, *_args, **_kwargs):
            return {}

        def add_pronunciation_dictionary_rules(self, *_args):
            return {}

        def set_pronunciation_dictionary_rules(self, *_args):
            return {}

        def remove_pronunciation_dictionary_rules(self, *_args):
            return {}

        def delete_pronunciation_dictionary(self, *_args):
            return None

        def download_pronunciation_dictionary_version(self, *_args):
            return b""

        def synthesize_with_metadata(self, _text, _settings):
            return {"audio": b"audio", "request_id": "req-123", "character_cost": "5"}

        def close(self):
            return None

    service = ProviderVerificationService(runtime, VoiceServiceFake(), provider_factory=lambda _settings: ProviderFake())
    report = service.run_elevenlabs(
        AppSettings(provider="elevenlabs", api_key="sk_SUPERSECRET", voice_id="voice", model_id="eleven_v3"),
        profile_name="Production",
        sample_text="mad tak en ø et år kat",
        project_name="Danish Lessons",
    )

    payload = report.json_path.read_text(encoding="utf-8")
    assert report.success is True
    assert "sk_SUPERSECRET" not in payload
    assert "req-123" in payload
    assert "Danish Lessons" not in str(report.report_dir.name)


@pytest.mark.skipif(
    os.environ.get("S_TALKING_RUN_LIVE_ELEVENLABS_TESTS") != "1",
    reason="Live ElevenLabs verification requires explicit opt-in and real credentials.",
)
def test_live_elevenlabs_verification_is_opt_in() -> None:
    assert os.environ.get("ELEVENLABS_API_KEY")
