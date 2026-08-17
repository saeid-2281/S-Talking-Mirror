from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.intelligent_tts_execution_service import (
    IntelligentTTSExecutionService,
)
from app.services.intelligent_tts_operations_intelligence_service import (
    IntelligentTTSOperationsIntelligenceService,
    IntelligentTTSOperationsIntegrityError,
)


CERTIFICATION_VERSION = "roadmap2-b6-v1"
EXPECTED_BASELINE_COMMIT = "134789743b749f68e2016ffc651d0a131bbf86e7"


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        provider="elevenlabs",
        active_api_profile_id="profile-production",
        voice_id="voice-da",
        model_id="eleven_v3",
        language_code="da",
        file_extension=".mp3",
        max_retries=4,
        generation_scope="entire_queue",
        execution_order="csv",
        api_key="B6-SECRET-MUST-NOT-PERSIST",
    )


def _check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "detail": detail,
        }
    )


def certify(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    service = IntelligentTTSOperationsIntelligenceService()
    jobs = [
        _Job(1, "one.mp3", "Dansk tekst."),
        _Job(2, "two.mp3", "English text."),
        _Job(3, "three.mp3", "Mere dansk."),
    ]
    binding = IntelligentTTSExecutionService().prepare(
        jobs,
        _settings(),
        output / "audio",
        job_language_overrides={2: "en"},
    )

    artifact = SimpleNamespace(
        verified_files=3,
        issue_count=0,
        status="verified",
        receipt_digest="artifact-digest-1",
    )
    receipt = SimpleNamespace(
        receipt_id="execution-receipt-1",
    )
    recovery = SimpleNamespace(
        parent_run_id="parent-run",
    )

    snapshot = service.observe_run(
        binding,
        run_id="operations-run-1",
        project_key="project-a",
        result="completed",
        summary={
            "completed": 3,
            "failed": 0,
            "skipped": 0,
        },
        monitor_metrics={
            "elapsed_seconds": 18.0,
            "retry_events": 1,
            "files_per_minute": 10.0,
            "characters_per_minute": 7200.0,
        },
        artifact_receipt=artifact,
        execution_receipt=receipt,
        recovery_assessment=recovery,
        evidence_root=output / "operations",
    )

    attention_artifact = SimpleNamespace(
        verified_files=1,
        issue_count=1,
        status="issues_detected",
        receipt_digest="artifact-digest-2",
    )
    service.observe_run(
        binding,
        run_id="operations-run-2",
        project_key="project-a",
        result="failed",
        summary={
            "completed": 1,
            "failed": 1,
            "skipped": 1,
        },
        monitor_metrics={
            "elapsed_seconds": 30.0,
            "retry_events": 2,
            "files_per_minute": 2.0,
            "characters_per_minute": 1600.0,
        },
        artifact_receipt=attention_artifact,
        execution_receipt=SimpleNamespace(
            receipt_id="execution-receipt-2"
        ),
        recovery_assessment=None,
        evidence_root=output / "operations",
    )
    rollup = service.rollup_project(
        output / "operations",
        "project-a",
    )

    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "binding_identity_preserved",
        snapshot.manifest_digest == binding.manifest_digest
        and snapshot.authority_digest == binding.authority_digest,
        snapshot.manifest_digest,
    )
    _check(
        checks,
        "explicit_authority_observed",
        snapshot.provider == binding.provider
        and snapshot.profile_id == binding.profile_id
        and snapshot.voice_id == binding.voice_id
        and snapshot.model_id == binding.model_id
        and snapshot.default_language == binding.default_language,
        "Provider/profile/voice/model/language remain observational.",
    )
    _check(
        checks,
        "run_counts_and_completion_rate",
        snapshot.completed == 3
        and snapshot.failed == 0
        and snapshot.skipped == 0
        and snapshot.completion_rate == 1.0,
        f"{snapshot.completed}/{snapshot.request_count}",
    )
    _check(
        checks,
        "throughput_metrics_observed",
        snapshot.elapsed_seconds == 18.0
        and snapshot.retry_events == 1
        and snapshot.files_per_minute == 10.0
        and snapshot.characters_per_minute == 7200.0,
        "Existing monitor metrics are copied without controlling execution.",
    )
    _check(
        checks,
        "artifact_integrity_signal_observed",
        snapshot.verified_files == 3
        and snapshot.artifact_issue_count == 0
        and snapshot.artifact_status == "verified",
        snapshot.artifact_status,
    )
    _check(
        checks,
        "receipt_link_observed",
        snapshot.execution_receipt_id == "execution-receipt-1"
        and snapshot.artifact_receipt_digest == "artifact-digest-1",
        str(snapshot.execution_receipt_id),
    )
    _check(
        checks,
        "resume_lineage_observed",
        snapshot.resume_run
        and snapshot.parent_run_id == "parent-run",
        str(snapshot.parent_run_id),
    )
    _check(
        checks,
        "healthy_run_classification",
        snapshot.health == "healthy",
        snapshot.health,
    )
    _check(
        checks,
        "project_rollup_aggregates_runs",
        rollup.total_runs == 2
        and rollup.request_count == 6
        and rollup.completed_jobs == 4
        and rollup.failed_jobs == 1
        and rollup.skipped_jobs == 1,
        f"{rollup.total_runs} runs / {rollup.request_count} requests",
    )
    _check(
        checks,
        "project_rollup_aggregates_integrity_and_retries",
        rollup.verified_files == 4
        and rollup.artifact_issue_count == 1
        and rollup.retry_events == 3
        and rollup.resume_runs == 1,
        f"{rollup.artifact_issue_count} issue(s)",
    )
    _check(
        checks,
        "project_health_surfaces_attention",
        rollup.health == "attention"
        and rollup.attention_runs == 1,
        rollup.health,
    )

    serialized = snapshot.path.read_text(encoding="utf-8")
    _check(
        checks,
        "privacy_safe_snapshot",
        "B6-SECRET-MUST-NOT-PERSIST" not in serialized
        and "Dansk tekst." not in serialized
        and "English text." not in serialized
        and "api_key" not in serialized,
        "No raw text or API key material is persisted.",
    )

    tampered = json.loads(serialized)
    tampered["failed"] = 99
    tamper_path = output / "tampered-operations.json"
    tamper_path.write_text(
        json.dumps(tampered, indent=2) + "\n",
        encoding="utf-8",
    )
    tamper_rejected = False
    try:
        service.load_snapshot(tamper_path)
    except IntelligentTTSOperationsIntegrityError:
        tamper_rejected = True
    _check(
        checks,
        "tamper_rejected",
        tamper_rejected,
        "Snapshot digest rejects modified evidence.",
    )

    service_source = inspect.getsource(
        IntelligentTTSOperationsIntelligenceService
    )
    forbidden = (
        "generation_controller.start",
        "run_preflight",
        "create_provider",
        "apply_smart_routing",
        "retry_failed",
        "detect_language",
        "unlink(",
        "rename(",
        "replace_output",
    )
    _check(
        checks,
        "no_execution_or_file_mutation_authority",
        all(token not in service_source for token in forbidden),
        "B6 observes and aggregates only.",
    )
    _check(
        checks,
        "database_schema_not_used",
        "database" not in serialized.casefold(),
        "Filesystem evidence only; schema 23 remains unchanged.",
    )

    failed_checks = [
        item for item in checks if not item["passed"]
    ]
    result = {
        "certification_version": CERTIFICATION_VERSION,
        "baseline_commit": EXPECTED_BASELINE_COMMIT,
        "status": "CERTIFIED" if not failed_checks else "FAILED",
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed_checks),
        "checks_failed": len(failed_checks),
        "checks": checks,
        "snapshot_path": str(snapshot.path),
        "snapshot_digest": snapshot.snapshot_digest,
        "rollup_path": str(rollup.path),
        "rollup_digest": rollup.rollup_digest,
    }
    (output / "certification.json").write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = certify(args.output)
    print(f"Roadmap 2 B6 certification: {result['status']}")
    print(
        f"Checks: {result['checks_passed']}/{result['checks_total']}"
    )
    print(f"Snapshot digest: {result['snapshot_digest']}")
    print(f"Rollup digest: {result['rollup_digest']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
