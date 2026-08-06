from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ReliabilityAssuranceGate:
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
class ReliabilityAssuranceSource:
    review_id: str
    decision_id: str
    baseline_id: str
    decision: str
    created_at: str
    age_days: int
    review_path: Path
    decision_path: Path
    review_sha256: str
    decision_sha256: str
    open_action_count: int = 0
    overdue_action_count: int = 0
    recurrent_pattern_count: int = 0
    ineffective_pattern_count: int = 0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["review_path"] = str(self.review_path)
        payload["decision_path"] = str(self.decision_path)
        return payload


@dataclass(frozen=True)
class ReliabilityAssuranceException:
    code: str
    review_id: str
    baseline_id: str
    category: str
    severity: str
    summary: str
    source_decision: str
    age_days: int
    status: str = "open"
    automatic: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReliabilityAssuranceSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    assurance_window_days: int
    status: str
    status_summary: str
    assurance_allowed: bool
    selected_review_count: int
    selected_decision_count: int
    verified_pair_count: int
    rejected_source_count: int
    ignored_pair_count: int
    close_effective_count: int
    monitoring_count: int
    escalation_count: int
    accepted_risk_count: int
    open_exception_count: int
    high_exception_count: int
    sources: tuple[ReliabilityAssuranceSource, ...] = field(default_factory=tuple)
    exceptions: tuple[ReliabilityAssuranceException, ...] = field(default_factory=tuple)
    gates: tuple[ReliabilityAssuranceGate, ...] = field(default_factory=tuple)

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
            "assurance_window_days": self.assurance_window_days,
            "status": self.status,
            "status_summary": self.status_summary,
            "assurance_allowed": self.assurance_allowed,
            "selected_review_count": self.selected_review_count,
            "selected_decision_count": self.selected_decision_count,
            "verified_pair_count": self.verified_pair_count,
            "rejected_source_count": self.rejected_source_count,
            "ignored_pair_count": self.ignored_pair_count,
            "close_effective_count": self.close_effective_count,
            "monitoring_count": self.monitoring_count,
            "escalation_count": self.escalation_count,
            "accepted_risk_count": self.accepted_risk_count,
            "open_exception_count": self.open_exception_count,
            "high_exception_count": self.high_exception_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "sources": [source.to_dict() for source in self.sources],
            "exceptions": [item.to_dict() for item in self.exceptions],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class ReliabilityAssuranceRecord:
    assurance_id: str
    created_at: str
    decision: str
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path
    source_count: int
    exception_count: int
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["attestation_path"] = str(self.attestation_path)
        payload["audit_pack_path"] = str(self.audit_pack_path)
        payload["receipt_path"] = str(self.receipt_path)
        return payload
