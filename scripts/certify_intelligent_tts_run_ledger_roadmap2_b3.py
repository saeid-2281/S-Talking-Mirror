from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionService
from app.services.intelligent_tts_run_ledger_service import (
    IntelligentTTSRunLedgerIntegrityError,
    IntelligentTTSRunLedgerService,
)


CERTIFICATION_VERSION = "roadmap2-b3-v1"
EXPECTED_BASELINE_COMMIT = "6ee5b9710e27ab6fd302a0d0ab21fd32d10bf659"


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        provider="elevenlabs",
        active_api_profile_id="production-profile",
        voice_id="voice-da",
        model_id="eleven_v3",
        language_code="da",
        file_extension=".mp3",
        max_retries=4,
        generation_scope="entire_queue",
        execution_order="csv",
        api_key="B3-CERTIFICATION-SECRET",
    )


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def certify(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    jobs = [
        _Job(1, "one.mp3", "Dansk produktionstekst."),
        _Job(2, "two.mp3", "Explicit English text."),
        _Job(3, "three.mp3", "Mere dansk tekst."),
    ]
    binding = IntelligentTTSExecutionService().prepare(
        jobs,
        _settings(),
        output / "audio",
        job_language_overrides={2: "en"},
    )
    service = IntelligentTTSRunLedgerService()
    ledger = service.begin(
        binding,
        run_id="b3-certification-run",
        project_key="certification-project",
        evidence_root=output / "ledger",
    )
    ledger = service.record_status(
        ledger.path,
        "running",
        metrics={
            "elapsed_seconds": 1.5,
            "retry_events": 0,
            "private": "must-not-persist",
        },
    )
    ledger = service.record_status(ledger.path, "paused", metrics={"paused_time": 2.0})
    ledger = service.record_status(ledger.path, "running", metrics={"elapsed_seconds": 4.0})
    ledger = service.finalize(
        ledger.path,
        "completed",
        summary={"completed": 3, "failed": 0, "skipped": 0},
        execution_session_path=output / "session.json",
        execution_receipt_path=output / "receipt.json",
        report_path=output / "report.html",
    )

    checks: list[dict[str, Any]] = []
    _check(checks, "binding_identity_persisted", ledger.manifest_digest == binding.manifest_digest and ledger.authority_digest == binding.authority_digest, ledger.manifest_digest)
    _check(checks, "request_order_persisted", ledger.request_ids == binding.request_ids and ledger.row_numbers == binding.row_numbers, str(ledger.row_numbers))
    _check(checks, "explicit_authority_persisted", ledger.provider == binding.provider and ledger.profile_id == binding.profile_id and ledger.voice_id == binding.voice_id and ledger.model_id == binding.model_id and ledger.default_language == binding.default_language, "Provider/profile/voice/model/language match B2 binding.")
    _check(checks, "lifecycle_is_hash_chained", [event.event_type for event in ledger.events] == ["approved", "running", "paused", "running", "finalized"] and service.verify(ledger.path), ledger.ledger_digest)
    reconciliation = ledger.events[-1].payload["outcome_reconciliation"]
    _check(checks, "completed_outcome_reconciles_exactly", reconciliation["status"] == "exact", json.dumps(reconciliation, sort_keys=True))
    serialized = ledger.path.read_text(encoding="utf-8")
    _check(checks, "api_secret_not_persisted", "B3-CERTIFICATION-SECRET" not in serialized and "api_key" not in serialized, "No API key field or secret value is present.")
    _check(checks, "source_text_not_persisted", "Dansk produktionstekst." not in serialized and "Explicit English text." not in serialized, "Ledger persists request ids/digests rather than raw source text.")
    _check(checks, "unapproved_metric_is_not_persisted", "must-not-persist" not in serialized and '"private"' not in serialized, "Only allow-listed operational metrics are recorded.")
    final_payload = ledger.events[-1].payload
    _check(checks, "execution_paths_are_linked", str(final_payload["execution_session_path"]).endswith("session.json") and str(final_payload["execution_receipt_path"]).endswith("receipt.json") and str(final_payload["report_path"]).endswith("report.html"), "Final event links session, receipt and report evidence.")
    _check(checks, "terminal_status_is_completed", ledger.status == "completed", ledger.status)

    tamper_path = output / "tampered-ledger.json"
    tampered = json.loads(serialized)
    tampered["provider"] = "tampered-provider"
    tamper_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tamper_rejected = False
    try:
        service.load(tamper_path)
    except IntelligentTTSRunLedgerIntegrityError:
        tamper_rejected = True
    _check(checks, "tamper_is_rejected", tamper_rejected, "Top-level ledger digest rejects modified persisted evidence.")

    cancelled = service.begin(binding, run_id="b3-cancelled-run", project_key="certification-project", evidence_root=output / "ledger")
    cancelled = service.finalize(cancelled.path, "cancelled", summary=None)
    cancelled_reconciliation = cancelled.events[-1].payload["outcome_reconciliation"]
    _check(checks, "prestart_cancel_reconciles_without_fake_failures", cancelled_reconciliation["status"] == "cancelled_unexecuted", json.dumps(cancelled_reconciliation, sort_keys=True))

    failed = service.begin(binding, run_id="b3-failed-run", project_key="certification-project", evidence_root=output / "ledger")
    failed = service.record_status(failed.path, "running")
    failed = service.finalize(failed.path, "failed", summary={"completed": 0, "failed": 1, "skipped": 0})
    failed_reconciliation = failed.events[-1].payload["outcome_reconciliation"]
    _check(checks, "partial_accounting_is_visible_not_fabricated", failed_reconciliation["status"] == "partial_accounting" and failed_reconciliation["unaccounted"] == 2, json.dumps(failed_reconciliation, sort_keys=True))
    _check(checks, "ledger_is_under_requested_evidence_root", str(ledger.path).startswith(str(output / "ledger")), str(ledger.path))
    _check(checks, "database_schema_is_not_used", "database" not in serialized.casefold(), "B3 ledger is filesystem evidence; no database migration.")

    failed_checks = [item for item in checks if not item["passed"]]
    result = {
        "certification_version": CERTIFICATION_VERSION,
        "baseline_commit": EXPECTED_BASELINE_COMMIT,
        "status": "CERTIFIED" if not failed_checks else "FAILED",
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed_checks),
        "checks_failed": len(failed_checks),
        "checks": checks,
        "ledger_path": str(ledger.path),
        "ledger_digest": ledger.ledger_digest,
    }
    (output / "certification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = certify(args.output)
    print(f"Roadmap 2 B3 certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Ledger digest: {result['ledger_digest']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
