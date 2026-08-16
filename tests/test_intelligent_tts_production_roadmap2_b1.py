from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from app.services.intelligent_tts_production_service import (
    IntelligentTTSProductionService,
    MANIFEST_SCHEMA_VERSION,
)
from scripts.certify_intelligent_tts_production_roadmap2_b1 import (
    CERTIFICATION_VERSION,
    EXPECTED_BASELINE_COMMIT,
    certify,
)


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _settings(**updates):
    values = {
        "provider": "elevenlabs",
        "active_api_profile_id": "profile-1",
        "voice_id": "voice-1",
        "model_id": "model-1",
        "language_code": "da",
        "file_extension": ".mp3",
        "max_retries": 4,
        "generation_scope": "entire_queue",
        "execution_order": "csv",
        "api_key": "SECRET-KEY",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _service() -> IntelligentTTSProductionService:
    return IntelligentTTSProductionService()


def test_b1_locks_to_a121_certified_baseline() -> None:
    assert EXPECTED_BASELINE_COMMIT == "c41a7e4f28865cf1640173c4c10a29adc5659839"
    assert CERTIFICATION_VERSION == "roadmap2-b1-v1"
    assert MANIFEST_SCHEMA_VERSION == 1


def test_b1_preserves_input_queue_order(tmp_path: Path) -> None:
    jobs = [
        _Job(7, "seven.mp3", "Syv"),
        _Job(2, "two.mp3", "To"),
        _Job(9, "nine.mp3", "Ni"),
    ]
    manifest = _service().compile_manifest(jobs, _settings(), tmp_path)
    assert [item.row_number for item in manifest.requests] == [7, 2, 9]
    assert [item.ordinal for item in manifest.requests] == [1, 2, 3]


def test_b1_uses_only_explicit_job_language_overrides(tmp_path: Path) -> None:
    jobs = [
        _Job(1, "a.mp3", "English words do not imply English."),
        _Job(2, "b.mp3", "Danske ord."),
    ]
    manifest = _service().compile_manifest(
        jobs,
        _settings(language_code="da"),
        tmp_path,
        job_language_overrides={2: "en"},
    )
    assert manifest.requests[0].language_code == "da"
    assert manifest.requests[0].language_source == "settings"
    assert manifest.requests[1].language_code == "en"
    assert manifest.requests[1].language_source == "explicit_job_override"


def test_b1_never_changes_provider_profile_voice_or_model(tmp_path: Path) -> None:
    manifest = _service().compile_manifest(
        [_Job(1, "a.mp3", "A"), _Job(2, "b.mp3", "B")],
        _settings(
            provider="openai",
            active_api_profile_id="chosen-profile",
            voice_id="alloy",
            model_id="gpt-4o-mini-tts",
        ),
        tmp_path,
    )
    for request in manifest.requests:
        assert request.provider == "openai"
        assert request.profile_id == "chosen-profile"
        assert request.voice_id == "alloy"
        assert request.model_id == "gpt-4o-mini-tts"


def test_b1_records_same_provider_retry_without_failover(tmp_path: Path) -> None:
    manifest = _service().compile_manifest(
        [_Job(1, "a.mp3", "Hej")], _settings(max_retries=6), tmp_path
    )
    request = manifest.requests[0]
    assert request.same_provider_retry_limit == 6
    assert request.cross_provider_failover == "disabled"
    assert manifest.authority.cross_provider_failover == "disabled"
    assert manifest.authority.automatic_selection == "disabled"


def test_b1_duplicate_outputs_are_flagged_not_renamed(tmp_path: Path) -> None:
    manifest = _service().compile_manifest(
        [_Job(1, "same.mp3", "Første"), _Job(2, "same.mp3", "Anden")],
        _settings(),
        tmp_path,
    )
    first, second = manifest.requests
    assert first.filename == second.filename == "same.mp3"
    assert first.output_path == second.output_path
    assert "duplicate_output_with_row:1" in second.review_reasons


def test_b1_unsafe_filename_is_review_only_and_not_rewritten(tmp_path: Path) -> None:
    manifest = _service().compile_manifest(
        [_Job(1, "../outside.mp3", "Hej")], _settings(), tmp_path
    )
    request = manifest.requests[0]
    assert request.filename == "../outside.mp3"
    assert "unsafe_filename" in request.review_reasons


def test_b1_text_size_signals_are_advisory(tmp_path: Path) -> None:
    manifest = _service().compile_manifest(
        [
            _Job(1, "empty.mp3", ""),
            _Job(2, "short.mp3", "Hej"),
            _Job(3, "large.mp3", "x" * 5001),
        ],
        _settings(),
        tmp_path,
    )
    assert "empty_text" in manifest.requests[0].review_reasons
    assert "short_utterance" in manifest.requests[1].review_reasons
    assert "large_text_review" in manifest.requests[2].review_reasons
    assert [item.filename for item in manifest.requests] == [
        "empty.mp3",
        "short.mp3",
        "large.mp3",
    ]


def test_b1_batches_only_contiguous_equal_request_signatures(tmp_path: Path) -> None:
    jobs = [
        _Job(1, "a.mp3", "A"),
        _Job(2, "b.mp3", "B"),
        _Job(3, "c.mp3", "C"),
        _Job(4, "d.mp3", "D"),
    ]
    manifest = _service().compile_manifest(
        jobs, _settings(), tmp_path, job_language_overrides={3: "en"}
    )
    assert [batch.row_numbers for batch in manifest.batches] == [
        (1, 2),
        (3,),
        (4,),
    ]
    assert all(
        batch.policy == "observational_contiguous_group_only"
        for batch in manifest.batches
    )


def test_b1_manifest_digest_is_deterministic(tmp_path: Path) -> None:
    jobs = [_Job(1, "a.mp3", "Hej")]
    first = _service().compile_manifest(jobs, _settings(), tmp_path)
    second = _service().compile_manifest(jobs, _settings(), tmp_path)
    assert first.manifest_digest == second.manifest_digest
    assert first.authority.digest == second.authority.digest


def test_b1_default_serialization_redacts_text_and_api_key(tmp_path: Path) -> None:
    source_text = "PRIVATE SOURCE TEXT"
    secret = "VERY-SECRET-API-KEY"
    manifest = _service().compile_manifest(
        [_Job(1, "a.mp3", source_text)], _settings(api_key=secret), tmp_path
    )
    serialized = manifest.to_json()
    assert source_text not in serialized
    assert secret not in serialized
    assert "api_key" not in serialized
    assert manifest.requests[0].text_sha256 in serialized


def test_b1_explicit_text_serialization_is_opt_in(tmp_path: Path) -> None:
    manifest = _service().compile_manifest(
        [_Job(1, "a.mp3", "Opt-in text")], _settings(), tmp_path
    )
    default_payload = manifest.to_dict()
    explicit_payload = manifest.to_dict(include_text=True)
    assert "text" not in default_payload["requests"][0]
    assert explicit_payload["requests"][0]["text"] == "Opt-in text"


def test_b1_does_not_mutate_jobs_or_settings(tmp_path: Path) -> None:
    job = _Job(5, "original.mp3", "Original")
    settings = _settings()
    before_job = (job.row_number, job.filename, job.text)
    before_settings = dict(vars(settings))
    _service().compile_manifest(
        [job], settings, tmp_path, job_language_overrides={5: "en"}
    )
    assert (job.row_number, job.filename, job.text) == before_job
    assert vars(settings) == before_settings


def test_b1_has_no_execution_or_auto_selection_authority(tmp_path: Path) -> None:
    module = __import__(
        "app.services.intelligent_tts_production_service",
        fromlist=["IntelligentTTSProductionService"],
    )
    source = inspect.getsource(module)
    for forbidden in (
        "create_provider",
        "run_preflight",
        "start_generation",
        "apply_smart_routing",
        "detect_language",
    ):
        assert forbidden not in source

    output = tmp_path / "cert"
    result = certify(output)
    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert (output / "certification.json").is_file()
    manifest_payload = json.loads(
        (output / "manifest-example.json").read_text(encoding="utf-8")
    )
    assert manifest_payload["authority"]["automatic_selection"] == "disabled"
    assert manifest_payload["authority"]["cross_provider_failover"] == "disabled"
