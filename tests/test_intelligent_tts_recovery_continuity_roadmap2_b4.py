from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionService
from app.services.intelligent_tts_recovery_continuity_service import (
    IntelligentTTSRecoveryContinuityService,
)
from app.services.intelligent_tts_run_ledger_service import (
    IntelligentTTSRunLedgerService,
    IntelligentTTSRunLedgerTransitionError,
)
from scripts.certify_intelligent_tts_recovery_continuity_roadmap2_b4 import (
    CERTIFICATION_VERSION,
    EXPECTED_BASELINE_COMMIT,
    certify,
)


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _settings():
    return SimpleNamespace(
        provider="elevenlabs",
        active_api_profile_id="profile-1",
        voice_id="voice-1",
        model_id="model-1",
        language_code="da",
        file_extension=".mp3",
        max_retries=4,
        generation_scope="selected",
        execution_order="csv",
        api_key="SECRET",
    )


def _binding(tmp_path: Path):
    return IntelligentTTSExecutionService().prepare(
        [_Job(1, "a.mp3", "Dansk."), _Job(2, "b.mp3", "English.")],
        _settings(),
        tmp_path / "audio",
        job_language_overrides={2: "en"},
    )


def _parent(tmp_path: Path, service: IntelligentTTSRunLedgerService):
    ledger = service.begin(
        _binding(tmp_path),
        run_id="parent-run",
        project_key="project",
        evidence_root=tmp_path / "ledger",
    )
    ledger = service.record_status(ledger.path, "running")
    return service.finalize(
        ledger.path,
        "failed",
        summary={"completed": 1, "failed": 1},
    )


def test_b4_locks_to_b3_certified_baseline() -> None:
    assert EXPECTED_BASELINE_COMMIT == "9ddf1b06d80c441699cb129ace88874cbc3f4cbe"
    assert CERTIFICATION_VERSION == "roadmap2-b4-v1"


def test_b4_path_for_is_deterministic_and_scoped(tmp_path: Path) -> None:
    service = IntelligentTTSRunLedgerService()
    first = service.path_for(tmp_path, "Project / A", "Run : 1")
    second = service.path_for(tmp_path, "Project / A", "Run : 1")
    assert first == second
    assert first.parent.name == "Project-A"
    assert first.name == "Run-1.intelligent-tts-ledger.json"


def test_b4_assess_resume_verifies_parent(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    parent = _parent(tmp_path, ledgers)
    service = IntelligentTTSRecoveryContinuityService(ledgers)
    assessment = service.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume-1",
        resume_receipt_path=tmp_path / "resume.json",
    )
    assert assessment.verified
    assert assessment.parent_ledger_digest == parent.ledger_digest
    assert assessment.parent_status == "failed"


def test_b4_missing_parent_is_explicit(tmp_path: Path) -> None:
    assessment = IntelligentTTSRecoveryContinuityService().assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="missing",
        resume_receipt_id="resume",
        resume_receipt_path=tmp_path / "resume.json",
    )
    assert assessment.continuity_status == "parent_ledger_missing"
    assert assessment.parent_ledger_digest is None


def test_b4_invalid_parent_is_explicit(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    parent = _parent(tmp_path, ledgers)
    payload = json.loads(parent.path.read_text(encoding="utf-8"))
    payload["provider"] = "tampered"
    parent.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assessment = IntelligentTTSRecoveryContinuityService(ledgers).assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume",
        resume_receipt_path=tmp_path / "resume.json",
    )
    assert assessment.continuity_status == "parent_ledger_invalid"
    assert assessment.parent_ledger_digest is None


def test_b4_child_lineage_records_parent_and_resume(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    parent = _parent(tmp_path, ledgers)
    continuity = IntelligentTTSRecoveryContinuityService(ledgers)
    assessment = continuity.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume-7",
        resume_receipt_path=tmp_path / "resume-7.json",
    )
    child = ledgers.begin(
        _binding(tmp_path), run_id="child", project_key="project", evidence_root=tmp_path / "ledger"
    )
    child = continuity.attach_child(child.path, assessment)
    assert child.events[-1].event_type == "recovery_lineage"
    assert child.events[-1].payload["parent_ledger_digest"] == parent.ledger_digest
    assert child.events[-1].payload["resume_receipt_id"] == "resume-7"


def test_b4_lineage_preserves_hash_chain(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    _parent(tmp_path, ledgers)
    continuity = IntelligentTTSRecoveryContinuityService(ledgers)
    assessment = continuity.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume",
        resume_receipt_path=tmp_path / "resume.json",
    )
    child = ledgers.begin(
        _binding(tmp_path), run_id="child", project_key="project", evidence_root=tmp_path / "ledger"
    )
    continuity.attach_child(child.path, assessment)
    assert ledgers.verify(child.path)


def test_b4_same_lineage_is_idempotent(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    _parent(tmp_path, ledgers)
    continuity = IntelligentTTSRecoveryContinuityService(ledgers)
    assessment = continuity.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume",
        resume_receipt_path=tmp_path / "resume.json",
    )
    child = ledgers.begin(
        _binding(tmp_path), run_id="child", project_key="project", evidence_root=tmp_path / "ledger"
    )
    first = continuity.attach_child(child.path, assessment)
    second = continuity.attach_child(child.path, assessment)
    assert first.ledger_digest == second.ledger_digest
    assert len(first.events) == len(second.events)


def test_b4_different_lineage_cannot_replace_existing(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    _parent(tmp_path, ledgers)
    continuity = IntelligentTTSRecoveryContinuityService(ledgers)
    first_assessment = continuity.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume-1",
        resume_receipt_path=tmp_path / "resume-1.json",
    )
    child = ledgers.begin(
        _binding(tmp_path), run_id="child", project_key="project", evidence_root=tmp_path / "ledger"
    )
    continuity.attach_child(child.path, first_assessment)
    changed = continuity.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume-2",
        resume_receipt_path=tmp_path / "resume-2.json",
    )
    with pytest.raises(IntelligentTTSRunLedgerTransitionError):
        continuity.attach_child(child.path, changed)


def test_b4_discover_interrupted_only_returns_nonterminal(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    binding = _binding(tmp_path)
    open_ledger = ledgers.begin(
        binding, run_id="open", project_key="project", evidence_root=tmp_path / "ledger"
    )
    open_ledger = ledgers.record_status(open_ledger.path, "running")
    closed = ledgers.begin(
        binding, run_id="closed", project_key="project", evidence_root=tmp_path / "ledger"
    )
    ledgers.finalize(closed.path, "completed", summary={"completed": 2})
    assert [item.run_id for item in ledgers.discover_open(tmp_path / "ledger")] == [open_ledger.run_id]


def test_b4_discover_interrupted_skips_tampered(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    ledger = ledgers.begin(
        _binding(tmp_path), run_id="tampered", project_key="project", evidence_root=tmp_path / "ledger"
    )
    payload = json.loads(ledger.path.read_text(encoding="utf-8"))
    payload["model_id"] = "changed"
    ledger.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert ledgers.discover_open(tmp_path / "ledger") == ()


def test_b4_lineage_is_privacy_safe(tmp_path: Path) -> None:
    ledgers = IntelligentTTSRunLedgerService()
    _parent(tmp_path, ledgers)
    continuity = IntelligentTTSRecoveryContinuityService(ledgers)
    assessment = continuity.assess_resume(
        evidence_root=tmp_path / "ledger",
        project_key="project",
        parent_run_id="parent-run",
        resume_receipt_id="resume",
        resume_receipt_path=tmp_path / "resume.json",
    )
    child = ledgers.begin(
        _binding(tmp_path), run_id="child-private", project_key="project", evidence_root=tmp_path / "ledger"
    )
    child = continuity.attach_child(child.path, assessment)
    serialized = child.path.read_text(encoding="utf-8")
    assert "SECRET" not in serialized
    assert "Dansk." not in serialized
    assert "English." not in serialized
    assert "api_key" not in serialized


def test_b4_continuity_does_not_change_b2_authority(tmp_path: Path) -> None:
    binding = _binding(tmp_path)
    child = IntelligentTTSRunLedgerService().begin(
        binding, run_id="authority", project_key="project", evidence_root=tmp_path / "ledger"
    )
    assert child.provider == binding.provider
    assert child.profile_id == binding.profile_id
    assert child.voice_id == binding.voice_id
    assert child.model_id == binding.model_id
    assert child.default_language == binding.default_language


def test_b4_certification_is_machine_verifiable(tmp_path: Path) -> None:
    result = certify(tmp_path / "cert")
    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert result["checks_total"] == 15
