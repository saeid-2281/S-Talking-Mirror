from __future__ import annotations

import json
from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_audit import PronunciationAuditDraft
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.pronunciation_audit_service import PronunciationAuditTrailService


ROOT = Path(__file__).resolve().parents[1]


def _job(row: int, text: str, **updates) -> TTSJob:
    return TTSJob(row_number=row, text=text, filename=f"row-{row}.mp3", **updates)


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="sk_PRIVATE_TEST_KEY",
        voice_id="voice-private-a",
        model_id="model-private-a",
        language_code="da",
        pronunciation_dictionary_locators=[
            {"pronunciation_dictionary_id": "dictionary-private-a", "version_id": "v1"}
        ],
        active_pronunciation_dictionary_id="dictionary-private-a:v1",
    )
    return base.model_copy(update=updates)


def _recorded_job(row: int = 1, text: str = "20 kr.") -> tuple[TTSJob, AppSettings]:
    settings = _settings()
    job = _job(row, text)
    assurance = PronunciationAssuranceService()
    job.pronunciation_override = assurance.encode_review_decision("normalized", job, settings)
    return job, settings


def test_a75_audit_path_does_not_expose_raw_project_identifier(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    path = service.audit_path(tmp_path, "Private Patient Project 123")
    assert "Private Patient Project 123" not in str(path)
    assert path.name.startswith("project-")
    assert path.suffix == ".jsonl"


def test_a75_append_and_verify_hash_chained_decision_event(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    job, settings = _recorded_job()
    events = service.append_events(
        tmp_path,
        "project-a",
        {job.row_number: job},
        settings,
        (PronunciationAuditDraft(job.row_number, "decision_set", "normalized", ""),),
    )
    assert len(events) == 1
    assert events[0].action == "decision_set"
    assert events[0].decision_kind == "normalized"
    assert events[0].freshness == "current"
    assert events[0].previous_event_hash == service.CHAIN_GENESIS
    assert len(events[0].event_hash) == 64
    verification = service.verify(tmp_path, "project-a")
    assert verification.valid is True
    assert verification.event_count == 1
    assert verification.last_event_hash == events[0].event_hash


def test_a75_audit_event_excludes_raw_private_material(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    private_text = "PRIVATE-UTTERANCE-7319"
    job, settings = _recorded_job(text=private_text)
    service.append_events(
        tmp_path,
        "Private Project Name",
        {job.row_number: job},
        settings,
        (PronunciationAuditDraft(job.row_number, "decision_set", "normalized", ""),),
    )
    data = service.audit_path(tmp_path, "Private Project Name").read_text(encoding="utf-8")
    for forbidden in (
        private_text,
        "sk_PRIVATE_TEST_KEY",
        "voice-private-a",
        "model-private-a",
        "dictionary-private-a",
        "Private Project Name",
        "tyve kroner",
    ):
        assert forbidden not in data
    parsed = json.loads(data)
    assert parsed["provider"] == "elevenlabs"
    assert parsed["language"] == "da"
    assert parsed["context_fingerprint"]


def test_a75_multiple_events_form_append_only_chain(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    job, settings = _recorded_job()
    first = service.append_events(
        tmp_path,
        "project-a",
        {1: job},
        settings,
        (PronunciationAuditDraft(1, "decision_set", "normalized", ""),),
    )[0]
    second = service.append_events(
        tmp_path,
        "project-a",
        {1: job},
        settings,
        (PronunciationAuditDraft(1, "decision_revalidated", "normalized", "normalized"),),
    )[0]
    assert second.previous_event_hash == first.event_hash
    events = service.read_events(tmp_path, "project-a")
    assert [event.action for event in events] == ["decision_set", "decision_revalidated"]
    assert service.verify(tmp_path, "project-a").valid is True


def test_a75_tampering_is_detected_and_chain_is_not_silently_accepted(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    job, settings = _recorded_job()
    service.append_events(
        tmp_path,
        "project-a",
        {1: job},
        settings,
        (PronunciationAuditDraft(1, "decision_set", "normalized", ""),),
    )
    path = service.audit_path(tmp_path, "project-a")
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace('"decision_kind":"normalized"', '"decision_kind":"original"'), encoding="utf-8")
    verification = service.verify(tmp_path, "project-a")
    assert verification.valid is False
    try:
        service.append_events(
            tmp_path,
            "project-a",
            {1: job},
            settings,
            (PronunciationAuditDraft(1, "decision_revalidated", "normalized", "normalized"),),
        )
    except ValueError as exc:
        assert "invalid pronunciation audit chain" in str(exc)
    else:
        raise AssertionError("Tampered audit chain must reject append.")


def test_a75_stale_reason_reports_safe_context_dimension_without_raw_text(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    settings = _settings()
    job = _job(1, "EU")
    job.pronunciation_override = PronunciationAssuranceService().encode_review_decision("original", job, settings)
    event = service.append_events(
        tmp_path,
        "project-a",
        {1: job},
        settings,
        (PronunciationAuditDraft(1, "decision_set", "original", ""),),
    )[0]
    assert service.stale_reason(event, job, _settings(voice_id="voice-private-b")) == "voice changed"
    changed_text = _job(1, "DR", pronunciation_override=job.pronunciation_override)
    assert service.stale_reason(event, changed_text, settings) == "source text changed"


def test_a75_workspace_evidence_summarizes_events_and_per_row_history(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    job, settings = _recorded_job()
    service.append_events(
        tmp_path,
        "project-a",
        {1: job},
        settings,
        (
            PronunciationAuditDraft(1, "decision_set", "normalized", ""),
            PronunciationAuditDraft(1, "decision_revalidated", "normalized", "normalized"),
        ),
    )
    summary, rows = service.workspace_evidence(tmp_path, "project-a", (job,), settings)
    assert "2 event(s)" in summary
    assert "chain VERIFIED" in summary
    assert "revalidations 1" in summary
    assert rows[1]["count"] == 2
    assert rows[1]["last_action"] == "decision_revalidated"
    assert rows[1]["last_hash"]


def test_a75_report_is_readable_privacy_safe_evidence(tmp_path: Path) -> None:
    service = PronunciationAuditTrailService()
    job, settings = _recorded_job(text="PRIVATE-UTTERANCE-7319")
    service.append_events(
        tmp_path,
        "Private Project Name",
        {1: job},
        settings,
        (PronunciationAuditDraft(1, "decision_set", "normalized", ""),),
    )
    report = service.export_report(tmp_path, "Private Project Name", (job,), settings)
    text = report.read_text(encoding="utf-8")
    assert "# Pronunciation Decision Audit Evidence" in text
    assert "Audit chain: VERIFIED" in text
    assert "decision_set" in text
    assert "context" in text.lower()
    for forbidden in (
        "PRIVATE-UTTERANCE-7319",
        "sk_PRIVATE_TEST_KEY",
        "voice-private-a",
        "model-private-a",
        "dictionary-private-a",
        "Private Project Name",
        "tyve kroner",
    ):
        assert forbidden not in text


def test_a75_review_workspace_surfaces_audit_summary_row_evidence_and_export() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_review_dialog.py").read_text(encoding="utf-8")
    assert "auditExportRequested = Signal()" in source
    assert '"Audit evidence"' in source
    assert "Export audit evidence" in source
    assert "refresh_audit_evidence" in source
    assert "No audit event" in source


def test_a75_review_workspace_audit_controls_do_not_run_external_actions() -> None:
    source = (ROOT / "app/gui/dialogs/pronunciation_review_dialog.py").read_text(encoding="utf-8")
    for forbidden in (
        "create_provider(",
        "provider.synthesize",
        "run_preflight(",
        "generation_controller.start",
        "provider.setCurrentText",
        "voice.setText",
        "set_model_value",
        "set_language_value",
        "detect_language",
    ):
        assert forbidden not in source


def test_a75_main_centralizes_audit_for_decision_set_and_clear_with_rollback() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def set_pronunciation_override_for_rows")
    end = source.index("    def _open_language_probe_for_jobs", start)
    block = source[start:end]
    assert "PronunciationAuditDraft" in block
    assert "'decision_set'" in block
    assert "'decision_cleared'" in block
    assert "append_events" in block
    assert "rolled back because audit evidence could not be recorded" in block
    assert "invalidate_preflight()" in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block


def test_a75_main_revalidation_records_audit_without_changing_intent() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def pronunciation_review_revalidate")
    end = source.index("    def pronunciation_review_probe", start)
    block = source[start:end]
    assert "decision_revalidated" in block
    assert "encode_review_decision(decision,job,settings)" in block
    assert "append_events" in block
    assert "generation_controller.is_active" in block
    assert "decision=='normalized' and not assessment.normalization_safe" in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block


def test_a75_export_is_explicit_user_triggered_read_only_evidence() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "dialog.auditExportRequested.connect(self.export_pronunciation_audit_evidence)" in source
    start = source.index("    def export_pronunciation_audit_evidence")
    end = source.index("    def set_pronunciation_override_for_rows", start)
    block = source[start:end]
    assert "export_report" in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block
    assert "open_voice_browser(" not in block


def test_a75_audit_source_has_no_raw_text_field_or_automatic_authority() -> None:
    source = (ROOT / "app/services/pronunciation_audit_service.py").read_text(encoding="utf-8")
    assert '"text":' not in source
    assert '"original_text":' not in source
    assert '"normalized_text":' not in source
    for forbidden in (
        "detect_language",
        "langdetect",
        "auto_provider",
        "auto_voice",
        "auto_model",
        "auto_language",
        "cross_provider_failover",
        "create_provider(",
        "synthesize(",
    ):
        assert forbidden not in source


def test_a75_document_preserves_schema23_and_fixed_next_roadmap() -> None:
    text = (ROOT / "docs/PRONUNCIATION_DECISION_AUDIT_TRAIL_EVIDENCE_ROADMAP2_A75.md").read_text(encoding="utf-8")
    assert "Database schema 23 is unchanged" in text
    assert "A7.6 — Pronunciation Coverage & Project Readiness" in text
    assert "no automatic Preflight" in text
    assert "no automatic generation" in text


def test_a75_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/pronunciation_audit.py"),
        Path("app/services/pronunciation_audit_service.py"),
        Path("app/gui/dialogs/pronunciation_review_dialog.py"),
        Path("app/gui/main.py"),
        Path("docs/PRONUNCIATION_DECISION_AUDIT_TRAIL_EVIDENCE_ROADMAP2_A75.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
