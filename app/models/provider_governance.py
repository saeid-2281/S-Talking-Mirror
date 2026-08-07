from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProviderGovernanceGate:
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
class ProviderFinancialAuditSource:
    audit_id: str
    accounting_period: str
    audit_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path
    audit_sha256: str
    attestation_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "audit_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = Path(payload[field_name]).name
        return payload


@dataclass(frozen=True)
class ProviderPerformanceScorecard:
    provider: str
    session_count: int
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    retry_events: int
    job_success_rate: float
    failure_rate: float
    retry_rate: float
    average_files_per_minute: float
    average_health_score: float
    invoice_count: int
    invoice_total_amount: float
    settlement_adjustment_amount: float
    final_residual_variance: float
    billing_adjustment_rate: float
    billing_accuracy_score: float
    reliability_score: float
    overall_score: float
    risk_level: str
    recommended_governance: str
    evidence_status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class ProviderGovernanceSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    project_id: int | None
    status: str
    status_summary: str
    governance_gate: str
    recommended_decision: str
    minimum_sessions: int
    preferred_threshold: float
    approved_threshold: float
    watch_threshold: float
    selected_financial_audit_count: int
    verified_financial_audit_count: int
    rejected_financial_audit_count: int
    provider_count: int
    preferred_count: int
    approved_count: int
    watch_count: int
    restricted_count: int
    financial_sources: tuple[ProviderFinancialAuditSource, ...] = field(
        default_factory=tuple
    )
    scorecards: tuple[ProviderPerformanceScorecard, ...] = field(default_factory=tuple)
    gates: tuple[ProviderGovernanceGate, ...] = field(default_factory=tuple)

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
            "project_id": self.project_id,
            "status": self.status,
            "status_summary": self.status_summary,
            "governance_gate": self.governance_gate,
            "recommended_decision": self.recommended_decision,
            "minimum_sessions": self.minimum_sessions,
            "preferred_threshold": self.preferred_threshold,
            "approved_threshold": self.approved_threshold,
            "watch_threshold": self.watch_threshold,
            "selected_financial_audit_count": self.selected_financial_audit_count,
            "verified_financial_audit_count": self.verified_financial_audit_count,
            "rejected_financial_audit_count": self.rejected_financial_audit_count,
            "provider_count": self.provider_count,
            "preferred_count": self.preferred_count,
            "approved_count": self.approved_count,
            "watch_count": self.watch_count,
            "restricted_count": self.restricted_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "financial_sources": [source.to_dict() for source in self.financial_sources],
            "scorecards": [scorecard.to_dict() for scorecard in self.scorecards],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class ProviderGovernanceRecord:
    governance_id: str
    created_at: str
    project_id: int | None
    provider_count: int
    preferred_count: int
    approved_count: int
    watch_count: int
    restricted_count: int
    snapshot_path: Path
    governance_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "governance_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
