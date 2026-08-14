from __future__ import annotations

from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_readiness import (
    PronunciationProjectReadiness,
    PronunciationReadinessRow,
)
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.pronunciation_audit_service import PronunciationAuditTrailService


class PronunciationReadinessService:
    """Read-only project pronunciation coverage and readiness projection.

    The service only summarizes existing A7.2-A7.5 evidence. It never changes a
    job, decision, language, provider, account, voice, model, dictionary,
    Preflight state, routing state, or generation state.
    """

    READY = "Ready"
    NEEDS_REVIEW = "Needs review"
    STALE = "Stale"
    UNSAFE = "Unsafe"
    NO_ACTION = "No action required"
    CATEGORIES = (READY, NEEDS_REVIEW, STALE, UNSAFE, NO_ACTION)

    def __init__(self) -> None:
        self.assurance = PronunciationAssuranceService()
        self.audit = PronunciationAuditTrailService()

    def _classification(self, job: TTSJob, settings: AppSettings) -> tuple[str, str]:
        assessment = self.assurance.assess_job(job, settings)
        decision = self.assurance.decision_kind(getattr(job, "pronunciation_override", None))
        freshness = self.assurance.decision_freshness(job, settings)

        if decision == "normalized" and not assessment.normalization_safe:
            return self.UNSAFE, "Explicit normalized decision no longer has a safe language-locked candidate."
        if decision in {"original", "normalized"} and freshness in {"stale", "legacy"}:
            label = "legacy review evidence" if freshness == "legacy" else "pronunciation-critical context changed"
            return self.STALE, f"Explicit {decision} decision requires revalidation: {label}."
        if decision in {"original", "normalized"} and freshness == "current":
            return self.READY, f"Explicit {decision} decision is current for the pronunciation context."
        if assessment.risk_level in {"high", "medium"}:
            return self.NEEDS_REVIEW, "Pronunciation risk is unresolved and requires an explicit review decision."
        return self.NO_ACTION, "No medium/high pronunciation risk requires an explicit decision."

    def assess_project(
        self,
        jobs: tuple[TTSJob, ...],
        settings: AppSettings,
        *,
        output_dir: Path | None = None,
        project_id: str | None = None,
    ) -> PronunciationProjectReadiness:
        batch = self.assurance.assess_batch(list(jobs), settings, require_freshness=True)
        audit_rows: dict[int, dict[str, object]] = {}
        audit_integrity = "EMPTY"
        audit_event_count = 0
        if output_dir is not None:
            verification = self.audit.verify(Path(output_dir), project_id)
            audit_event_count = int(verification.event_count)
            if verification.valid:
                audit_integrity = "VERIFIED" if verification.event_count else "EMPTY"
                _summary, audit_rows = self.audit.workspace_evidence(Path(output_dir), project_id, jobs, settings)
            else:
                audit_integrity = "FAILED"

        assessments = {int(item.row): item for item in batch.assessments if item.row is not None}
        rows: list[PronunciationReadinessRow] = []
        counts = {category: 0 for category in self.CATEGORIES}
        for job in jobs:
            item = assessments[job.row_number]
            category, reason = self._classification(job, settings)
            decision = self.assurance.decision_kind(getattr(job, "pronunciation_override", None))
            freshness = self.assurance.decision_freshness(job, settings)
            audit = audit_rows.get(job.row_number, {})
            audit_note = ""
            if audit:
                audit_note = str(audit.get("stale_reason", ""))
            rows.append(
                PronunciationReadinessRow(
                    row_number=job.row_number,
                    category=category,
                    risk_level=item.risk_level,
                    language=item.language,
                    decision_kind=decision if decision in {"original", "normalized"} else "",
                    freshness=freshness,
                    normalization_safe=bool(item.normalization_safe),
                    flags=item.flags,
                    reason=reason,
                    audit_event_count=int(audit.get("count", 0)) if audit else 0,
                    audit_note=audit_note,
                )
            )
            counts[category] += 1

        pronunciation_risk = sum(1 for item in batch.assessments if item.risk_level in {"high", "medium"})
        stale_decisions = counts[self.STALE]
        unresolved = counts[self.NEEDS_REVIEW] + counts[self.STALE] + counts[self.UNSAFE]
        summary = (
            f"Pronunciation readiness: {len(jobs)} job(s); risk {pronunciation_risk}; "
            f"ready {counts[self.READY]}; needs review {counts[self.NEEDS_REVIEW]}; "
            f"stale {counts[self.STALE]}; unsafe {counts[self.UNSAFE]}; "
            f"no action {counts[self.NO_ACTION]}. Audit: {audit_integrity}."
        )
        return PronunciationProjectReadiness(
            rows=tuple(rows),
            counts=counts,
            total_jobs=len(jobs),
            pronunciation_risk=pronunciation_risk,
            reviewed_current=len(batch.reviewed_rows),
            stale_decisions=stale_decisions,
            unresolved=unresolved,
            normalized=len(batch.normalized_rows),
            keep_original=len(batch.explicit_original_rows),
            audit_integrity=audit_integrity,
            audit_event_count=audit_event_count,
            summary=summary,
        )
