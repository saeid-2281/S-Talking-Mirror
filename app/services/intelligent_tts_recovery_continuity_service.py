from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.intelligent_tts_run_ledger_service import (
    IntelligentTTSRunLedger,
    IntelligentTTSRunLedgerIntegrityError,
    IntelligentTTSRunLedgerService,
)


@dataclass(frozen=True)
class IntelligentTTSRecoveryContinuityAssessment:
    continuity_status: str
    parent_run_id: str
    resume_receipt_id: str | None
    resume_receipt_path: str | None
    parent_ledger_path: str | None
    parent_ledger_digest: str | None
    parent_status: str | None

    @property
    def verified(self) -> bool:
        return self.continuity_status == "verified"

    def to_event_payload(self) -> dict[str, str | None]:
        return {
            "continuity_status": self.continuity_status,
            "parent_run_id": self.parent_run_id,
            "parent_ledger_path": self.parent_ledger_path,
            "parent_ledger_digest": self.parent_ledger_digest,
            "parent_status": self.parent_status,
            "resume_receipt_id": self.resume_receipt_id,
            "resume_receipt_path": self.resume_receipt_path,
        }


class IntelligentTTSRecoveryContinuityService:
    """Record Safe Resume provenance without taking recovery authority."""

    def __init__(
        self,
        ledger_service: IntelligentTTSRunLedgerService | None = None,
    ) -> None:
        self.ledger_service = ledger_service or IntelligentTTSRunLedgerService()

    def assess_resume(
        self,
        *,
        evidence_root: Path,
        project_key: str,
        parent_run_id: str,
        resume_receipt_id: str | None,
        resume_receipt_path: str | Path | None,
    ) -> IntelligentTTSRecoveryContinuityAssessment:
        parent_id = str(parent_run_id or "").strip()
        receipt_id = str(resume_receipt_id).strip() if resume_receipt_id is not None else None
        receipt_path = str(resume_receipt_path) if resume_receipt_path is not None else None
        if not parent_id:
            return IntelligentTTSRecoveryContinuityAssessment(
                "parent_run_missing", "", receipt_id, receipt_path, None, None, None
            )
        parent_path = self.ledger_service.path_for(evidence_root, project_key, parent_id)
        if not parent_path.exists():
            return IntelligentTTSRecoveryContinuityAssessment(
                "parent_ledger_missing",
                parent_id,
                receipt_id,
                receipt_path,
                str(parent_path),
                None,
                None,
            )
        try:
            parent = self.ledger_service.load(parent_path)
        except IntelligentTTSRunLedgerIntegrityError:
            return IntelligentTTSRecoveryContinuityAssessment(
                "parent_ledger_invalid",
                parent_id,
                receipt_id,
                receipt_path,
                str(parent_path),
                None,
                None,
            )
        return IntelligentTTSRecoveryContinuityAssessment(
            "verified",
            parent_id,
            receipt_id,
            receipt_path,
            str(parent.path),
            parent.ledger_digest,
            parent.status,
        )

    def attach_child(
        self,
        child_ledger_path: Path,
        assessment: IntelligentTTSRecoveryContinuityAssessment,
    ) -> IntelligentTTSRunLedger:
        return self.ledger_service.record_recovery_lineage(
            child_ledger_path,
            assessment.to_event_payload(),
        )

    def discover_interrupted(
        self,
        evidence_root: Path,
    ) -> tuple[IntelligentTTSRunLedger, ...]:
        return self.ledger_service.discover_open(evidence_root)
