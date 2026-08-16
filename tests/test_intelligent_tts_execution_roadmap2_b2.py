from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.intelligent_tts_execution_service import (
    EXECUTION_BINDING_SCHEMA_VERSION,
    IntelligentTTSExecutionDrift,
    IntelligentTTSExecutionService,
)
from scripts.certify_intelligent_tts_execution_roadmap2_b2 import (
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
        "api_key": "SECRET",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _jobs():
    return [
        _Job(1, "a.mp3", "Dansk tekst."),
        _Job(2, "b.mp3", "English text."),
    ]


def test_b2_locks_to_b1_certified_baseline() -> None:
    assert EXPECTED_BASELINE_COMMIT == (
        "4671d517ab6e008e7cd6e872e66d6e94a77e5ce6"
    )
    assert CERTIFICATION_VERSION == "roadmap2-b2-v1"
    assert EXECUTION_BINDING_SCHEMA_VERSION == 1


def test_b2_prepare_preserves_explicit_authority(tmp_path: Path) -> None:
    binding = IntelligentTTSExecutionService().prepare(
        _jobs(),
        _settings(),
        tmp_path,
    )
    assert binding.provider == "elevenlabs"
    assert binding.profile_id == "profile-1"
    assert binding.voice_id == "voice-1"
    assert binding.model_id == "model-1"
    assert binding.default_language == "da"


def test_b2_prepare_preserves_queue_order(tmp_path: Path) -> None:
    binding = IntelligentTTSExecutionService().prepare(
        list(reversed(_jobs())),
        _settings(),
        tmp_path,
    )
    assert binding.row_numbers == (2, 1)


def test_b2_explicit_language_override_changes_manifest_only_when_passed(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSExecutionService()
    default = service.prepare(_jobs(), _settings(), tmp_path)
    explicit = service.prepare(
        _jobs(),
        _settings(),
        tmp_path,
        job_language_overrides={2: "en"},
    )
    assert default.manifest_digest != explicit.manifest_digest
    assert explicit.language_override_policy == "explicit_mapping_only"


def test_b2_identical_context_verifies(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(_jobs(), _settings(), tmp_path)
    assert (
        service.verify_unchanged(
            binding,
            _jobs(),
            _settings(),
            tmp_path,
        )
        == binding
    )


def test_b2_provider_drift_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(_jobs(), _settings(), tmp_path)
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            _jobs(),
            _settings(provider="openai"),
            tmp_path,
        )


def test_b2_voice_or_model_drift_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(_jobs(), _settings(), tmp_path)
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            _jobs(),
            _settings(voice_id="other"),
            tmp_path,
        )
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            _jobs(),
            _settings(model_id="other"),
            tmp_path,
        )


def test_b2_language_drift_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(_jobs(), _settings(), tmp_path)
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            _jobs(),
            _settings(language_code="en"),
            tmp_path,
        )


def test_b2_queue_order_drift_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(_jobs(), _settings(), tmp_path)
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            list(reversed(_jobs())),
            _settings(),
            tmp_path,
        )


def test_b2_text_drift_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(_jobs(), _settings(), tmp_path)
    changed = _jobs()
    changed[0].text = "Changed"
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            changed,
            _settings(),
            tmp_path,
        )


def test_b2_output_drift_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSExecutionService()
    binding = service.prepare(
        _jobs(),
        _settings(),
        tmp_path / "a",
    )
    with pytest.raises(IntelligentTTSExecutionDrift):
        service.verify_unchanged(
            binding,
            _jobs(),
            _settings(),
            tmp_path / "b",
        )


def test_b2_binding_is_secret_and_text_free(tmp_path: Path) -> None:
    binding = IntelligentTTSExecutionService().prepare(
        _jobs(),
        _settings(api_key="TOP-SECRET"),
        tmp_path,
    )
    serialized = str(binding.to_dict())
    assert "TOP-SECRET" not in serialized
    assert "Dansk tekst." not in serialized
    assert "api_key" not in serialized


def test_b2_service_has_no_provider_preflight_or_generation_authority() -> None:
    module = __import__(
        "app.services.intelligent_tts_execution_service",
        fromlist=["IntelligentTTSExecutionService"],
    )
    source = inspect.getsource(module)
    for token in (
        "create_provider",
        "run_preflight",
        "start_generation",
        "apply_smart_routing",
        "detect_language",
        "GenerationWorker",
    ):
        assert token not in source


def test_b2_certification_is_machine_verifiable(tmp_path: Path) -> None:
    result = certify(tmp_path / "evidence")
    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert (tmp_path / "evidence" / "certification.json").is_file()
    assert (
        tmp_path / "evidence" / "execution-binding-example.json"
    ).is_file()
