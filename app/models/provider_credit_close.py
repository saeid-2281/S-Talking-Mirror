from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProviderCreditCloseGate:
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
class ProviderCreditSettlementSource:
    settlement_id: str
    case_id: str
    outcome_status: str
    provider: str
    invoice_id: str
    currency: str
    requested_credit_amount: float
    approved_credit_amount: float
    applied_credit_amount: float
    remaining_variance_amount: float
    settlement_path: Path
    attestation_path: Path
    closure_pack_path: Path
    receipt_path: Path
    settlement_sha256: str
    attestation_sha256: str
    closure_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "settlement_path",
            "attestation_path",
            "closure_pack_path",
            "receipt_path",
        ):
            payload[field_name] = Path(payload[field_name]).name
        return payload


@dataclass(frozen=True)
class ProviderCreditCloseSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    accounting_period: str
    status: str
    status_summary: str
    close_gate: str
    recommended_decision: str
    selected_settlement_count: int
    verified_source_count: int
    rejected_source_count: int
    settled_count: int
    unresolved_count: int
    total_requested_credit: float
    total_approved_credit: float
    total_applied_credit: float
    total_remaining_variance: float
    recovery_rate_percent: float
    currency: str
    sources: tuple[ProviderCreditSettlementSource, ...] = field(default_factory=tuple)
    gates: tuple[ProviderCreditCloseGate, ...] = field(default_factory=tuple)

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
            "accounting_period": self.accounting_period,
            "status": self.status,
            "status_summary": self.status_summary,
            "close_gate": self.close_gate,
            "recommended_decision": self.recommended_decision,
            "selected_settlement_count": self.selected_settlement_count,
            "verified_source_count": self.verified_source_count,
            "rejected_source_count": self.rejected_source_count,
            "settled_count": self.settled_count,
            "unresolved_count": self.unresolved_count,
            "total_requested_credit": self.total_requested_credit,
            "total_approved_credit": self.total_approved_credit,
            "total_applied_credit": self.total_applied_credit,
            "total_remaining_variance": self.total_remaining_variance,
            "recovery_rate_percent": self.recovery_rate_percent,
            "currency": self.currency,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "sources": [source.to_dict() for source in self.sources],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class ProviderCreditCloseRecord:
    close_id: str
    created_at: str
    accounting_period: str
    outcome_status: str
    total_applied_credit: float
    total_remaining_variance: float
    snapshot_path: Path
    close_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "close_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
