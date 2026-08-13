from __future__ import annotations

import inspect
from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.pronunciation_service import PronunciationService


ROOT = Path(__file__).resolve().parents[1]


def _job(row: int, text: str, **updates) -> TTSJob:
    return TTSJob(row_number=row, text=text, filename=f"row-{row}.mp3", **updates)


def test_a72_danish_integer_has_safe_language_locked_candidate() -> None:
    assessment = PronunciationAssuranceService().assess("10", AppSettings(language_code="da"))
    assert assessment.normalized_text == "ti"
    assert assessment.normalization_kind == "integer"
    assert assessment.normalization_safe is True
    assert "digits" in assessment.flags
    assert "short_utterance" in assessment.flags


def test_a72_danish_currency_has_safe_candidate() -> None:
    assessment = PronunciationAssuranceService().assess("20 kr.", AppSettings(language_code="da"))
    assert assessment.normalized_text == "tyve kroner"
    assert assessment.normalization_kind == "currency"
    assert assessment.normalization_safe is True
    assert "currency" in assessment.flags


def test_a72_danish_date_has_safe_candidate() -> None:
    assessment = PronunciationAssuranceService().assess("13/08/2026", AppSettings(language_code="da"))
    assert assessment.normalized_text == "den trettende august to tusind og seksogtyve"
    assert assessment.normalization_kind == "date"
    assert assessment.normalization_safe is True
    assert "date" in assessment.flags


def test_a72_non_danish_numeric_text_is_not_normalized() -> None:
    assessment = PronunciationAssuranceService().assess("10", AppSettings(language_code="en"))
    assert assessment.normalized_text == "10"
    assert assessment.normalization_safe is False
    assert assessment.normalization_kind == "none"


def test_a72_acronym_and_proper_name_are_review_risks_not_guessed_rewrites() -> None:
    service = PronunciationAssuranceService()
    acronym = service.assess("EU", AppSettings(language_code="da"))
    name = service.assess("Mette Frederiksen", AppSettings(language_code="da"))
    assert acronym.risk_level == "high"
    assert "acronym" in acronym.flags
    assert acronym.normalization_safe is False
    assert name.risk_level == "high"
    assert "proper_name" in name.flags
    assert name.normalization_safe is False


def test_a72_script_mismatch_is_risk_only_and_never_language_detection() -> None:
    assessment = PronunciationAssuranceService().assess("سلام", AppSettings(language_code="da"))
    assert assessment.language == "da"
    assert assessment.risk_level == "high"
    assert "script_mismatch" in assessment.flags
    assert assessment.normalized_text == "سلام"


def test_a72_batch_uses_only_project_or_explicit_job_languages() -> None:
    settings = AppSettings(language_code="da")
    jobs = [_job(1, "10"), _job(2, "10", language_override="en")]
    batch = PronunciationAssuranceService().assess_batch(jobs, settings)
    assert batch.languages == ("da", "en")
    assert batch.assessments[0].language == "da"
    assert batch.assessments[1].language == "en"
    assert batch.assessments[0].normalization_safe is True
    assert batch.assessments[1].normalization_safe is False


def test_a72_provider_text_stays_original_without_explicit_override() -> None:
    settings = AppSettings(language_code="da")
    result = PronunciationService().prepare_job(_job(1, "20 kr."), settings)
    assert result.original_text == "20 kr."
    assert result.provider_text == "20 kr."
    assert result.aid_applied is False


def test_a72_explicit_normalized_override_changes_only_provider_form() -> None:
    settings = AppSettings(language_code="da")
    job = _job(1, "20 kr.", pronunciation_override="normalized")
    result = PronunciationService().prepare_job(job, settings)
    assert job.text == "20 kr."
    assert result.original_text == "20 kr."
    assert result.provider_text == "tyve kroner"
    assert result.aid_applied is True
    assert result.strategy == "language_locked_currency"


def test_a72_unsafe_normalized_override_fails_closed_without_rewrite() -> None:
    settings = AppSettings(language_code="da")
    result = PronunciationService().prepare_job(
        _job(1, "EU", pronunciation_override="normalized"),
        settings,
    )
    assert result.provider_text == "EU"
    assert result.aid_applied is False
    assert result.strategy == "normalization_unavailable"


def test_a72_dictionary_disable_contract_is_preserved() -> None:
    settings = AppSettings(
        language_code="da",
        pronunciation_dictionary_locators=[{"pronunciation_dictionary_id": "dict-1", "version_id": "v1"}],
        active_pronunciation_dictionary_id="dict-1:v1",
    )
    result = PronunciationService().prepare_job(
        _job(1, "10", pronunciation_override="dictionary_disabled"),
        settings,
    )
    assert result.provider_text == "10"
    assert result.strategy == "dictionary_disabled"
    assert result.dictionary_locators == ()


def test_a72_explicit_normalization_preserves_dictionary_metadata() -> None:
    locator = {"pronunciation_dictionary_id": "dict-1", "version_id": "v1"}
    settings = AppSettings(
        language_code="da",
        pronunciation_dictionary_locators=[locator],
        active_pronunciation_dictionary_id="dict-1:v1",
    )
    result = PronunciationService().prepare_job(
        _job(1, "10", pronunciation_override="normalized"),
        settings,
    )
    assert result.provider_text == "ti"
    assert result.dictionary_locators == (locator,)
    assert result.dictionary_fingerprint == "dict-1:v1"


def test_a72_global_aid_flag_does_not_become_hidden_execution_permission() -> None:
    service = PronunciationService()
    enabled = AppSettings(language_code="da", short_text_pronunciation_aid=True)
    disabled = AppSettings(language_code="da", short_text_pronunciation_aid=False)
    assert service.should_apply_danish_aid("10", enabled) is True
    assert service.should_apply_danish_aid("10", disabled) is False
    assert service.prepare_job(_job(1, "10"), enabled).provider_text == "10"


def test_a72_preflight_contract_blocks_unsafe_override_and_keys_pronunciation_decision() -> None:
    from app.services.preflight_service import PreflightService

    source = inspect.getsource(PreflightService)
    assert "pronunciation_normalization_unavailable" in source
    assert "pronunciation_review_required" in source
    assert 'job.pronunciation_override or ""' in source
    assert "No content-based language detection or automatic language switching" in source


def test_a72_preflight_state_persists_visible_pronunciation_evidence() -> None:
    state = PreflightState(
        pronunciation_risk_summary="review",
        pronunciation_high_risk_rows=(2,),
        pronunciation_medium_risk_rows=(1,),
        pronunciation_normalizable_rows=(1,),
        pronunciation_previews=(
            {
                "row": 1,
                "language": "da",
                "original_text": "10",
                "normalized_text": "ti",
            },
        ),
    )
    assert state.pronunciation_risk_summary == "review"
    assert state.pronunciation_high_risk_rows == (2,)
    assert state.pronunciation_previews[0]["normalized_text"] == "ti"


def test_a72_generation_confirmation_requires_pronunciation_review_acknowledgement() -> None:
    settings = AppSettings(provider="mock", language_code="da")
    state = PreflightState(
        total_jobs=1,
        estimated_files=1,
        estimated_characters=2,
        estimated_provider_requests=1,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        pronunciation_risk_summary="1 short utterance needs review",
        pronunciation_high_risk_rows=(1,),
    )
    confirmation = GenerationConfirmationCoordinator().evaluate(state, settings)
    check = next(item for item in confirmation.checks if item.code == "pronunciation_review")
    assert check.requires_acknowledgement is True
    assert "pronunciation_review" in confirmation.required_acknowledgements


def test_a72_language_probe_is_manual_and_limited_to_one_to_three_samples() -> None:
    source = (ROOT / "app/gui/dialogs/language_probe_dialog.py").read_text(encoding="utf-8")
    assert "1 <= len(assessments) <= 3" in source
    assert "previewRequested" in source
    assert "overrideRequested" in source
    assert "generate_preview" not in source
    assert "auto" in source.lower()


def test_a72_main_preloads_voice_browser_but_never_auto_starts_preview() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def language_probe_preview")
    end = source.index("    def language_probe_override", start)
    block = source[start:end]
    assert "self.open_voice_browser()" in block
    assert "preview_text" in block
    assert "setPlainText(text)" in block
    assert "generate_preview" not in block
    assert "Press Preview manually" in block


def test_a72_main_exposes_explicit_language_probe_without_auto_switch_contracts() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "Language Probe (1-3 samples)" in source
    assert "def open_language_probe(self):" in source
    assert "Select between 1 and 3 queue rows" in source
    block_start = source.index("    def open_language_probe(self):")
    block_end = source.index("    def language_probe_preview", block_start)
    block = source[block_start:block_end]
    for forbidden in (
        "provider.setCurrentText",
        "set_model_value",
        "voice.setText",
        "set_language_value",
        "dry_run(",
        "run_preflight(",
        "start(",
    ):
        assert forbidden not in block


def test_a72_new_logic_has_no_content_language_detector_or_hidden_routing() -> None:
    paths = (
        ROOT / "app/models/pronunciation_assurance.py",
        ROOT / "app/services/pronunciation_assurance_service.py",
        ROOT / "app/services/pronunciation_service.py",
        ROOT / "app/gui/dialogs/language_probe_dialog.py",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "detect_language",
        "langdetect",
        "auto_provider",
        "auto_voice",
        "auto_model",
        "cross_provider_failover",
    ):
        assert forbidden not in text


def test_a72_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/pronunciation_assurance.py"),
        Path("app/services/pronunciation_assurance_service.py"),
        Path("app/services/pronunciation_service.py"),
        Path("app/models/preflight_state.py"),
        Path("app/services/preflight_service.py"),
        Path("app/services/generation_confirmation_service.py"),
        Path("app/gui/dialogs/language_probe_dialog.py"),
        Path("app/gui/main.py"),
        Path("docs/SHORT_UTTERANCE_PRONUNCIATION_HARDENING_ROADMAP2_A72.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
