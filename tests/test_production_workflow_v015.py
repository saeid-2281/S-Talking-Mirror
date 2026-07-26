from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.models import AppSettings, JobStatus, TTSJob
from app.models.pronunciation_dictionary import PronunciationRule
from app.models.preflight_state import PreflightState
from app.providers.elevenlabs import ElevenLabsProvider
from app.services.api_profile_service import ApiProfileService
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_scope_service import GenerationScopeService
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService
from app.services.pronunciation_service import PronunciationService
from app.services.secure_credentials import SecureCredentialStore


def jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, filename="b.mp3", text="Hej"),
        TTSJob(row_number=2, filename="a.mp3", text="Dette er en lidt længere linje"),
        TTSJob(row_number=3, filename="c.mp3", text="Kort"),
    ]


def test_danish_pronunciation_no_longer_wraps_spoken_text() -> None:
    settings = AppSettings(provider="elevenlabs", language_code="da", short_text_pronunciation_aid=True)
    result = PronunciationService().prepare("mad", settings)

    assert result.provider_text == "mad"
    assert result.original_text == "mad"
    assert result.aid_applied is False
    assert result.strategy == "language_code_da"


def test_elevenlabs_payload_includes_language_and_dictionary_locator(monkeypatch) -> None:
    captured: dict[str, object] = {}
    provider = ElevenLabsProvider(
        AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model")
    )

    def fake_request(method: str, url: str, **kwargs):
        captured.update(kwargs.get("json", {}))
        return httpx.Response(200, content=b"audio")

    monkeypatch.setattr(provider, "_request", fake_request)
    settings = AppSettings(
        provider="elevenlabs",
        api_key="sk_TEST",
        voice_id="voice",
        model_id="model",
        language_code="da",
        pronunciation_dictionary_locators=[{"pronunciation_dictionary_id": "dict", "version_id": "v1"}],
    )

    assert provider.synthesize("Hej", settings) == b"audio"
    assert captured["text"] == "Hej"
    assert captured["language_code"] == "da"
    assert captured["pronunciation_dictionary_locators"] == [
        {"pronunciation_dictionary_id": "dict", "version_id": "v1"}
    ]


def test_api_profile_metadata_does_not_store_raw_key(tmp_path: Path) -> None:
    service = ApiProfileService(
        tmp_path / "profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )

    profile = service.create_profile("Production", api_key="sk_SECRET", active=True)
    payload = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))

    assert "sk_SECRET" not in json.dumps(payload)
    assert service.api_key_for(profile.profile_id) == "sk_SECRET"
    assert service.active_profile("elevenlabs").profile_id == profile.profile_id


def test_api_profile_failover_decision_requires_eligible_error(tmp_path: Path) -> None:
    service = ApiProfileService(tmp_path / "profiles.json", SecureCredentialStore(tmp_path / "credentials"))
    first = service.create_profile("Primary", api_key="sk_ONE", active=True)
    backup = service.create_profile("Backup", api_key="sk_TWO")

    assert service.choose_failover(
        provider="elevenlabs",
        current_profile_id=first.profile_id,
        mode="auto",
        error_code="network_failure",
    ).should_switch is False
    decision = service.choose_failover(
        provider="elevenlabs",
        current_profile_id=first.profile_id,
        mode="auto",
        error_code="insufficient_quota",
    )
    assert decision.should_switch is True
    assert decision.target_profile_id == backup.profile_id


def test_generation_scope_ordering_and_character_counts() -> None:
    plan = GenerationScopeService().build_plan(
        jobs(),
        scope_mode="entire_queue",
        execution_order="character_shortest",
    )

    assert [job.filename for job in plan.jobs] == ["b.mp3", "c.mp3", "a.mp3"]
    assert plan.total_characters == sum(len(job.text) for job in jobs())


def test_generation_scope_selected_rows_and_row_range() -> None:
    service = GenerationScopeService()
    selected = service.build_plan(jobs(), scope_mode="selected", selected_rows={1, 3})
    row_range = service.build_plan(jobs(), scope_mode="row_range", row_range=(2, 3))

    assert [job.row_number for job in selected.jobs] == [1, 3]
    assert [job.row_number for job in row_range.jobs] == [2, 3]


def test_quota_batch_reserves_two_percent_or_500() -> None:
    local_jobs = jobs()
    local_jobs[0].status = JobStatus.COMPLETED
    preview = GenerationScopeService().quota_batch(local_jobs, quota_remaining=550)

    assert preview.reserved_characters == 500
    assert preview.required_characters <= 50
    assert all(job.status == JobStatus.PENDING for job in preview.jobs)


def test_pronunciation_dictionary_import_and_locator(tmp_path: Path) -> None:
    pls = tmp_path / "da.pls"
    pls.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<lexicon version="1.0" xml:lang="da" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon">
  <lexeme><grapheme>AI</grapheme><alias>kunstig intelligens</alias></lexeme>
</lexicon>
""",
        encoding="utf-8",
    )
    service = PronunciationDictionaryService(tmp_path / "dicts")
    dictionary = service.import_pls(pls, version_id="v1")

    assert dictionary.rules == [PronunciationRule("AI", "kunstig intelligens", "alias", "da")]
    assert service.locators_for([dictionary.dictionary_id]) == [
        {"pronunciation_dictionary_id": dictionary.dictionary_id, "version_id": "v1"}
    ]


def test_generation_confirmation_coordinator_single_warning_prompt() -> None:
    state = PreflightState(total_jobs=1, valid_jobs=1, warnings=1, issues=[])
    state.blocking_errors = 0
    confirmation = GenerationConfirmationCoordinator().evaluate(state, AppSettings(provider="mock"))

    assert confirmation.allowed is True
    assert confirmation.requires_user_confirmation is True
    assert confirmation.title == "Preflight warnings"
