from __future__ import annotations

from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_audit import PronunciationAuditDraft
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.pronunciation_audit_service import PronunciationAuditTrailService
from app.services.pronunciation_readiness_service import PronunciationReadinessService


ROOT = Path(__file__).resolve().parents[1]


def _job(row: int, text: str, **updates) -> TTSJob:
    return TTSJob(row_number=row, text=text, filename=f"row-{row}.mp3", **updates)


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="sk_PRIVATE_TEST_KEY",
        voice_id="voice-a",
        model_id="model-a",
        language_code="da",
        pronunciation_dictionary_locators=[
            {"pronunciation_dictionary_id": "dict-a", "version_id": "v1"}
        ],
        active_pronunciation_dictionary_id="dict-a:v1",
    )
    return base.model_copy(update=updates)


def _classified_jobs() -> tuple[tuple[TTSJob, ...], AppSettings]:
    assurance = PronunciationAssuranceService()
    settings = _settings(voice_id="voice-b")

    ready = _job(1, "EU")
    ready.pronunciation_override = assurance.encode_review_decision("original", ready, settings)

    needs_review = _job(2, "DR")

    stale = _job(3, "EU")
    stale.pronunciation_override = assurance.encode_review_decision("original", stale, _settings(voice_id="voice-a"))

    unsafe = _job(4, "20 kr.")
    unsafe.pronunciation_override = assurance.encode_review_decision("normalized", unsafe, _settings(voice_id="voice-a"))
    unsafe.text = "EU"

    no_action = _job(5, "Dette er en almindelig sætning til produktion.")
    return (ready, needs_review, stale, unsafe, no_action), settings


def test_a76_assigns_every_job_to_exactly_one_readiness_category() -> None:
    jobs, settings = _classified_jobs()
    result = PronunciationReadinessService().assess_project(jobs, settings)
    assert [row.category for row in result.rows] == [
        "Ready",
        "Needs review",
        "Stale",
        "Unsafe",
        "No action required",
    ]
    assert sum(result.counts.values()) == result.total_jobs == 5


def test_a76_project_counts_cover_risk_review_stale_and_unresolved() -> None:
    jobs, settings = _classified_jobs()
    result = PronunciationReadinessService().assess_project(jobs, settings)
    assert result.pronunciation_risk >= 3
    assert result.reviewed_current == 1
    assert result.stale_decisions == 1
    assert result.unresolved == 3
    assert result.keep_original == 1
    assert result.counts["Unsafe"] == 1
    assert result.counts["No action required"] == 1
    assert result.requires_attention is True


def test_a76_current_safe_normalized_decision_is_ready() -> None:
    assurance = PronunciationAssuranceService()
    settings = _settings()
    job = _job(1, "20 kr.")
    job.pronunciation_override = assurance.encode_review_decision("normalized", job, settings)
    result = PronunciationReadinessService().assess_project((job,), settings)
    assert result.rows[0].category == "Ready"
    assert result.normalized == 1
    assert result.unresolved == 0


def test_a76_low_risk_without_decision_requires_no_action() -> None:
    job = _job(1, "Dette er en almindelig sætning til produktion.")
    result = PronunciationReadinessService().assess_project((job,), _settings())
    assert result.rows[0].category == "No action required"
    assert result.requires_attention is False


def test_a76_audit_integrity_empty_verified_and_failed_are_visible(tmp_path: Path) -> None:
    readiness = PronunciationReadinessService()
    audit = PronunciationAuditTrailService()
    assurance = PronunciationAssuranceService()
    settings = _settings()
    job = _job(1, "EU")
    job.pronunciation_override = assurance.encode_review_decision("original", job, settings)

    empty = readiness.assess_project((job,), settings, output_dir=tmp_path, project_id="project-a")
    assert empty.audit_integrity == "EMPTY"

    audit.append_events(
        tmp_path,
        "project-a",
        {1: job},
        settings,
        (PronunciationAuditDraft(1, "decision_set", "original", ""),),
    )
    verified = readiness.assess_project((job,), settings, output_dir=tmp_path, project_id="project-a")
    assert verified.audit_integrity == "VERIFIED"
    assert verified.audit_event_count == 1
    assert verified.rows[0].audit_event_count == 1

    path = audit.audit_path(tmp_path, "project-a")
    path.write_text(path.read_text(encoding="utf-8").replace('"decision_kind":"original"', '"decision_kind":"normalized"'), encoding="utf-8")
    failed = readiness.assess_project((job,), settings, output_dir=tmp_path, project_id="project-a")
    assert failed.audit_integrity == "FAILED"
    assert failed.requires_attention is True


def test_a76_service_is_read_only_and_has_no_external_execution_authority() -> None:
    source = (ROOT / "app/services/pronunciation_readiness_service.py").read_text(encoding="utf-8")
    for forbidden in (
        "create_provider(",
        ".synthesize(",
        "run_preflight(",
        "generation_controller.start",
        "provider.setCurrentText",
        "voice.setText",
        "set_model_value",
        "set_language_value",
        "detect_language",
    ):
        assert forbidden not in source


def test_a76_dashboard_has_all_five_categories_and_no_bulk_approval() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_readiness_dialog.py").read_text(encoding="utf-8")
    for label in ("Ready", "Needs review", "Stale", "Unsafe", "No action required"):
        assert label in (ROOT / "app/services/pronunciation_readiness_service.py").read_text(encoding="utf-8")
    assert "Open Pronunciation Review Workspace" in source
    for forbidden in ("Approve all", "Bulk approve", "decisionRequested", "revalidateRequested"):
        assert forbidden not in source


def test_a76_dashboard_does_not_run_preflight_generation_or_routing() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_readiness_dialog.py").read_text(encoding="utf-8")
    for forbidden in (
        "run_preflight(",
        "generation_controller.start",
        "create_provider(",
        "provider.setCurrentText",
        "set_language_value",
        "detect_language",
    ):
        assert forbidden not in source


def test_a76_main_exposes_explicit_readiness_workspace_without_launch_side_effects() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "Pronunciation Project Readiness" in source
    assert "open_pronunciation_readiness" in source
    start = source.index("    def open_pronunciation_readiness")
    end = source.index("    def set_pronunciation_override_for_rows", start)
    block = source[start:end]
    assert "assess_project" in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block
    assert "set_pronunciation_override_for_rows(" not in block


def test_a76_readiness_refreshes_after_explicit_review_changes() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "_refresh_pronunciation_readiness_dialog()" in source
    setter_start = source.index("    def set_pronunciation_override_for_rows")
    setter_end = source.index("    def _open_language_probe_for_jobs", setter_start)
    assert "_refresh_pronunciation_readiness_dialog()" in source[setter_start:setter_end]


def test_a76_preserves_authoritative_language_and_does_not_detect_content_language() -> None:
    source = (ROOT / "app/services/pronunciation_readiness_service.py").read_text(encoding="utf-8")
    assert "assess_job(job, settings)" in source
    assert "decision_freshness(job, settings)" in source
    assert "language_override" not in source
    assert "detect_language" not in source


def test_a76_document_preserves_schema23_and_fixed_next_roadmap() -> None:
    text = (ROOT / "docs/PRONUNCIATION_COVERAGE_PROJECT_READINESS_ROADMAP2_A76.md").read_text(encoding="utf-8")
    assert "Database schema 23 is unchanged" in text
    assert "A7.7 — Launch Assurance Consolidation" in text
    assert "no bulk approval" in text
    assert "does not run Preflight" in text


def test_a76_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/pronunciation_readiness.py"),
        Path("app/services/pronunciation_readiness_service.py"),
        Path("app/gui/dialogs/pronunciation_readiness_dialog.py"),
        Path("app/gui/main.py"),
        Path("docs/PRONUNCIATION_COVERAGE_PROJECT_READINESS_ROADMAP2_A76.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
