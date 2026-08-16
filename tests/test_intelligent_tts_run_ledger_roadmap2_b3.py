from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionService
from app.services.intelligent_tts_run_ledger_service import (
    RUN_LEDGER_SCHEMA_VERSION,
    IntelligentTTSRunLedgerIntegrityError,
    IntelligentTTSRunLedgerService,
    IntelligentTTSRunLedgerTransitionError,
)
from scripts.certify_intelligent_tts_run_ledger_roadmap2_b3 import (
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
        "api_key": "TOP-SECRET",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def _jobs():
    return [
        _Job(1, "a.mp3", "Dansk tekst."),
        _Job(2, "b.mp3", "English text."),
        _Job(3, "c.mp3", "Mere dansk."),
    ]


def _binding(tmp_path: Path):
    return IntelligentTTSExecutionService().prepare(
        _jobs(),
        _settings(),
        tmp_path / "audio",
        job_language_overrides={2: "en"},
    )


def test_b3_locks_to_b2_hotfix3_certified_baseline() -> None:
    assert EXPECTED_BASELINE_COMMIT == "6ee5b9710e27ab6fd302a0d0ab21fd32d10bf659"
    assert CERTIFICATION_VERSION == "roadmap2-b3-v1"
    assert RUN_LEDGER_SCHEMA_VERSION == 1


def test_b3_begin_persists_b2_binding_identity(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    ledger = IntelligentTTSRunLedgerService().begin(binding, run_id="run-1", project_key="project-1", evidence_root=tmp_path / "ledger")
    assert ledger.manifest_digest == binding.manifest_digest
    assert ledger.authority_digest == binding.authority_digest
    assert ledger.request_ids == binding.request_ids
    assert ledger.row_numbers == binding.row_numbers


def test_b3_begin_preserves_explicit_provider_authority(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    ledger = IntelligentTTSRunLedgerService().begin(binding, run_id="run-2", project_key="project-2", evidence_root=tmp_path / "ledger")
    assert ledger.provider == "elevenlabs"
    assert ledger.profile_id == "profile-1"
    assert ledger.voice_id == "voice-1"
    assert ledger.model_id == "model-1"
    assert ledger.default_language == "da"


def test_b3_ledger_never_serializes_source_text_or_api_key(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    ledger = IntelligentTTSRunLedgerService().begin(binding, run_id="run-private", project_key="private", evidence_root=tmp_path / "ledger")
    serialized = ledger.path.read_text(encoding="utf-8")
    assert "Dansk tekst." not in serialized
    assert "English text." not in serialized
    assert "TOP-SECRET" not in serialized
    assert "api_key" not in serialized


def test_b3_lifecycle_events_form_a_verified_hash_chain(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-chain", project_key="chain", evidence_root=tmp_path / "ledger")
    ledger = service.record_status(ledger.path, "running")
    ledger = service.record_status(ledger.path, "paused")
    ledger = service.record_status(ledger.path, "running")
    ledger = service.record_status(ledger.path, "stopping")
    assert service.verify(ledger.path)
    assert [event.event_type for event in ledger.events] == ["approved", "running", "paused", "running", "stopping"]
    for previous, current in zip(ledger.events, ledger.events[1:]):
        assert current.previous_digest == previous.event_digest


def test_b3_runtime_metrics_are_allowlisted(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-metrics", project_key="metrics", evidence_root=tmp_path / "ledger")
    ledger = service.record_status(ledger.path, "running", metrics={"elapsed_seconds": 2.5, "retry_events": 1, "secret_metric": "do-not-store"})
    event = ledger.events[-1]
    assert event.payload["elapsed_seconds"] == 2.5
    assert event.payload["retry_events"] == 1
    assert "secret_metric" not in event.payload


def test_b3_completed_run_reconciles_exactly(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-complete", project_key="complete", evidence_root=tmp_path / "ledger")
    ledger = service.record_status(ledger.path, "running")
    ledger = service.finalize(ledger.path, "completed", summary={"completed": 3, "failed": 0, "skipped": 0})
    reconciliation = ledger.events[-1].payload["outcome_reconciliation"]
    assert reconciliation["status"] == "exact"
    assert reconciliation["unaccounted"] == 0


def test_b3_cancelled_before_start_does_not_invent_failures(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-cancelled", project_key="cancelled", evidence_root=tmp_path / "ledger")
    ledger = service.finalize(ledger.path, "cancelled", summary=None)
    reconciliation = ledger.events[-1].payload["outcome_reconciliation"]
    assert reconciliation["status"] == "cancelled_unexecuted"
    assert reconciliation["failed"] == 0
    assert reconciliation["unaccounted"] == 3


def test_b3_partial_accounting_is_explicit(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-failed", project_key="failed", evidence_root=tmp_path / "ledger")
    ledger = service.record_status(ledger.path, "running")
    ledger = service.finalize(ledger.path, "failed", summary={"completed": 0, "failed": 1, "skipped": 0})
    reconciliation = ledger.events[-1].payload["outcome_reconciliation"]
    assert reconciliation["status"] == "partial_accounting"
    assert reconciliation["unaccounted"] == 2


def test_b3_final_event_links_existing_execution_evidence(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-links", project_key="links", evidence_root=tmp_path / "ledger")
    ledger = service.finalize(ledger.path, "completed", summary={"completed": 3}, execution_session_path=tmp_path / "session.json", execution_receipt_path=tmp_path / "receipt.json", report_path=tmp_path / "report.html")
    payload = ledger.events[-1].payload
    assert payload["execution_session_path"].endswith("session.json")
    assert payload["execution_receipt_path"].endswith("receipt.json")
    assert payload["report_path"].endswith("report.html")


def test_b3_tampering_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-tamper", project_key="tamper", evidence_root=tmp_path / "ledger")
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["voice_id"] = "tampered"
    ledger.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IntelligentTTSRunLedgerIntegrityError):
        service.load(ledger.path)


def test_b3_terminal_transition_is_idempotent_for_same_result(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-idempotent", project_key="idempotent", evidence_root=tmp_path / "ledger")
    first = service.finalize(ledger.path, "completed", summary={"completed": 3})
    second = service.finalize(ledger.path, "completed", summary={"completed": 3})
    assert first.ledger_digest == second.ledger_digest
    assert len(first.events) == len(second.events)


def test_b3_terminal_result_cannot_be_changed(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="run-terminal", project_key="terminal", evidence_root=tmp_path / "ledger")
    ledger = service.finalize(ledger.path, "failed", summary={"failed": 1})
    with pytest.raises(IntelligentTTSRunLedgerTransitionError):
        service.finalize(ledger.path, "completed", summary={"completed": 3})


def test_b3_begin_is_idempotent_for_same_run_and_binding(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    service = IntelligentTTSRunLedgerService()
    first = service.begin(binding, run_id="same-run", project_key="same-project", evidence_root=tmp_path / "ledger")
    second = service.begin(binding, run_id="same-run", project_key="same-project", evidence_root=tmp_path / "ledger")
    assert first.path == second.path
    assert first.ledger_digest == second.ledger_digest


def test_b3_record_status_rejects_terminal_transition_api(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(_binding(tmp_path), run_id="terminal-api", project_key="terminal-api", evidence_root=tmp_path / "ledger")
    with pytest.raises(IntelligentTTSRunLedgerTransitionError):
        service.record_status(ledger.path, "completed")


def test_b3_certification_is_machine_verifiable(tmp_path: Path) -> None:
    result = certify(tmp_path / "cert")
    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert result["checks_total"] == 15
    assert (tmp_path / "cert" / "certification.json").is_file()
