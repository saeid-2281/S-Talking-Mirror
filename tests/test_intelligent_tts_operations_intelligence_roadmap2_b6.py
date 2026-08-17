from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.intelligent_tts_execution_service import (
    IntelligentTTSExecutionService,
)
from app.services.intelligent_tts_operations_intelligence_service import (
    OPERATIONS_ROLLUP_SCHEMA_VERSION,
    OPERATIONS_SNAPSHOT_SCHEMA_VERSION,
    IntelligentTTSOperationsIntelligenceError,
    IntelligentTTSOperationsIntelligenceService,
    IntelligentTTSOperationsIntegrityError,
)
from scripts.certify_intelligent_tts_operations_intelligence_roadmap2_b6 import (
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
        generation_scope="entire_queue",
        execution_order="csv",
        api_key="SECRET",
    )


def _binding(tmp_path: Path):
    return IntelligentTTSExecutionService().prepare(
        [
            _Job(1, "a.mp3", "Dansk."),
            _Job(2, "b.mp3", "English."),
        ],
        _settings(),
        tmp_path / "audio",
        job_language_overrides={2: "en"},
    )


def _artifact(
    *,
    verified_files: int = 2,
    issue_count: int = 0,
    status: str = "verified",
    digest: str = "artifact-digest",
):
    return SimpleNamespace(
        verified_files=verified_files,
        issue_count=issue_count,
        status=status,
        receipt_digest=digest,
    )


def _observe(
    tmp_path: Path,
    service: IntelligentTTSOperationsIntelligenceService,
    *,
    run_id: str = "run-1",
    result: str = "completed",
    completed: int = 2,
    failed: int = 0,
    skipped: int = 0,
    artifact=None,
    recovery=None,
):
    return service.observe_run(
        _binding(tmp_path),
        run_id=run_id,
        project_key="project",
        result=result,
        summary={
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        },
        monitor_metrics={
            "elapsed_seconds": 12.0,
            "retry_events": 1,
            "files_per_minute": 10.0,
            "characters_per_minute": 5000.0,
        },
        artifact_receipt=artifact or _artifact(),
        execution_receipt=SimpleNamespace(
            receipt_id=f"receipt-{run_id}"
        ),
        recovery_assessment=recovery,
        evidence_root=tmp_path / "operations",
    )


def test_b6_locks_to_b5_certified_baseline() -> None:
    assert EXPECTED_BASELINE_COMMIT == (
        "134789743b749f68e2016ffc651d0a131bbf86e7"
    )
    assert CERTIFICATION_VERSION == "roadmap2-b6-v1"
    assert OPERATIONS_SNAPSHOT_SCHEMA_VERSION == 1
    assert OPERATIONS_ROLLUP_SCHEMA_VERSION == 1


def test_b6_snapshot_preserves_b2_binding_identity(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    binding = _binding(tmp_path)
    snapshot = service.observe_run(
        binding,
        run_id="identity",
        project_key="project",
        result="completed",
        summary={"completed": 2},
        monitor_metrics={},
        artifact_receipt=_artifact(),
        execution_receipt=None,
        recovery_assessment=None,
        evidence_root=tmp_path / "operations",
    )
    assert snapshot.manifest_digest == binding.manifest_digest
    assert snapshot.authority_digest == binding.authority_digest
    assert snapshot.provider == binding.provider
    assert snapshot.voice_id == binding.voice_id
    assert snapshot.model_id == binding.model_id
    assert snapshot.default_language == binding.default_language


def test_b6_snapshot_observes_counts_and_throughput(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    snapshot = _observe(tmp_path, service)
    assert snapshot.request_count == 2
    assert snapshot.completed == 2
    assert snapshot.completion_rate == 1.0
    assert snapshot.elapsed_seconds == 12.0
    assert snapshot.retry_events == 1
    assert snapshot.files_per_minute == 10.0
    assert snapshot.characters_per_minute == 5000.0


def test_b6_snapshot_observes_artifact_integrity(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    snapshot = _observe(
        tmp_path,
        service,
        artifact=_artifact(
            verified_files=1,
            issue_count=2,
            status="issues_detected",
        ),
    )
    assert snapshot.verified_files == 1
    assert snapshot.artifact_issue_count == 2
    assert snapshot.artifact_status == "issues_detected"
    assert snapshot.health == "attention"


def test_b6_snapshot_observes_resume_lineage(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    snapshot = _observe(
        tmp_path,
        service,
        recovery=SimpleNamespace(parent_run_id="parent-run"),
    )
    assert snapshot.resume_run is True
    assert snapshot.parent_run_id == "parent-run"


def test_b6_snapshot_is_privacy_safe(tmp_path: Path) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    snapshot = _observe(tmp_path, service)
    serialized = snapshot.path.read_text(encoding="utf-8")
    assert "SECRET" not in serialized
    assert "Dansk." not in serialized
    assert "English." not in serialized
    assert "api_key" not in serialized


def test_b6_same_run_finalization_is_idempotent(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    first = _observe(tmp_path, service)
    second = _observe(tmp_path, service)
    assert first.path == second.path
    assert first.snapshot_digest == second.snapshot_digest


def test_b6_different_evidence_cannot_replace_existing_snapshot(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    _observe(tmp_path, service)
    with pytest.raises(IntelligentTTSOperationsIntelligenceError):
        _observe(
            tmp_path,
            service,
            result="failed",
            completed=0,
            failed=1,
        )


def test_b6_tampered_snapshot_is_rejected(tmp_path: Path) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    snapshot = _observe(tmp_path, service)
    payload = json.loads(snapshot.path.read_text(encoding="utf-8"))
    payload["failed"] = 99
    snapshot.path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(IntelligentTTSOperationsIntegrityError):
        service.load_snapshot(snapshot.path)


def test_b6_project_rollup_aggregates_runs(tmp_path: Path) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    _observe(tmp_path, service, run_id="run-1")
    _observe(
        tmp_path,
        service,
        run_id="run-2",
        result="failed",
        completed=1,
        failed=1,
        artifact=_artifact(
            verified_files=1,
            issue_count=1,
            status="issues_detected",
            digest="artifact-2",
        ),
    )
    rollup = service.rollup_project(
        tmp_path / "operations",
        "project",
    )
    assert rollup.total_runs == 2
    assert rollup.request_count == 4
    assert rollup.completed_jobs == 3
    assert rollup.failed_jobs == 1
    assert rollup.verified_files == 3
    assert rollup.artifact_issue_count == 1
    assert rollup.retry_events == 2


def test_b6_rollup_surfaces_attention_without_auto_action(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    _observe(
        tmp_path,
        service,
        artifact=_artifact(
            issue_count=1,
            status="issues_detected",
        ),
    )
    rollup = service.rollup_project(
        tmp_path / "operations",
        "project",
    )
    assert rollup.health == "attention"
    assert rollup.attention_runs == 1


def test_b6_rollup_counts_invalid_snapshot_evidence(
    tmp_path: Path,
) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    _observe(tmp_path, service)
    bad = (
        service.project_dir(
            tmp_path / "operations",
            "project",
        )
        / "bad.intelligent-tts-operations.json"
    )
    bad.write_text('{"bad":true}\n', encoding="utf-8")
    rollup = service.rollup_project(
        tmp_path / "operations",
        "project",
    )
    assert rollup.invalid_snapshot_count == 1
    assert rollup.health == "attention"


def test_b6_empty_rollup_is_explicit(tmp_path: Path) -> None:
    service = IntelligentTTSOperationsIntelligenceService()
    rollup = service.rollup_project(
        tmp_path / "operations",
        "empty-project",
    )
    assert rollup.total_runs == 0
    assert rollup.health == "empty"
    assert rollup.completion_rate == 0.0


def test_b6_certification_is_machine_verifiable(
    tmp_path: Path,
) -> None:
    result = certify(tmp_path / "cert")
    assert result["status"] == "CERTIFIED"
    assert result["checks_failed"] == 0
    assert result["checks_total"] == 15
    assert (tmp_path / "cert" / "certification.json").is_file()
