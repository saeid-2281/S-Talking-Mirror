from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.intelligent_tts_production_service import (
    IntelligentTTSProductionService,
)


CERTIFICATION_VERSION = "roadmap2-b1-v1"
EXPECTED_BASELINE_COMMIT = "c41a7e4f28865cf1640173c4c10a29adc5659839"


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def certify(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        provider="elevenlabs",
        active_api_profile_id="production-profile",
        voice_id="voice-da",
        model_id="eleven_v3",
        language_code="da",
        file_extension=".mp3",
        max_retries=4,
        generation_scope="entire_queue",
        execution_order="csv",
        api_key="CERTIFICATION_SECRET_MUST_NOT_APPEAR",
    )
    jobs = [
        _Job(1, "intro.mp3", "Hej verden"),
        _Job(2, "english.mp3", "This is explicitly English."),
        _Job(3, "duplicate.mp3", "Dansk tekst til produktion."),
        _Job(4, "duplicate.mp3", "Anden dansk tekst."),
    ]
    service = IntelligentTTSProductionService()
    overrides = {2: "en"}
    manifest = service.compile_manifest(
        jobs,
        settings,
        output / "audio",
        job_language_overrides=overrides,
    )
    repeated = service.compile_manifest(
        jobs,
        settings,
        output / "audio",
        job_language_overrides=overrides,
    )

    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "input_order_preserved",
        [request.row_number for request in manifest.requests] == [1, 2, 3, 4],
        "Rows remain in source order.",
    )
    _check(
        checks,
        "explicit_language_override_only",
        [request.language_code for request in manifest.requests]
        == ["da", "en", "da", "da"],
        "Row 2 uses explicit en override; all other rows retain da.",
    )
    _check(
        checks,
        "selection_authority_preserved",
        all(
            request.provider == "elevenlabs"
            and request.profile_id == "production-profile"
            and request.voice_id == "voice-da"
            and request.model_id == "eleven_v3"
            for request in manifest.requests
        ),
        "Provider/profile/voice/model remain exactly user-selected.",
    )
    _check(
        checks,
        "cross_provider_failover_disabled",
        all(request.cross_provider_failover == "disabled" for request in manifest.requests),
        "No request permits hidden cross-provider failover.",
    )
    _check(
        checks,
        "retry_scope_same_provider",
        all(request.same_provider_retry_limit == 4 for request in manifest.requests),
        "Retry limit is recorded without choosing another provider.",
    )
    _check(
        checks,
        "duplicate_is_review_signal_not_rename",
        manifest.requests[2].filename == manifest.requests[3].filename
        and any(
            reason.startswith("duplicate_output_with_row:")
            for reason in manifest.requests[3].review_reasons
        ),
        "Duplicate output stays unchanged and is surfaced for review.",
    )
    serialized = manifest.to_json()
    _check(
        checks,
        "secrets_redacted",
        "CERTIFICATION_SECRET_MUST_NOT_APPEAR" not in serialized
        and "api_key" not in serialized,
        "Manifest serialization contains no API key material.",
    )
    _check(
        checks,
        "raw_text_redacted_by_default",
        "This is explicitly English." not in serialized
        and "Dansk tekst til produktion." not in serialized,
        "Default evidence contains hashes/counts rather than source text.",
    )
    _check(
        checks,
        "deterministic_manifest_digest",
        manifest.manifest_digest == repeated.manifest_digest,
        manifest.manifest_digest,
    )
    _check(
        checks,
        "batching_is_observational",
        all(
            batch.policy == "observational_contiguous_group_only"
            for batch in manifest.batches
        )
        and [row for batch in manifest.batches for row in batch.row_numbers]
        == [1, 2, 3, 4],
        "Batch metadata does not reorder or execute jobs.",
    )

    service_source = inspect.getsource(
        __import__(
            "app.services.intelligent_tts_production_service",
            fromlist=["IntelligentTTSProductionService"],
        )
    )
    forbidden = (
        "create_provider",
        "run_preflight",
        "start_generation",
        "apply_smart_routing",
        "detect_language",
    )
    _check(
        checks,
        "no_hidden_execution_authority",
        all(token not in service_source for token in forbidden),
        "B1 service is a deterministic manifest boundary only.",
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
        "manifest_digest": manifest.manifest_digest,
    }
    (output / "manifest-example.json").write_text(
        manifest.to_json() + "\n", encoding="utf-8"
    )
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
    print(f"Roadmap 2 B1 certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Manifest digest: {result['manifest_digest']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
