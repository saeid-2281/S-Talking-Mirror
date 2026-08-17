from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionService
from app.services.intelligent_tts_recovery_continuity_service import (
    IntelligentTTSRecoveryContinuityService,
)
from app.services.intelligent_tts_run_ledger_service import IntelligentTTSRunLedgerService


CERTIFICATION_VERSION = "roadmap2-b4-v1"
EXPECTED_BASELINE_COMMIT = "9ddf1b06d80c441699cb129ace88874cbc3f4cbe"


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        provider="elevenlabs",
        active_api_profile_id="profile-1",
        voice_id="voice-da",
        model_id="eleven_v3",
        language_code="da",
        file_extension=".mp3",
        max_retries=4,
        generation_scope="selected",
        execution_order="csv",
        api_key="B4-SECRET-MUST-NOT-PERSIST",
    )


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def certify(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    jobs = [
        _Job(1, "a.mp3", "Dansk tekst."),
        _Job(2, "b.mp3", "English text."),
    ]
    binding = IntelligentTTSExecutionService().prepare(
        jobs,
        _settings(),
        output / "audio",
        job_language_overrides={2: "en"},
    )
    ledger_service = IntelligentTTSRunLedgerService()
    continuity = IntelligentTTSRecoveryContinuityService(ledger_service)
    ledger_root = output / "ledger"

    parent = ledger_service.begin(
        binding,
        run_id="parent-run",
        project_key="project-a",
        evidence_root=ledger_root,
    )
    parent = ledger_service.record_status(parent.path, "running")
    parent = ledger_service.finalize(
        parent.path,
        "failed",
        summary={"completed": 1, "failed": 1, "skipped": 0},
    )

    assessment = continuity.assess_resume(
        evidence_root=ledger_root,
        project_key="project-a",
        parent_run_id="parent-run",
        resume_receipt_id="resume-1",
        resume_receipt_path=output / "resume-1.json",
    )
    child = ledger_service.begin(
        binding,
        run_id="child-run",
        project_key="project-a",
        evidence_root=ledger_root,
    )
    child = continuity.attach_child(child.path, assessment)
    child = ledger_service.record_status(child.path, "running")

    checks: list[dict[str, Any]] = []
    _check(checks, "parent_ledger_verified", assessment.verified, assessment.continuity_status)
    _check(
        checks,
        "parent_digest_linked",
        assessment.parent_ledger_digest == parent.ledger_digest,
        str(assessment.parent_ledger_digest),
    )
    _check(checks, "parent_status_linked", assessment.parent_status == "failed", str(assessment.parent_status))
    _check(
        checks,
        "resume_receipt_linked",
        assessment.resume_receipt_id == "resume-1"
        and str(assessment.resume_receipt_path).endswith("resume-1.json"),
        str(assessment.resume_receipt_path),
    )
    _check(
        checks,
        "child_lineage_event_recorded",
        [event.event_type for event in child.events] == ["approved", "recovery_lineage", "running"],
        str([event.event_type for event in child.events]),
    )
    _check(checks, "child_hash_chain_verifies", ledger_service.verify(child.path), child.ledger_digest)
    _check(
        checks,
        "child_references_parent_digest",
        child.events[1].payload["parent_ledger_digest"] == parent.ledger_digest,
        str(child.events[1].payload["parent_ledger_digest"]),
    )
    serialized = child.path.read_text(encoding="utf-8")
    _check(
        checks,
        "privacy_preserved",
        "B4-SECRET-MUST-NOT-PERSIST" not in serialized
        and "Dansk tekst." not in serialized
        and "api_key" not in serialized,
        "No raw source text or API key material is persisted.",
    )

    missing = continuity.assess_resume(
        evidence_root=ledger_root,
        project_key="project-a",
        parent_run_id="missing-run",
        resume_receipt_id="resume-missing",
        resume_receipt_path=output / "resume-missing.json",
    )
    _check(
        checks,
        "missing_parent_is_explicit",
        missing.continuity_status == "parent_ledger_missing" and missing.parent_ledger_digest is None,
        missing.continuity_status,
    )

    open_ledger = ledger_service.begin(
        binding,
        run_id="interrupted-run",
        project_key="project-a",
        evidence_root=ledger_root,
    )
    open_ledger = ledger_service.record_status(open_ledger.path, "running")
    interrupted = continuity.discover_interrupted(ledger_root)
    _check(
        checks,
        "nonterminal_discovery",
        any(item.run_id == open_ledger.run_id for item in interrupted),
        str([item.run_id for item in interrupted]),
    )
    _check(
        checks,
        "terminal_parent_not_interrupted",
        all(item.run_id != parent.run_id for item in interrupted),
        str([item.run_id for item in interrupted]),
    )

    source = inspect.getsource(
        __import__(
            "app.services.intelligent_tts_recovery_continuity_service",
            fromlist=["IntelligentTTSRecoveryContinuityService"],
        )
    )
    forbidden = (
        "generation_controller.start",
        "start_generation",
        "run_preflight",
        "create_provider",
        "apply_smart_routing",
        "detect_language",
        "retry_failed",
        "prepare_jobs",
    )
    _check(
        checks,
        "no_execution_authority",
        all(token not in source for token in forbidden),
        "Continuity is evidence-only.",
    )
    _check(
        checks,
        "binding_authority_unchanged",
        child.provider == binding.provider
        and child.profile_id == binding.profile_id
        and child.voice_id == binding.voice_id
        and child.model_id == binding.model_id
        and child.default_language == binding.default_language,
        "Child ledger preserves B2 authority.",
    )
    _check(checks, "database_schema_not_used", "database" not in serialized.casefold(), "Filesystem evidence only.")
    second = continuity.attach_child(child.path, assessment)
    _check(
        checks,
        "lineage_attachment_idempotent",
        second.ledger_digest == child.ledger_digest and len(second.events) == len(child.events),
        second.ledger_digest,
    )

    failed = [item for item in checks if not item["passed"]]
    result = {
        "certification_version": CERTIFICATION_VERSION,
        "baseline_commit": EXPECTED_BASELINE_COMMIT,
        "status": "CERTIFIED" if not failed else "FAILED",
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "checks": checks,
        "child_ledger_path": str(child.path),
        "child_ledger_digest": child.ledger_digest,
    }
    (output / "certification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = certify(args.output)
    print(f"Roadmap 2 B4 certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Child ledger digest: {result['child_ledger_digest']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
