from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.exceptions import ConfigurationError
from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.pronunciation_service import PronunciationService


ROOT = Path(__file__).resolve().parents[1]


def _job(row: int, text: str, **updates) -> TTSJob:
    return TTSJob(row_number=row, text=text, filename=f"row-{row}.mp3", **updates)


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="sk_TEST",
        voice_id="voice-a",
        model_id="model-a",
        language_code="da",
        pronunciation_dictionary_locators=[
            {"pronunciation_dictionary_id": "dict-a", "version_id": "v1"}
        ],
        active_pronunciation_dictionary_id="dict-a:v1",
    )
    return base.model_copy(update=updates)


def test_a74_context_fingerprint_is_stable_for_non_pronunciation_settings() -> None:
    service = PronunciationAssuranceService()
    job = _job(1, "20 kr.")
    baseline = service.review_context_fingerprint(job, _settings())
    changed = _settings(speed=1.15, delay_seconds=2.5, max_retries=1)
    assert service.review_context_fingerprint(job, changed) == baseline


def test_a74_context_fingerprint_changes_for_pronunciation_critical_context() -> None:
    service = PronunciationAssuranceService()
    baseline_job = _job(1, "20 kr.")
    baseline_settings = _settings()
    baseline = service.review_context_fingerprint(baseline_job, baseline_settings)

    variants = (
        (_job(1, "21 kr."), baseline_settings),
        (_job(1, "20 kr.", language_override="en"), baseline_settings),
        (baseline_job, _settings(provider="openai")),
        (baseline_job, _settings(voice_id="voice-b")),
        (baseline_job, _settings(model_id="model-b")),
        (baseline_job, _settings(active_pronunciation_dictionary_id="dict-a:v2")),
        (
            baseline_job,
            _settings(
                pronunciation_dictionary_locators=[
                    {"pronunciation_dictionary_id": "dict-a", "version_id": "v2"}
                ]
            ),
        ),
    )
    for job, settings in variants:
        assert service.review_context_fingerprint(job, settings) != baseline


def test_a74_new_decision_is_versioned_and_current() -> None:
    service = PronunciationAssuranceService()
    settings = _settings()
    job = _job(1, "EU")
    stored = service.encode_review_decision("original", job, settings)
    job.pronunciation_override = stored
    assert stored.startswith("original@a74:")
    assert service.decision_kind(stored) == "original"
    assert service.decision_fingerprint(stored)
    assert service.decision_freshness(job, settings) == "current"


def test_a74_versioned_decision_becomes_stale_after_voice_change() -> None:
    service = PronunciationAssuranceService()
    settings = _settings()
    job = _job(1, "EU")
    job.pronunciation_override = service.encode_review_decision("original", job, settings)
    assert service.decision_freshness(job, _settings(voice_id="voice-b")) == "stale"


def test_a74_plain_preexisting_decision_is_legacy_in_freshness_mode() -> None:
    service = PronunciationAssuranceService()
    job = _job(1, "EU", pronunciation_override="original")
    assert service.decision_kind(job.pronunciation_override) == "original"
    assert service.decision_freshness(job, _settings()) == "legacy"
    batch = service.assess_batch([job], _settings(), require_freshness=True)
    assert batch.reviewed_rows == ()
    assert batch.legacy_review_rows == (1,)
    assert batch.high_risk_rows == (1,)


def test_a74_a73_compatibility_default_still_reads_plain_decision_as_reviewed() -> None:
    job = _job(1, "EU", pronunciation_override="original")
    batch = PronunciationAssuranceService().assess_batch([job], _settings())
    assert batch.reviewed_rows == (1,)
    assert batch.explicit_original_rows == (1,)


def test_a74_current_versioned_normalized_decision_executes_candidate() -> None:
    service = PronunciationAssuranceService()
    settings = _settings()
    job = _job(1, "20 kr.")
    job.pronunciation_override = service.encode_review_decision("normalized", job, settings)
    result = PronunciationService().prepare_job(job, settings)
    assert result.provider_text == "tyve kroner"
    assert result.strategy == "language_locked_currency"
    assert job.text == "20 kr."


def test_a74_stale_versioned_normalized_decision_never_falls_back_silently() -> None:
    service = PronunciationAssuranceService()
    settings = _settings()
    job = _job(1, "20 kr.")
    job.pronunciation_override = service.encode_review_decision("normalized", job, settings)
    with pytest.raises(ConfigurationError, match="stale"):
        PronunciationService().prepare_job(job, _settings(model_id="model-b"))
    assert job.text == "20 kr."


def test_a74_freshness_aware_batch_separates_current_stale_and_legacy() -> None:
    service = PronunciationAssuranceService()
    settings = _settings()
    current = _job(1, "EU")
    current.pronunciation_override = service.encode_review_decision("original", current, settings)
    stale = _job(2, "10")
    stale.pronunciation_override = service.encode_review_decision("normalized", stale, settings)
    legacy = _job(3, "DR", pronunciation_override="original")
    changed = _settings(voice_id="voice-b")

    # Re-encode only row 1 for the changed current context.
    current.pronunciation_override = service.encode_review_decision("original", current, changed)
    batch = service.assess_batch([current, stale, legacy], changed, require_freshness=True)
    assert batch.current_review_rows == (1,)
    assert batch.stale_review_rows == (2,)
    assert batch.legacy_review_rows == (3,)
    assert batch.reviewed_rows == (1,)


def test_a74_preflight_state_exposes_freshness_evidence() -> None:
    state = PreflightState(
        pronunciation_current_review_rows=(1,),
        pronunciation_stale_review_rows=(2,),
        pronunciation_legacy_review_rows=(3,),
        pronunciation_previews=(
            {
                "row": 2,
                "decision_kind": "normalized",
                "decision_freshness": "stale",
                "decision_fingerprint": "old",
                "current_fingerprint": "new",
            },
        ),
    )
    assert state.pronunciation_current_review_rows == (1,)
    assert state.pronunciation_stale_review_rows == (2,)
    assert state.pronunciation_legacy_review_rows == (3,)
    assert state.pronunciation_previews[0]["decision_freshness"] == "stale"


def test_a74_preflight_requires_freshness_and_blocks_stale_normalized() -> None:
    from app.services.preflight_service import PreflightService

    source = inspect.getsource(PreflightService)
    assert "require_freshness=True" in source
    assert "pronunciation_normalized_decision_stale" in source
    assert "pronunciation_review_evidence_stale" in source
    assert "explicit normalized pronunciation decision is stale" in source
    assert "revalidate" in source.lower()


def test_a74_review_workspace_exposes_freshness_filter_and_explicit_revalidation() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_review_dialog.py").read_text(encoding="utf-8")
    assert 'FILTER_STALE = "Needs revalidation"' in source
    assert '"Freshness"' in source
    assert "Revalidate selected decisions" in source
    assert "revalidateRequested.emit(rows)" in source
    assert "require_freshness=True" in source


def test_a74_review_workspace_revalidation_never_runs_external_actions() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_review_dialog.py").read_text(encoding="utf-8")
    for forbidden in (
        "create_provider(",
        "provider.synthesize",
        "run_preflight(",
        "dry_run(",
        "generation_controller.start",
        "provider.setCurrentText",
        "voice.setText",
        "set_model_value",
        "set_language_value",
        "detect_language",
    ):
        assert forbidden not in source


def test_a74_main_records_versioned_decisions_and_revalidates_same_intent_only() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def set_pronunciation_override_for_rows")
    end = source.index("    def _open_language_probe_for_jobs", start)
    setter = source[start:end]
    assert "encode_review_decision" in setter
    assert "value in {'original','normalized'}" in setter

    start = source.index("    def pronunciation_review_revalidate")
    end = source.index("    def pronunciation_review_probe", start)
    block = source[start:end]
    assert "generation_controller.is_active" in block
    assert "decision not in {'original','normalized'}" in block
    assert "decision=='normalized' and not assessment.normalization_safe" in block
    assert "encode_review_decision(decision,job,settings)" in block
    assert "invalidate_preflight()" in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block


def test_a74_main_revalidation_is_user_triggered_from_workspace() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "dialog.revalidateRequested.connect(self.pronunciation_review_revalidate)" in source
    assert "Stop the active generation before revalidating pronunciation review decisions." in source


def test_a74_fingerprint_code_has_no_content_language_detection_or_hidden_routing() -> None:
    paths = (
        ROOT / "app/services/pronunciation_assurance_service.py",
        ROOT / "app/services/pronunciation_service.py",
        ROOT / "app/gui/dialogs/pronunciation_review_dialog.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "detect_language",
        "langdetect",
        "auto_provider",
        "auto_voice",
        "auto_model",
        "auto_language",
        "cross_provider_failover",
    ):
        assert forbidden not in source


def test_a74_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/pronunciation_assurance.py"),
        Path("app/services/pronunciation_assurance_service.py"),
        Path("app/services/pronunciation_service.py"),
        Path("app/models/preflight_state.py"),
        Path("app/services/preflight_service.py"),
        Path("app/gui/dialogs/pronunciation_review_dialog.py"),
        Path("app/gui/main.py"),
        Path("docs/PRONUNCIATION_DECISION_FRESHNESS_REVALIDATION_ROADMAP2_A74.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
