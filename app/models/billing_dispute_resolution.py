from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BillingDisputeGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class BillingDisputeSource:
    reconciliation_id: str
    outcome_status: str
    decision: str
    provider: str
    invoice_id: str
    currency: str
    variance_amount: float
    duplicate_charge_count: int
    unmatched_request_count: int
    result_path: Path
    attestation_path: Path
    dispute_pack_path: Path
    receipt_path: Path
    result_sha256: str
    attestation_sha256: str
    dispute_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        # Persist only portable filenames in evidence.  The in-memory model keeps
        # absolute Paths for local verification, but exported snapshots must not
        # disclose a workstation or project directory.
        for field_name in (
            "result_path",
            "attestation_path",
            "dispute_pack_path",
            "receipt_path",
        ):
            payload[field_name] = Path(payload[field_name]).name
        return payload


@dataclass(frozen=True)
class BillingDisputeSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    status: str
    status_summary: str
    release_gate: str
    recommended_decision: str
    selected_result_count: int
    verified_source_count: int
    rejected_source_count: int
    dispute_required_count: int
    no_dispute_required_count: int
    total_claim_amount: float
    currency: str
    sources: tuple[BillingDisputeSource, ...] = field(default_factory=tuple)
    gates: tuple[BillingDisputeGate, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "status": self.status,
            "status_summary": self.status_summary,
            "release_gate": self.release_gate,
            "recommended_decision": self.recommended_decision,
            "selected_result_count": self.selected_result_count,
            "verified_source_count": self.verified_source_count,
            "rejected_source_count": self.rejected_source_count,
            "dispute_required_count": self.dispute_required_count,
            "no_dispute_required_count": self.no_dispute_required_count,
            "total_claim_amount": self.total_claim_amount,
            "currency": self.currency,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "sources": [source.to_dict() for source in self.sources],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class BillingDisputeCaseRecord:
    case_id: str
    created_at: str
    case_status: str
    requested_credit_amount: float
    snapshot_path: Path
    case_path: Path
    source_result_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in ("snapshot_path", "case_path", "source_result_path"):
            payload[field_name] = str(payload[field_name])
        return payload


@dataclass(frozen=True)
class BillingSettlementRecord:
    settlement_id: str
    case_id: str
    created_at: str
    outcome_status: str
    approved_credit_amount: float
    applied_credit_amount: float
    remaining_variance_amount: float
    case_path: Path
    settlement_path: Path
    attestation_path: Path
    closure_pack_path: Path
    receipt_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "case_path",
            "settlement_path",
            "attestation_path",
            "closure_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
