from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Iterable

from app.models.domain import AppSettings
from app.models.preflight_state import PreflightState
from app.models.unified_preflight_decision import (
    UnifiedPreflightDecision,
    UnifiedPreflightSignal,
)


class UnifiedPreflightDecisionService:
    """Normalize all launch-readiness inputs into one deterministic decision."""

    PREPARATION_CODES = {
        "empty_text",
        "text_too_long",
        "invalid_filename",
        "path_traversal",
        "duplicate_filename",
        "duplicate_text",
        "missing_extension",
        "unsupported_extension",
        "path_too_long",
        "missing_csv",
        "no_jobs",
    }
    OUTPUT_CODES = {
        "existing_output",
        "output_directory",
        "output_directory_unavailable",
        "output_directory_not_writable",
    }
    PROVIDER_CODES = {
        "provider_not_ready",
        "missing_api_key",
        "invalid_provider",
        "provider_override_not_ready",
        "voice_not_ready",
        "model_not_ready",
        "quota_unknown",
        "quota_shortfall",
        "pricing_unavailable",
    }
    GUARD_CODES = {
        "baseline_guard_disabled",
        "baseline_guard_no_baseline",
        "baseline_guard_matching",
        "baseline_guard_information",
        "baseline_drift_guard",
        "baseline_drift_exception",
        "baseline_drift_blocked",
    }

    def evaluate(
        self,
        state: PreflightState,
        settings: AppSettings,
        *,
        checks: Iterable[object] = (),
        base_allowed: bool = True,
        required_acknowledgements: Iterable[str] = (),
        base_status: str = "ready",
    ) -> UnifiedPreflightDecision:
        signals: list[UnifiedPreflightSignal] = []
        check_items = tuple(checks)
        check_codes = {
            str(getattr(item, "code", "") or "").casefold()
            for item in check_items
        }

        for issue in state.issues:
            severity = str(issue.severity or "info").casefold()
            blocking = severity in {"hard_error", "overridable_error", "error"} and not (
                issue.overridable and issue.overridden
            )
            normalized_severity = "error" if blocking else "warning" if severity == "warning" else "info"
            signals.append(
                UnifiedPreflightSignal(
                    source=self._issue_source(issue.code),
                    code=str(issue.code or "preflight_issue"),
                    title=str(issue.message or "Preflight issue"),
                    detail=self._issue_detail(issue),
                    severity=normalized_severity,
                    suggested_action=str(issue.suggested_action or ""),
                    blocking=blocking,
                    requires_approval=bool(issue.overridable and not issue.overridden),
                )
            )

        if not state.provider_ready:
            signals.append(
                UnifiedPreflightSignal(
                    source="Provider readiness",
                    code="provider_not_ready",
                    title="Provider is not ready",
                    detail=f"{settings.provider or 'The selected provider'} is not ready for generation.",
                    severity="error",
                    suggested_action="Open Provider Workspace and resolve account, model, or voice readiness.",
                    blocking=True,
                )
            )
        if not state.output_directory_ready:
            signals.append(
                UnifiedPreflightSignal(
                    source="Output readiness",
                    code="output_directory_not_ready",
                    title="Output directory is not ready",
                    detail="The selected output directory is missing, inaccessible, or not writable.",
                    severity="error",
                    suggested_action="Choose a writable output directory and run preflight again.",
                    blocking=True,
                )
            )
        if state.total_jobs and state.estimated_files == 0:
            signals.append(
                UnifiedPreflightSignal(
                    source="Scope",
                    code="no_pending_jobs",
                    title="No pending jobs are selected",
                    detail="The current generation scope contains no pending work.",
                    severity="error",
                    suggested_action="Change the generation scope or reset eligible jobs.",
                    blocking=True,
                )
            )

        issue_warning_count = sum(
            str(issue.severity or "").casefold() == "warning"
            for issue in state.issues
        )
        if state.warnings > issue_warning_count and "preflight_warnings" not in check_codes:
            signals.append(
                UnifiedPreflightSignal(
                    source="Preflight",
                    code="preflight_warnings",
                    title="Preflight warnings remain",
                    detail=f"{state.warnings:,} warning(s) remain in the current preflight result.",
                    severity="warning",
                    suggested_action="Review the warning list before generation.",
                )
            )

        plan = state.generation_plan
        if plan is not None:
            if plan.risk_level in {"medium", "high"} and "planning_risk" not in check_codes:
                signals.append(
                    UnifiedPreflightSignal(
                        source="Batch planning",
                        code="planning_risk",
                        title=f"{plan.risk_level.title()} planning risk",
                        detail=" · ".join(plan.reasons),
                        severity="warning",
                        suggested_action="Reduce scope, retries, or concurrency when the risk is not acceptable.",
                        requires_approval=True,
                    )
                )
            if plan.quota_shortfall > 0 and "quota_shortfall" not in check_codes:
                signals.append(
                    UnifiedPreflightSignal(
                        source="Cost and quota",
                        code="quota_shortfall",
                        title="Quota shortfall",
                        detail=f"The plan exceeds available quota by {plan.quota_shortfall:,} characters.",
                        severity="warning",
                        suggested_action="Reduce scope, switch provider, or acquire additional quota.",
                        requires_approval=True,
                    )
                )
            elif (
                plan.provider == "elevenlabs"
                and plan.quota_remaining is None
                and "quota_unknown" not in check_codes
            ):
                signals.append(
                    UnifiedPreflightSignal(
                        source="Cost and quota",
                        code="quota_unknown",
                        title="Provider quota is unknown",
                        detail="The provider quota snapshot is not available.",
                        severity="warning",
                        suggested_action="Refresh provider quota before launching a large batch.",
                        requires_approval=True,
                    )
                )
            if (
                plan.provider in {"elevenlabs", "openai", "azure", "google", "aws_polly"}
                and not plan.cost_available
                and "pricing_unavailable" not in check_codes
            ):
                signals.append(
                    UnifiedPreflightSignal(
                        source="Cost and quota",
                        code="pricing_unavailable",
                        title="Cost estimate is unavailable",
                        detail="No provider pricing rate is configured for the current model.",
                        severity="warning",
                        suggested_action="Configure provider pricing or acknowledge that cost is unknown.",
                        requires_approval=True,
                    )
                )

        if state.existing_outputs and "existing_outputs" not in check_codes:
            policy = (
                "skip"
                if settings.skip_existing
                else "overwrite"
                if settings.overwrite_existing
                else "unresolved"
            )
            signals.append(
                UnifiedPreflightSignal(
                    source="Output policy",
                    code="existing_outputs",
                    title="Existing output files",
                    detail=f"{len(state.existing_outputs):,} existing output(s) use the {policy} policy.",
                    severity="warning",
                    suggested_action="Choose Skip Existing, Overwrite, or resolve filename conflicts.",
                    requires_approval=True,
                )
            )

        for check in check_items:
            code = str(getattr(check, "code", "") or "launch_check")
            tone = str(getattr(check, "tone", "info") or "info").casefold()
            requires_approval = bool(getattr(check, "requires_acknowledgement", False))
            blocking = code in {"preflight_blocked", "no_pending_jobs", "baseline_drift_blocked"}
            if tone == "error" and not requires_approval:
                blocking = True
            signals.append(
                UnifiedPreflightSignal(
                    source=self._check_source(code),
                    code=code,
                    title=str(getattr(check, "title", "Launch check") or "Launch check"),
                    detail=str(getattr(check, "detail", "") or ""),
                    severity="error" if blocking else "warning" if tone in {"warning", "error"} else "info",
                    suggested_action=self._check_action(code),
                    blocking=blocking,
                    requires_approval=requires_approval,
                )
            )

        signals = self._deduplicate(signals)
        blockers = [item for item in signals if item.blocking]
        approvals = [item for item in signals if item.requires_approval and not item.blocking]
        warnings = [item for item in signals if item.severity == "warning" and not item.blocking]
        required = tuple(sorted({str(item) for item in required_acknowledgements if str(item).strip()}))

        if blockers or not base_allowed or base_status in {"blocked", "baseline_guard_blocked"}:
            status = "blocked"
            allowed = False
            headline = "Blocked"
            summary = self._summary(blockers, approvals, warnings, "Resolve blocking decisions before generation.")
        elif approvals or required:
            status = "approval_required"
            allowed = True
            headline = "Approval required"
            summary = self._summary(blockers, approvals, warnings, "Review and acknowledge required decisions.")
        elif warnings or state.warnings:
            status = "ready_with_warnings"
            allowed = True
            headline = "Ready with warnings"
            summary = self._summary(blockers, approvals, warnings, "Review warnings before generation.")
        else:
            status = "ready"
            allowed = True
            headline = "Ready"
            summary = "Preparation, provider, output, planning, quota, cost, and guard checks are ready."

        recommendations = self._recommendations(signals, status)
        trace_payload = {
            "preflight_revision": state.revision,
            "settings_revision": state.settings_revision,
            "provider": settings.provider,
            "model": settings.model_id,
            "voice": settings.voice_id,
            "base_status": base_status,
            "required_acknowledgements": required,
            "status": status,
            "signals": [asdict(item) for item in signals],
            "recommendations": recommendations,
        }
        trace_id = hashlib.sha256(
            json.dumps(trace_payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        return UnifiedPreflightDecision(
            status=status,
            allowed=allowed,
            headline=headline,
            summary=summary,
            trace_id=trace_id,
            signals=tuple(signals),
            recommendations=recommendations,
            blocker_count=len(blockers),
            warning_count=len(warnings),
            approval_count=max(len(approvals), len(required)),
        )

    @classmethod
    def _issue_source(cls, code: str) -> str:
        key = str(code or "").casefold()
        if key in cls.PREPARATION_CODES:
            return "Source preparation"
        if key in cls.OUTPUT_CODES or key.startswith("output_"):
            return "Output readiness"
        if key in cls.PROVIDER_CODES or key.startswith("provider_"):
            return "Provider readiness"
        if "quota" in key or "pricing" in key:
            return "Cost and quota"
        return "Preflight"

    @classmethod
    def _check_source(cls, code: str) -> str:
        key = str(code or "").casefold()
        if key in cls.GUARD_CODES or key.startswith("baseline_"):
            return "Baseline guard"
        if key in {"planning_risk", "estimated_cost", "retry_reserve"}:
            return "Batch planning"
        if key in {"quota_unknown", "quota_shortfall", "pricing_unavailable"}:
            return "Cost and quota"
        if key == "existing_outputs":
            return "Output policy"
        if key in {"provider", "provider_not_ready"}:
            return "Provider readiness"
        if key in {"scope", "no_pending_jobs"}:
            return "Scope"
        return "Launch review"

    @staticmethod
    def _issue_detail(issue: object) -> str:
        row = getattr(issue, "row", None)
        filename = str(getattr(issue, "filename", "") or "")
        context: list[str] = []
        if row is not None:
            context.append(f"row {row}")
        if filename:
            context.append(filename)
        message = str(getattr(issue, "message", "") or "")
        return f"{message} ({' · '.join(context)})" if context else message

    @staticmethod
    def _check_action(code: str) -> str:
        actions = {
            "preflight_blocked": "Resolve blocking preflight issues and run the decision again.",
            "no_pending_jobs": "Change scope or reset eligible jobs.",
            "preflight_warnings": "Review the warning list and acknowledge intentional risks.",
            "planning_risk": "Reduce scope, retries, or concurrency when the risk is not acceptable.",
            "quota_unknown": "Refresh provider quota before launching a large batch.",
            "quota_shortfall": "Reduce scope, switch provider, or acquire additional quota.",
            "pricing_unavailable": "Configure provider pricing or acknowledge that cost is unknown.",
            "existing_outputs": "Choose Skip Existing, Overwrite, or resolve filename conflicts.",
            "baseline_drift_guard": "Restore protected baseline settings or explicitly acknowledge drift.",
            "baseline_drift_blocked": "Restore protected settings or create a time-bound exception approval.",
            "baseline_drift_exception": "Verify the approver, expiry, and protected changes before launch.",
        }
        return actions.get(str(code or "").casefold(), "")

    @staticmethod
    def _deduplicate(signals: list[UnifiedPreflightSignal]) -> list[UnifiedPreflightSignal]:
        result: list[UnifiedPreflightSignal] = []
        seen: set[tuple[str, str, str]] = set()
        for signal in signals:
            key = (signal.source.casefold(), signal.code.casefold(), signal.detail.casefold())
            if key in seen:
                continue
            seen.add(key)
            result.append(signal)
        return result

    @staticmethod
    def _summary(
        blockers: list[UnifiedPreflightSignal],
        approvals: list[UnifiedPreflightSignal],
        warnings: list[UnifiedPreflightSignal],
        fallback: str,
    ) -> str:
        parts: list[str] = []
        if blockers:
            parts.append(f"{len(blockers):,} blocker(s)")
        if approvals:
            parts.append(f"{len(approvals):,} approval decision(s)")
        if warnings:
            parts.append(f"{len(warnings):,} warning(s)")
        return f"{' · '.join(parts)}. {fallback}" if parts else fallback

    @staticmethod
    def _recommendations(
        signals: list[UnifiedPreflightSignal],
        status: str,
    ) -> tuple[str, ...]:
        prioritized = sorted(
            signals,
            key=lambda item: (
                0 if item.blocking else 1 if item.requires_approval else 2,
                item.source.casefold(),
                item.code.casefold(),
            ),
        )
        recommendations: list[str] = []
        for signal in prioritized:
            action = str(signal.suggested_action or "").strip()
            if action and action not in recommendations:
                recommendations.append(action)
            if len(recommendations) >= 5:
                break
        if not recommendations and status == "ready":
            recommendations.append("Start generation with the reviewed plan.")
        return tuple(recommendations)
