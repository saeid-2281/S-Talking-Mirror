from __future__ import annotations

import inspect
from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.pronunciation_service import PronunciationService


ROOT = Path(__file__).resolve().parents[1]


def _job(row: int, text: str, **updates) -> TTSJob:
    return TTSJob(row_number=row, text=text, filename=f"row-{row}.mp3", **updates)


def test_a73_explicit_original_is_a_review_decision_without_text_mutation() -> None:
    settings = AppSettings(language_code="da")
    job = _job(1, "EU", pronunciation_override="original")
    batch = PronunciationAssuranceService().assess_batch([job], settings)
    assert batch.reviewed_rows == (1,)
    assert batch.explicit_original_rows == (1,)
    assert batch.high_risk_rows == ()
    assert job.text == "EU"


def test_a73_safe_normalized_decision_is_reviewed() -> None:
    settings = AppSettings(language_code="da")
    job = _job(1, "20 kr.", pronunciation_override="normalized")
    batch = PronunciationAssuranceService().assess_batch([job], settings)
    assert batch.reviewed_rows == (1,)
    assert batch.normalized_rows == (1,)
    assert batch.medium_risk_rows == ()
    assert batch.unsafe_normalization_rows == ()


def test_a73_unsafe_normalized_decision_is_not_counted_as_reviewed() -> None:
    settings = AppSettings(language_code="da")
    job = _job(1, "EU", pronunciation_override="normalized")
    batch = PronunciationAssuranceService().assess_batch([job], settings)
    assert batch.reviewed_rows == ()
    assert batch.normalized_rows == ()
    assert batch.unsafe_normalization_rows == (1,)
    assert batch.high_risk_rows == (1,)


def test_a73_unreviewed_high_and_medium_rows_remain_visible() -> None:
    settings = AppSettings(language_code="da")
    jobs = [_job(1, "EU"), _job(2, "20 kr."), _job(3, "Hej med dig")]
    batch = PronunciationAssuranceService().assess_batch(jobs, settings)
    assert batch.high_risk_rows == (1,)
    assert batch.medium_risk_rows == (2,)
    assert batch.reviewed_rows == ()
    assert 2 in batch.normalizable_rows


def test_a73_explicit_original_execution_preserves_provider_text_and_dictionary_metadata() -> None:
    locator = {"pronunciation_dictionary_id": "dict-1", "version_id": "v1"}
    settings = AppSettings(
        language_code="da",
        pronunciation_dictionary_locators=[locator],
        active_pronunciation_dictionary_id="dict-1:v1",
    )
    job = _job(1, "EU", pronunciation_override="original")
    result = PronunciationService().prepare_job(job, settings)
    assert result.original_text == "EU"
    assert result.provider_text == "EU"
    assert result.aid_applied is False
    assert result.strategy == "explicit_original"
    assert result.dictionary_locators == (locator,)
    assert result.dictionary_fingerprint == "dict-1:v1"


def test_a73_preflight_state_persists_review_evidence() -> None:
    state = PreflightState(
        pronunciation_reviewed_rows=(1, 2),
        pronunciation_explicit_original_rows=(1,),
        pronunciation_normalized_rows=(2,),
        pronunciation_previews=(
            {"row": 1, "decision": "original"},
            {"row": 2, "decision": "normalized"},
        ),
    )
    assert state.pronunciation_reviewed_rows == (1, 2)
    assert state.pronunciation_explicit_original_rows == (1,)
    assert state.pronunciation_normalized_rows == (2,)
    assert state.pronunciation_previews[0]["decision"] == "original"


def test_a73_preflight_treats_explicit_original_as_reviewed_and_keeps_unsafe_block() -> None:
    from app.services.preflight_service import PreflightService

    source = inspect.getsource(PreflightService)
    assert 'if override == "original":' in source
    assert 'if override == "normalized":' in source
    assert "pronunciation_normalization_unavailable" in source
    assert "Pronunciation Review Workspace" in source
    assert 'job.pronunciation_override or ""' in source


def test_a73_batch_summary_reports_explicit_decision_count() -> None:
    settings = AppSettings(language_code="da")
    jobs = [
        _job(1, "EU", pronunciation_override="original"),
        _job(2, "10", pronunciation_override="normalized"),
        _job(3, "DR"),
    ]
    batch = PronunciationAssuranceService().assess_batch(jobs, settings)
    assert "2 explicit decision(s) recorded" in batch.summary
    assert batch.reviewed_rows == (1, 2)
    assert batch.high_risk_rows == (3,)


def test_a73_large_batch_review_analysis_is_deterministic_and_ordered() -> None:
    settings = AppSettings(language_code="da")
    jobs = [
        _job(row, "EU" if row % 2 else "10", pronunciation_override="original" if row % 5 == 0 else None)
        for row in range(1, 501)
    ]
    batch = PronunciationAssuranceService().assess_batch(jobs, settings)
    assert batch.reviewed_rows == tuple(range(5, 501, 5))
    assert batch.high_risk_rows == tuple(row for row in range(1, 501, 2) if row % 5 != 0)
    assert batch.medium_risk_rows == tuple(row for row in range(2, 501, 2) if row % 5 != 0)


def test_a73_language_probe_keep_original_records_explicit_review() -> None:
    source = (ROOT / "app/gui/dialogs/language_probe_dialog.py").read_text(encoding="utf-8")
    assert '"original"' in source
    assert "Keep original" in source
    keep_start = source.index('keep_original = QPushButton("Keep original")')
    keep_block = source[keep_start:keep_start + 500]
    assert '"original"' in keep_block


def test_a73_review_workspace_has_explicit_selection_only_actions() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_review_dialog.py").read_text(encoding="utf-8")
    assert "Needs review" in source
    assert "Use original for selected" in source
    assert "Use normalized for selected" in source
    assert "Clear decision" in source
    assert "Language Probe selected (1-3)" in source
    assert "selected_rows" in source
    assert "decisionRequested.emit(rows, decision)" in source
    assert "every selected row" in source.lower()


def test_a73_review_workspace_never_auto_executes_provider_or_preflight_actions() -> None:
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


def test_a73_main_exposes_review_workspace_without_automatic_generation_actions() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "Pronunciation Review Workspace" in source
    assert "def open_pronunciation_review(self):" in source
    assert "Stop the active generation before changing pronunciation review decisions." in source
    start = source.index("    def open_pronunciation_review(self):")
    end = source.index("    def pronunciation_review_decision", start)
    block = source[start:end]
    assert "generation_plan().jobs" in block
    for forbidden in (
        "provider.setCurrentText",
        "voice.setText",
        "set_model_value",
        "set_language_value",
        "dry_run(",
        "run_preflight(",
        "generation_controller.start(",
    ):
        assert forbidden not in block


def test_a73_batch_decision_handler_invalidates_preflight_but_does_not_run_it() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def pronunciation_review_decision")
    end = source.index("    def pronunciation_review_probe", start)
    block = source[start:end]
    assert "generation_controller.is_active" in block
    assert "Stop the active generation before changing pronunciation review decisions." in block
    assert "set_pronunciation_override_for_rows" in block
    assert "Run Preflight before generation" in block
    assert "run_preflight(" not in block
    assert "dry_run(" not in block
    assert "start(" not in block


def test_a73_probe_handoff_remains_manual_and_limited_to_three_rows() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def pronunciation_review_probe")
    end = source.index("    def language_probe_preview", start)
    block = source[start:end]
    assert "1 <= len(jobs) <= 3" in block
    assert "_open_language_probe_for_jobs" in block
    assert "generate_preview" not in block
    assert "synthesize" not in block


def test_a73_review_logic_preserves_language_authority_and_has_no_hidden_routing() -> None:
    paths = (
        ROOT / "app/models/pronunciation_assurance.py",
        ROOT / "app/services/pronunciation_assurance_service.py",
        ROOT / "app/services/pronunciation_service.py",
        ROOT / "app/gui/dialogs/pronunciation_review_dialog.py",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "detect_language",
        "langdetect",
        "auto_provider",
        "auto_voice",
        "auto_model",
        "auto_language",
        "cross_provider_failover",
    ):
        assert forbidden not in text


def test_a73_source_text_is_not_rewritten_by_review_service_path() -> None:
    settings = AppSettings(language_code="da")
    original = "20 kr."
    job = _job(1, original, pronunciation_override="normalized")
    PronunciationAssuranceService().assess_batch([job], settings)
    PronunciationService().prepare_job(job, settings)
    assert job.text == original


def test_a73_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/pronunciation_assurance.py"),
        Path("app/services/pronunciation_assurance_service.py"),
        Path("app/services/pronunciation_service.py"),
        Path("app/models/preflight_state.py"),
        Path("app/services/preflight_service.py"),
        Path("app/gui/dialogs/language_probe_dialog.py"),
        Path("app/gui/dialogs/pronunciation_review_dialog.py"),
        Path("app/gui/main.py"),
        Path("docs/PRONUNCIATION_REVIEW_WORKSPACE_ROADMAP2_A73.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
