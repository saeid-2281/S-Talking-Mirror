from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.services.intelligent_tts_execution_service import (
    IntelligentTTSExecutionDrift,
    IntelligentTTSExecutionService,
)


CERTIFICATION_VERSION = "roadmap2-b2-v1"
EXPECTED_BASELINE_COMMIT = "4671d517ab6e008e7cd6e872e66d6e94a77e5ce6"


@dataclass
class _Job:
    row_number: int
    filename: str
    text: str


def _settings(**updates: Any) -> SimpleNamespace:
    values = {
        "provider": "elevenlabs",
        "active_api_profile_id": "production-profile",
        "voice_id": "voice-da",
        "model_id": "eleven_v3",
        "language_code": "da",
        "file_extension": ".mp3",
        "max_retries": 4,
        "generation_scope": "entire_queue",
        "execution_order": "csv",
        "api_key": "CERTIFICATION_SECRET_MUST_NOT_APPEAR",
    }
    values.update(updates)
    return SimpleNamespace(**values)


def certify(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    service = IntelligentTTSExecutionService()
    jobs = [
        _Job(1, "intro.mp3", "Dansk introduktion."),
        _Job(2, "english.mp3", "Explicit English row."),
    ]
    settings = _settings()
    binding = service.prepare(
        jobs,
        settings,
        output / "audio",
        job_language_overrides={2: "en"},
    )
    verified = service.verify_unchanged(
        binding,
        jobs,
        settings,
        output / "audio",
        job_language_overrides={2: "en"},
    )

    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    check("deterministic_binding", binding == verified, binding.manifest_digest)
    check("queue_order_locked", binding.row_numbers == (1, 2), str(binding.row_numbers))
    check("provider_locked", binding.provider == "elevenlabs", binding.provider)
    check("profile_locked", binding.profile_id == "production-profile", str(binding.profile_id))
    check("voice_locked", binding.voice_id == "voice-da", binding.voice_id)
    check("model_locked", binding.model_id == "eleven_v3", binding.model_id)
    check("language_locked", binding.default_language == "da", binding.default_language)
    check("cross_provider_failover_disabled", binding.cross_provider_failover == "disabled", binding.cross_provider_failover)
    check("automatic_execution_disabled", binding.automatic_execution == "disabled", binding.automatic_execution)

    drift_cases = {
        "provider_drift_rejected": (_settings(provider="openai"), jobs, output / "audio"),
        "voice_drift_rejected": (_settings(voice_id="other"), jobs, output / "audio"),
        "model_drift_rejected": (_settings(model_id="other"), jobs, output / "audio"),
        "language_drift_rejected": (_settings(language_code="en"), jobs, output / "audio"),
        "output_drift_rejected": (settings, jobs, output / "other"),
        "queue_drift_rejected": (settings, list(reversed(jobs)), output / "audio"),
    }
    for name, (case_settings, case_jobs, case_output) in drift_cases.items():
        rejected = False
        try:
            service.verify_unchanged(
                binding,
                case_jobs,
                case_settings,
                case_output,
                job_language_overrides={2: "en"},
            )
        except IntelligentTTSExecutionDrift:
            rejected = True
        check(name, rejected, "drift rejected" if rejected else "drift accepted")

    source = inspect.getsource(
        __import__(
            "app.services.intelligent_tts_execution_service",
            fromlist=["IntelligentTTSExecutionService"],
        )
    )
    forbidden = (
        "create_provider",
        "run_preflight",
        "start_generation",
        "apply_smart_routing",
        "detect_language",
        "GenerationWorker",
    )
    check(
        "no_hidden_execution_authority",
        all(token not in source for token in forbidden),
        "binding service never owns provider/generation authority",
    )

    serialized = json.dumps(binding.to_dict(), sort_keys=True)
    check(
        "secret_free_evidence",
        "CERTIFICATION_SECRET_MUST_NOT_APPEAR" not in serialized and "api_key" not in serialized,
        "binding evidence excludes credentials and raw source text",
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
        "manifest_digest": binding.manifest_digest,
    }
    (output / "execution-binding-example.json").write_text(
        json.dumps(binding.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "certification.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = certify(args.output)
    print(f"Roadmap 2 B2 execution certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Evidence: {args.output}")
    return 0 if result["status"] == "CERTIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
