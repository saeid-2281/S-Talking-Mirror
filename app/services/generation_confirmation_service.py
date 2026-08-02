from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.models.domain import AppSettings
from app.models.preflight_state import PreflightState


@dataclass(frozen=True)
class GenerationLaunchCheck:
    """One decision item shown before a generation batch is committed."""

    code: str
    title: str
    detail: str
    tone: str = "info"
    requires_acknowledgement: bool = False


@dataclass(frozen=True)
class GenerationConfirmation:
    allowed: bool
    title: str = ""
    message: str = ""
    requires_user_confirmation: bool = False
    status: str = "ready"
    fingerprint: str = ""
    summary: str = ""
    checks: tuple[GenerationLaunchCheck, ...] = field(default_factory=tuple)
    required_acknowledgements: tuple[str, ...] = field(default_factory=tuple)


class GenerationConfirmationCoordinator:
    """Build the safe-launch decision and a secret-free execution receipt."""

    CLOUD_PROVIDERS = {"elevenlabs", "openai", "azure", "google", "aws_polly"}

    def evaluate(self, state: PreflightState, settings: AppSettings) -> GenerationConfirmation:
        if state.status == "Blocked by errors":
            checks = (
                GenerationLaunchCheck(
                    "preflight_blocked",
                    "Preflight is blocked",
                    "Resolve blocking errors before generation.",
                    "error",
                ),
            )
            return self._confirmation(
                allowed=False,
                title="Preflight errors",
                message="Resolve blocking errors before generation.",
                status="blocked",
                state=state,
                settings=settings,
                checks=checks,
            )
        if state.status == "No pending jobs":
            checks = (
                GenerationLaunchCheck(
                    "no_pending_jobs",
                    "No pending jobs",
                    "Select another scope or reset jobs before starting generation.",
                    "neutral",
                ),
            )
            return self._confirmation(
                allowed=False,
                title="No pending jobs",
                message="There are no pending jobs in the selected scope.",
                status="blocked",
                state=state,
                settings=settings,
                checks=checks,
            )

        checks: list[GenerationLaunchCheck] = [
            GenerationLaunchCheck(
                "scope",
                "Generation scope",
                f"{state.estimated_files:,} file(s), {state.estimated_characters:,} characters and "
                f"{state.estimated_provider_requests:,} provider request(s).",
                "success",
            ),
            GenerationLaunchCheck(
                "provider",
                "Provider and model",
                f"{settings.provider or 'Unknown provider'} · {settings.model_id or 'Default model'}",
                "success" if state.provider_ready else "info",
            ),
        ]

        warning_count = max(
            state.warnings,
            sum(1 for issue in state.issues if issue.severity == "warning"),
        )
        if state.status == "Ready with warnings" or warning_count:
            checks.append(
                GenerationLaunchCheck(
                    "preflight_warnings",
                    "Preflight warnings",
                    f"{warning_count:,} warning(s) remain in the current preflight result.",
                    "warning",
                    True,
                )
            )

        plan = state.generation_plan
        if plan is not None:
            if plan.risk_level in {"medium", "high"}:
                tone = "error" if plan.risk_level == "high" else "warning"
                checks.append(
                    GenerationLaunchCheck(
                        "planning_risk",
                        f"{plan.risk_level.title()} planning risk",
                        " · ".join(plan.reasons),
                        tone,
                        True,
                    )
                )
            else:
                checks.append(
                    GenerationLaunchCheck(
                        "planning_risk",
                        "Planning risk is low",
                        " · ".join(plan.reasons),
                        "success",
                    )
                )

            if plan.provider == "elevenlabs" and plan.quota_remaining is None:
                checks.append(
                    GenerationLaunchCheck(
                        "quota_unknown",
                        "Provider quota is unknown",
                        "Refresh the provider account when possible or acknowledge the unknown quota.",
                        "warning",
                        True,
                    )
                )
            elif plan.quota_shortfall > 0:
                checks.append(
                    GenerationLaunchCheck(
                        "quota_shortfall",
                        "Quota shortfall",
                        f"The planned batch exceeds available quota by {plan.quota_shortfall:,} characters.",
                        "error",
                        True,
                    )
                )

            if plan.provider in self.CLOUD_PROVIDERS and not plan.cost_available:
                checks.append(
                    GenerationLaunchCheck(
                        "pricing_unavailable",
                        "Cost estimate is unavailable",
                        "No pricing rate is configured for this provider and model.",
                        "warning",
                        True,
                    )
                )
            elif plan.cost_available:
                checks.append(
                    GenerationLaunchCheck(
                        "estimated_cost",
                        "Estimated provider cost",
                        f"{plan.currency} {plan.estimated_cost:,.4f} for the base scenario.",
                        "success" if plan.risk_level == "low" else "info",
                    )
                )

            expected = next((item for item in plan.scenarios if item.key == "expected"), None)
            if expected is not None and expected.retry_reserve_percent > 0:
                checks.append(
                    GenerationLaunchCheck(
                        "retry_reserve",
                        "Retry reserve scenario",
                        f"Expected retries reserve {expected.retry_reserve_percent}% and may reach "
                        f"{expected.characters:,} characters.",
                        "info",
                    )
                )

        existing_count = len(state.existing_outputs)
        if existing_count:
            if settings.skip_existing:
                detail = f"{existing_count:,} existing output(s) will be skipped by the current file policy."
                tone = "warning"
            elif settings.overwrite_existing:
                detail = f"{existing_count:,} existing output(s) may be replaced by this run."
                tone = "error"
            else:
                detail = f"{existing_count:,} existing output(s) need a file-policy decision."
                tone = "warning"
            checks.append(
                GenerationLaunchCheck(
                    "existing_outputs",
                    "Existing output files",
                    detail,
                    tone,
                    True,
                )
            )

        required = tuple(item.code for item in checks if item.requires_acknowledgement)
        requires_confirmation = bool(required)
        if state.status == "Ready with warnings" and required == ("preflight_warnings",):
            message = f"{warning_count:,} warning(s) found. Continue anyway?"
        elif requires_confirmation:
            message = f"Review and acknowledge {len(required):,} launch decision(s) before generation."
        else:
            message = "Preflight, scope and planning checks are ready for generation."

        return self._confirmation(
            allowed=True,
            title="Preflight warnings" if state.status == "Ready with warnings" else "Generation ready",
            message=message,
            status="confirmation_required" if requires_confirmation else "ready",
            state=state,
            settings=settings,
            checks=tuple(checks),
        )

    def write_receipt(
        self,
        confirmation: GenerationConfirmation,
        state: PreflightState,
        settings: AppSettings,
        *,
        reports_dir: Path,
        project_name: str,
        output_dir: Path,
        acknowledged_codes: tuple[str, ...] = (),
    ) -> Path:
        """Persist the exact launch decision without API keys or credentials."""

        timestamp = datetime.now(timezone.utc)
        folder = (
            Path(reports_dir)
            / self._safe_name(project_name)
            / "launches"
            / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}-{confirmation.fingerprint[:8]}"
        )
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "created_at": timestamp.isoformat(),
            "project_name": project_name,
            "launch_fingerprint": confirmation.fingerprint,
            "preflight_revision": state.revision,
            "preflight_status": state.status,
            "review_status": confirmation.status,
            "acknowledged_codes": sorted(set(acknowledged_codes)),
            "required_acknowledgements": list(confirmation.required_acknowledgements),
            "scope": {
                "files": state.estimated_files,
                "characters": state.estimated_characters,
                "provider_requests": state.estimated_provider_requests,
                "existing_outputs": len(state.existing_outputs),
            },
            "settings": {
                "provider": settings.provider,
                "model_id": settings.model_id,
                "voice_id": settings.voice_id,
                "language_code": settings.language_code,
                "file_extension": settings.file_extension,
                "max_retries": settings.max_retries,
                "delay_seconds": settings.delay_seconds,
                "skip_existing": settings.skip_existing,
                "overwrite_existing": settings.overwrite_existing,
                "generation_scope": settings.generation_scope,
                "execution_order": settings.execution_order,
            },
            "output_directory": str(Path(output_dir)),
            "checks": [asdict(item) for item in confirmation.checks],
            "generation_plan": asdict(state.generation_plan) if state.generation_plan is not None else None,
        }
        receipt_path = folder / "generation-launch.json"
        receipt_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (folder / "generation-launch.md").write_text(
            self._receipt_markdown(payload),
            encoding="utf-8",
        )
        return receipt_path

    def _confirmation(
        self,
        *,
        allowed: bool,
        title: str,
        message: str,
        status: str,
        state: PreflightState,
        settings: AppSettings,
        checks: tuple[GenerationLaunchCheck, ...],
    ) -> GenerationConfirmation:
        required = tuple(item.code for item in checks if item.requires_acknowledgement)
        summary = (
            f"{state.estimated_files:,} file(s) · {state.estimated_characters:,} characters · "
            f"{state.estimated_provider_requests:,} request(s) · {len(state.existing_outputs):,} existing output(s)"
        )
        fingerprint_payload = {
            "preflight_revision": state.revision,
            "settings_revision": state.settings_revision,
            "provider": settings.provider,
            "model": settings.model_id,
            "voice": settings.voice_id,
            "file_extension": settings.file_extension,
            "skip_existing": settings.skip_existing,
            "overwrite_existing": settings.overwrite_existing,
            "checks": [asdict(item) for item in checks],
            "plan": asdict(state.generation_plan) if state.generation_plan is not None else None,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return GenerationConfirmation(
            allowed=allowed,
            title=title,
            message=message,
            requires_user_confirmation=bool(required),
            status=status,
            fingerprint=fingerprint,
            summary=summary,
            checks=checks,
            required_acknowledgements=required,
        )

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
        return safe or "No-project"

    @staticmethod
    def _receipt_markdown(payload: dict[str, object]) -> str:
        scope = payload["scope"]
        settings = payload["settings"]
        checks = payload["checks"]
        lines = [
            "# S Talking Generation Launch Receipt",
            "",
            f"- Created: {payload['created_at']}",
            f"- Project: {payload['project_name']}",
            f"- Launch fingerprint: `{payload['launch_fingerprint']}`",
            f"- Preflight status: {payload['preflight_status']}",
            f"- Files: {scope['files']:,}",
            f"- Characters: {scope['characters']:,}",
            f"- Requests: {scope['provider_requests']:,}",
            f"- Provider: {settings['provider']}",
            f"- Model: {settings['model_id']}",
            f"- Output: {payload['output_directory']}",
            "",
            "## Launch checks",
        ]
        lines.extend(
            f"- {item['title']}: {item['detail']}"
            for item in checks
        )
        lines.extend(
            [
                "",
                "## Acknowledgements",
                *(f"- {code}" for code in payload["acknowledged_codes"]),
            ]
        )
        if not payload["acknowledged_codes"]:
            lines.append("- None required")
        return "\n".join(lines) + "\n"
