from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Any

from app.models.launch_assurance import LaunchAssuranceEvidence
from app.models.preflight_state import PreflightState


class LaunchAssuranceContextChanged(RuntimeError):
    """Raised when the live resolved request no longer matches explicit Preflight."""


class LaunchAssuranceService:
    """Fail-closed bridge from explicit Preflight to launch and generation.

    The service has no provider, routing, Preflight, or generation authority. It only
    verifies that the same resolved request and the same Preflight evidence are reused.
    """

    CHECKED_DIMENSIONS = (
        "queue rows / filenames / source text / pending status",
        "per-job provider / voice / model overrides",
        "user-selected target language / per-job language override",
        "pronunciation decisions / freshness / dictionary selection",
        "provider / account / voice / model settings",
        "generation scope / execution order",
        "source / output / project identity",
        "Preflight quota / cost / planning evidence snapshot",
    )

    def verify_launch(
        self,
        state: PreflightState,
        observed_revision: str,
    ) -> LaunchAssuranceEvidence:
        if not state.can_start:
            raise LaunchAssuranceContextChanged(
                "The explicit Preflight result is not launchable."
            )
        if not state.revision:
            raise LaunchAssuranceContextChanged(
                "The explicit Preflight result has no request revision."
            )
        if not observed_revision or observed_revision != state.revision:
            raise LaunchAssuranceContextChanged(
                "The resolved request changed after Preflight."
            )
        return LaunchAssuranceEvidence(
            preflight_revision=state.revision,
            preflight_context_fingerprint=self.preflight_context_fingerprint(state),
            launch_revision=observed_revision,
            checked_dimensions=self.CHECKED_DIMENSIONS,
        )

    def verify_generation(
        self,
        evidence: LaunchAssuranceEvidence,
        state: PreflightState,
        observed_revision: str,
    ) -> LaunchAssuranceEvidence:
        if not evidence.launch_matches_preflight:
            raise LaunchAssuranceContextChanged(
                "Launch assurance does not match the explicit Preflight revision."
            )
        if not observed_revision or observed_revision != evidence.launch_revision:
            raise LaunchAssuranceContextChanged(
                "The resolved request changed after launch review."
            )
        if state.revision != evidence.preflight_revision:
            raise LaunchAssuranceContextChanged(
                "The Preflight revision changed before generation."
            )
        if self.preflight_context_fingerprint(state) != evidence.preflight_context_fingerprint:
            raise LaunchAssuranceContextChanged(
                "The Preflight quota, cost, planning, language, or pronunciation evidence changed before generation."
            )
        return replace(
            evidence,
            generation_revision=observed_revision,
            status="generation_verified",
        )

    def preflight_context_fingerprint(self, state: PreflightState) -> str:
        payload = {
            "request_revision": state.revision,
            "estimated_files": int(state.estimated_files),
            "estimated_characters": int(state.estimated_characters),
            "estimated_provider_requests": int(state.estimated_provider_requests),
            "estimated_cost": state.estimated_cost,
            "provider_ready": bool(state.provider_ready),
            "output_directory_ready": bool(state.output_directory_ready),
            "language_lock_languages": list(state.language_lock_languages),
            "language_assurance_level": state.language_assurance_level,
            "pronunciation_current_review_rows": list(state.pronunciation_current_review_rows),
            "pronunciation_stale_review_rows": list(state.pronunciation_stale_review_rows),
            "pronunciation_legacy_review_rows": list(state.pronunciation_legacy_review_rows),
            "pronunciation_explicit_original_rows": list(state.pronunciation_explicit_original_rows),
            "pronunciation_normalized_rows": list(state.pronunciation_normalized_rows),
            "quota_snapshot": self._safe_value(state.quota_snapshot or {}),
            "generation_plan": self._safe_value(state.generation_plan),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _safe_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, Path):
            return str(value)
        if is_dataclass(value) and not isinstance(value, type):
            return self._safe_value(asdict(value))
        if hasattr(value, "model_dump"):
            return self._safe_value(value.model_dump(exclude={"api_key"}))
        if isinstance(value, dict):
            return {
                str(key): self._safe_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
                if "api_key" not in str(key).casefold()
            }
        if isinstance(value, (list, tuple, set)):
            return [self._safe_value(item) for item in value]
        if hasattr(value, "__dict__"):
            return self._safe_value(
                {
                    key: item
                    for key, item in vars(value).items()
                    if not key.startswith("_") and "api_key" not in key.casefold()
                }
            )
        return str(value)
