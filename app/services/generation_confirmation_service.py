from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from app.models.domain import AppSettings
from app.models.generation_budget_guard import GenerationBudgetGuardDecision
from app.models.generation_launch_receipt import GenerationLaunchReceipt
from app.models.preflight_state import PreflightState
from app.models.unified_preflight_decision import UnifiedPreflightDecision
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService
from app.services.generation_budget_guard_service import GenerationBudgetGuardService
from app.services.unified_preflight_decision_service import UnifiedPreflightDecisionService


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
    guard_candidate_fingerprint: str = ""
    guard_baseline_receipt_id: str = ""
    guard_change_keys: tuple[str, ...] = field(default_factory=tuple)
    guard_approval_id: str = ""
    guard_policy_profile_id: str = ""
    guard_policy_version: int = 0
    guard_policy_locked: bool = False
    budget_guard_decision: GenerationBudgetGuardDecision | None = None
    budget_approval_id: str = ""
    budget_reservation_id: str = ""
    unified_decision: UnifiedPreflightDecision | None = None


class GenerationConfirmationCoordinator:
    """Build the safe-launch decision and a secret-free execution receipt."""

    CLOUD_PROVIDERS = {"elevenlabs", "openai", "azure", "google", "aws_polly"}

    def __init__(
        self,
        decision_service: UnifiedPreflightDecisionService | None = None,
    ) -> None:
        self.decision_service = decision_service or UnifiedPreflightDecisionService()

    def evaluate(
        self,
        state: PreflightState,
        settings: AppSettings,
        *,
        receipt_service: GenerationLaunchReceiptService | None = None,
        budget_guard_service: GenerationBudgetGuardService | None = None,
        project_name: str = "",
        project_id: int | None = None,
        output_dir: Path | None = None,
    ) -> GenerationConfirmation:
        if state.status == "Blocked by errors":
            checks = (
                GenerationLaunchCheck(
                    "preflight_blocked",
                    "Preflight is blocked",
                    "Resolve blocking errors before generation.",
                    "error",
                ),
            )
            return self._finalize_decision(
                self._confirmation(
                    allowed=False,
                    title="Preflight errors",
                    message="Resolve blocking errors before generation.",
                    status="blocked",
                    state=state,
                    settings=settings,
                    checks=checks,
                ),
                state,
                settings,
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
            return self._finalize_decision(
                self._confirmation(
                    allowed=False,
                    title="No pending jobs",
                    message="There are no pending jobs in the selected scope.",
                    status="blocked",
                    state=state,
                    settings=settings,
                    checks=checks,
                ),
                state,
                settings,
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

        confirmation = self._confirmation(
            allowed=True,
            title="Preflight warnings" if state.status == "Ready with warnings" else "Generation ready",
            message=message,
            status="confirmation_required" if requires_confirmation else "ready",
            state=state,
            settings=settings,
            checks=tuple(checks),
        )
        guarded = self._apply_baseline_guard(
            confirmation,
            state,
            settings,
            receipt_service=receipt_service,
            project_name=project_name,
            output_dir=output_dir,
        )
        budgeted = self._apply_budget_guard(
            guarded,
            state,
            settings,
            budget_guard_service=budget_guard_service,
            project_id=project_id,
            project_name=project_name,
        )
        return self._finalize_decision(budgeted, state, settings)

    def _finalize_decision(
        self,
        confirmation: GenerationConfirmation,
        state: PreflightState,
        settings: AppSettings,
    ) -> GenerationConfirmation:
        decision = self.decision_service.evaluate(
            state,
            settings,
            checks=confirmation.checks,
            base_allowed=confirmation.allowed,
            required_acknowledgements=confirmation.required_acknowledgements,
            base_status=confirmation.status,
        )
        return replace(confirmation, unified_decision=decision)

    def _apply_baseline_guard(
        self,
        confirmation: GenerationConfirmation,
        state: PreflightState,
        settings: AppSettings,
        *,
        receipt_service: GenerationLaunchReceiptService | None,
        project_name: str,
        output_dir: Path | None,
    ) -> GenerationConfirmation:
        project = str(project_name or "").strip()
        if receipt_service is None or not project:
            return confirmation
        candidate = GenerationLaunchReceipt(
            path=Path(output_dir or ".") / ".generation-launch-preview.json",
            markdown_path=Path(output_dir or ".") / ".generation-launch-preview.md",
            schema_version=2,
            project_name=project,
            launch_fingerprint=confirmation.fingerprint,
            preflight_status=state.status,
            review_status=confirmation.status,
            provider=settings.provider,
            model_id=settings.model_id,
            voice_id=settings.voice_id,
            language_code=settings.language_code,
            file_extension=settings.file_extension,
            max_retries=settings.max_retries,
            delay_seconds=settings.delay_seconds,
            skip_existing=settings.skip_existing,
            overwrite_existing=settings.overwrite_existing,
            generation_scope=settings.generation_scope,
            execution_order=settings.execution_order,
            output_directory=str(Path(output_dir or ".")),
            files=state.estimated_files,
            characters=state.estimated_characters,
            provider_requests=state.estimated_provider_requests,
            existing_outputs=len(state.existing_outputs),
            risk_level=(
                state.generation_plan.risk_level
                if state.generation_plan is not None
                else "unknown"
            ),
            estimated_cost=(
                state.generation_plan.estimated_cost
                if state.generation_plan is not None
                else state.estimated_cost
            ),
            currency=(
                state.generation_plan.currency
                if state.generation_plan is not None
                else "USD"
            ),
            required_acknowledgements=confirmation.required_acknowledgements,
            integrity_status="verified",
            integrity_message="Current preflight preview.",
        )
        decision = receipt_service.evaluate_guard(candidate)
        if decision.status == "disabled":
            check = GenerationLaunchCheck(
                "baseline_guard_disabled",
                "Project baseline guard is disabled",
                decision.summary,
                "info",
            )
        elif decision.status == "no_baseline":
            check = GenerationLaunchCheck(
                "baseline_guard_no_baseline",
                "No project launch baseline",
                "Set a trusted receipt in Reports → Launch Receipts to enable drift protection.",
                "info",
            )
        elif decision.status == "matching":
            check = GenerationLaunchCheck(
                "baseline_guard_matching",
                "Protected launch settings match baseline",
                decision.summary,
                "success",
            )
        elif decision.status == "informational_drift":
            check = GenerationLaunchCheck(
                "baseline_guard_information",
                "Informational baseline drift",
                decision.summary,
                "info",
            )
        elif decision.status == "review_required":
            check = GenerationLaunchCheck(
                "baseline_drift_guard",
                "Protected launch settings changed",
                decision.summary,
                "error" if decision.critical_count else "warning",
                True,
            )
        elif decision.status == "approved_exception":
            approval = decision.approval
            detail = decision.summary
            if approval is not None:
                detail = (
                    f"{decision.summary} Approved by {approval.approved_by}; "
                    f"expires {approval.expires_at}."
                )
            check = GenerationLaunchCheck(
                "baseline_drift_exception",
                "Approved baseline guard exception",
                detail,
                "warning",
                True,
            )
        else:
            check = GenerationLaunchCheck(
                "baseline_drift_blocked",
                "Project baseline guard blocked launch",
                decision.summary,
                "error",
            )
        checks = (*confirmation.checks, check)
        baseline = decision.comparison.baseline if decision.comparison is not None else None
        baseline_id = (
            baseline.receipt_id or baseline.launch_fingerprint or baseline.path.name
            if baseline is not None
            else ""
        )
        change_keys = tuple(sorted(item.key for item in decision.protected_changes))
        approval_id = decision.approval.approval_id if decision.approval is not None else ""
        if not decision.allowed:
            result = self._confirmation(
                allowed=False,
                title="Launch blocked by project baseline",
                message=(
                    f"{decision.summary} Create a time-bound exception approval or "
                    "restore protected settings."
                ),
                status="baseline_guard_blocked",
                state=state,
                settings=settings,
                checks=checks,
            )
            return replace(
                result,
                guard_candidate_fingerprint=confirmation.fingerprint,
                guard_baseline_receipt_id=baseline_id,
                guard_change_keys=change_keys,
                guard_policy_profile_id=decision.policy.profile_id,
                guard_policy_version=decision.policy.version,
                guard_policy_locked=decision.policy.locked,
            )
        required = any(item.requires_acknowledgement for item in checks)
        result = self._confirmation(
            allowed=True,
            title=(
                "Baseline exception review"
                if decision.status == "approved_exception"
                else "Baseline drift review"
                if decision.requires_acknowledgement
                else confirmation.title
            ),
            message=(
                decision.summary
                if decision.requires_acknowledgement
                else confirmation.message
            ),
            status="confirmation_required" if required else confirmation.status,
            state=state,
            settings=settings,
            checks=checks,
        )
        return replace(
            result,
            guard_candidate_fingerprint=confirmation.fingerprint,
            guard_baseline_receipt_id=baseline_id,
            guard_change_keys=change_keys,
            guard_approval_id=approval_id,
            guard_policy_profile_id=decision.policy.profile_id,
            guard_policy_version=decision.policy.version,
            guard_policy_locked=decision.policy.locked,
        )

    def _apply_budget_guard(
        self,
        confirmation: GenerationConfirmation,
        state: PreflightState,
        settings: AppSettings,
        *,
        budget_guard_service: GenerationBudgetGuardService | None,
        project_id: int | None,
        project_name: str,
    ) -> GenerationConfirmation:
        if budget_guard_service is None:
            return confirmation
        plan = state.generation_plan
        estimated_cost = (
            float(plan.estimated_cost)
            if plan is not None and plan.cost_available
            else float(state.estimated_cost or 0.0)
        )
        currency = plan.currency if plan is not None else "USD"
        quota_remaining = plan.quota_remaining if plan is not None else None
        decision = budget_guard_service.evaluate(
            project_id=project_id,
            project_name=project_name,
            provider=settings.provider,
            model_id=settings.model_id,
            estimated_cost=estimated_cost,
            currency=currency,
            required_characters=state.estimated_characters,
            quota_remaining=quota_remaining,
            launch_fingerprint=confirmation.fingerprint,
        )
        detail = decision.summary
        if decision.reasons:
            detail = f"{detail} " + " ".join(decision.reasons)
        if decision.status == "disabled":
            check = GenerationLaunchCheck(
                "budget_guard_disabled",
                "Budget guard is disabled",
                detail,
                "info",
            )
        elif decision.status == "ready":
            check = GenerationLaunchCheck(
                "budget_guard_ready",
                "Budget and quota guard ready",
                detail,
                "success",
            )
        elif decision.status == "warning":
            check = GenerationLaunchCheck(
                "budget_guard_warning",
                "Budget or quota warning",
                detail,
                "warning",
                True,
            )
        elif decision.status == "approved_exception":
            check = GenerationLaunchCheck(
                "budget_exception",
                "Approved budget exception",
                f"{detail} Approval: {decision.approval_id}.",
                "warning",
                True,
            )
        elif decision.status == "quota_blocked":
            check = GenerationLaunchCheck(
                "quota_guard_blocked",
                "Provider quota blocks launch",
                detail,
                "error",
            )
        else:
            check = GenerationLaunchCheck(
                "budget_guard_blocked",
                "Budget policy blocks launch",
                detail,
                "error",
            )
        checks = (*confirmation.checks, check)
        if not confirmation.allowed:
            result = self._confirmation(
                allowed=False,
                title=confirmation.title,
                message=confirmation.message,
                status=confirmation.status,
                state=state,
                settings=settings,
                checks=checks,
            )
            return replace(
                result,
                budget_guard_decision=decision,
                budget_approval_id=decision.approval_id,
                guard_candidate_fingerprint=confirmation.guard_candidate_fingerprint,
                guard_baseline_receipt_id=confirmation.guard_baseline_receipt_id,
                guard_change_keys=confirmation.guard_change_keys,
                guard_approval_id=confirmation.guard_approval_id,
                guard_policy_profile_id=confirmation.guard_policy_profile_id,
                guard_policy_version=confirmation.guard_policy_version,
                guard_policy_locked=confirmation.guard_policy_locked,
            )
        if not decision.allowed:
            result = self._confirmation(
                allowed=False,
                title=(
                    "Launch blocked by provider quota"
                    if decision.status == "quota_blocked"
                    else "Launch blocked by budget policy"
                ),
                message=(
                    "Reduce the generation scope or refresh provider quota."
                    if decision.status == "quota_blocked"
                    else "Reduce the scope, update the budget policy or create a time-bound exception."
                ),
                status=(
                    "quota_guard_blocked"
                    if decision.status == "quota_blocked"
                    else "budget_guard_blocked"
                ),
                state=state,
                settings=settings,
                checks=checks,
            )
            return replace(
                result,
                budget_guard_decision=decision,
                budget_approval_id=decision.approval_id,
                guard_candidate_fingerprint=confirmation.guard_candidate_fingerprint,
                guard_baseline_receipt_id=confirmation.guard_baseline_receipt_id,
                guard_change_keys=confirmation.guard_change_keys,
                guard_approval_id=confirmation.guard_approval_id,
                guard_policy_profile_id=confirmation.guard_policy_profile_id,
                guard_policy_version=confirmation.guard_policy_version,
                guard_policy_locked=confirmation.guard_policy_locked,
            )
        required = any(item.requires_acknowledgement for item in checks)
        result = self._confirmation(
            allowed=True,
            title=(
                "Budget exception review"
                if decision.status == "approved_exception"
                else "Budget and quota review"
                if decision.requires_acknowledgement
                else confirmation.title
            ),
            message=decision.summary if decision.requires_acknowledgement else confirmation.message,
            status="confirmation_required" if required else confirmation.status,
            state=state,
            settings=settings,
            checks=checks,
        )
        return replace(
            result,
            budget_guard_decision=decision,
            budget_approval_id=decision.approval_id,
            guard_candidate_fingerprint=confirmation.guard_candidate_fingerprint,
            guard_baseline_receipt_id=confirmation.guard_baseline_receipt_id,
            guard_change_keys=confirmation.guard_change_keys,
            guard_approval_id=confirmation.guard_approval_id,
            guard_policy_profile_id=confirmation.guard_policy_profile_id,
            guard_policy_version=confirmation.guard_policy_version,
            guard_policy_locked=confirmation.guard_policy_locked,
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
        receipt_service: GenerationLaunchReceiptService | None = None,
        run_id: str = "",
        execution_session_path: Path | None = None,
        consume_guard_approval: bool = True,
    ) -> Path:
        """Persist the exact launch decision without API keys or credentials."""

        timestamp = datetime.now(timezone.utc)
        folder = (
            Path(reports_dir)
            / self._safe_name(project_name)
            / "launches"
            / f"{timestamp.strftime('%Y-%m-%d_%H-%M-%S-%f')}-{confirmation.fingerprint[:8]}"
        )
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "receipt_id": f"launch-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{confirmation.fingerprint[:12]}",
            "created_at": timestamp.isoformat(),
            "project_name": project_name,
            "launch_fingerprint": confirmation.fingerprint,
            "preflight_revision": state.revision,
            "preflight_status": state.status,
            "review_status": confirmation.status,
            "acknowledged_codes": sorted(set(acknowledged_codes)),
            "required_acknowledgements": list(confirmation.required_acknowledgements),
            "guard_policy": {
                "profile_id": confirmation.guard_policy_profile_id,
                "version": confirmation.guard_policy_version,
                "locked": confirmation.guard_policy_locked,
            },
            "guard_exception": (
                {
                    "approval_id": confirmation.guard_approval_id,
                    "candidate_fingerprint": confirmation.guard_candidate_fingerprint,
                    "baseline_receipt_id": confirmation.guard_baseline_receipt_id,
                    "protected_change_keys": list(confirmation.guard_change_keys),
                }
                if confirmation.guard_approval_id
                else None
            ),
            "budget_guard": (
                {
                    **asdict(confirmation.budget_guard_decision),
                    "approval_id": confirmation.budget_approval_id,
                    "reservation_id": confirmation.budget_reservation_id,
                }
                if confirmation.budget_guard_decision is not None
                else None
            ),
            "execution": {
                "run_id": str(run_id or ""),
                "session_path": str(execution_session_path or ""),
            },
            "unified_decision": (
                asdict(confirmation.unified_decision)
                if confirmation.unified_decision is not None
                else None
            ),
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
        payload["integrity"] = {
            "algorithm": "sha256",
            "digest": GenerationLaunchReceiptService.canonical_digest(payload),
        }
        receipt_path = folder / "generation-launch.json"
        receipt_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (folder / "generation-launch.md").write_text(
            self._receipt_markdown(payload),
            encoding="utf-8",
        )
        if receipt_service is not None and confirmation.guard_approval_id and consume_guard_approval:
            receipt_service.consume_guard_approval(
                confirmation.guard_approval_id,
                receipt_id=str(payload.get("receipt_id") or ""),
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
            f"- Receipt ID: `{payload.get('receipt_id', '')}`",
            f"- Created: {payload['created_at']}",
            f"- Project: {payload['project_name']}",
            f"- Launch fingerprint: `{payload['launch_fingerprint']}`",
            f"- Integrity: {payload.get('integrity', {}).get('algorithm', 'legacy')} "
            f"`{payload.get('integrity', {}).get('digest', '')}`",
            f"- Preflight status: {payload['preflight_status']}",
            f"- Unified decision: {(payload.get('unified_decision') or {}).get('headline', 'Not recorded')}",
            f"- Decision trace: `{(payload.get('unified_decision') or {}).get('trace_id', '')}`",
            f"- Guard policy profile: {(payload.get('guard_policy') or {}).get('profile_id', 'Custom') or 'Custom'}",
            f"- Guard policy version: {(payload.get('guard_policy') or {}).get('version', 0)}",
            f"- Guard policy locked: {(payload.get('guard_policy') or {}).get('locked', False)}",
            f"- Guard exception: {(payload.get('guard_exception') or {}).get('approval_id', 'None')}",
            f"- Budget guard: {(payload.get('budget_guard') or {}).get('status', 'Not recorded')}",
            f"- Budget approval: {(payload.get('budget_guard') or {}).get('approval_id', 'None') or 'None'}",
            f"- Budget reservation: {(payload.get('budget_guard') or {}).get('reservation_id', 'None') or 'None'}",
            f"- Run ID: `{(payload.get('execution') or {}).get('run_id', '')}`",
            f"- Execution session: {(payload.get('execution') or {}).get('session_path', 'Not recorded') or 'Not recorded'}",
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
