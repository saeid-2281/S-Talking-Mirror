from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ReliabilityAssuranceRenewalGate:
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
class ReliabilityAssuranceRenewalSource:
    assurance_id: str
    assurance_decision: str
    created_at: str
    age_days: int
    review_due_date: str
    days_until_review: int
    lifecycle_status: str
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path
    attestation_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str
    source_exception_count: int = 0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["attestation_path"] = str(self.attestation_path)
        payload["audit_pack_path"] = str(self.audit_pack_path)
        payload["receipt_path"] = str(self.receipt_path)
        return payload


@dataclass(frozen=True)
class ReliabilityAssuranceRenewalException:
    code: str
    assurance_id: str
    category: str
    severity: str
    summary: str
    due_date: str
    status: str = "open"
    automatic: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReliabilityAssuranceRenewalSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    validity_days: int
    due_soon_days: int
    status: str
    status_summary: str
    renewal_allowed: bool
    selected_attestation_count: int
    selected_pack_count: int
    selected_receipt_count: int
    verified_triplet_count: int
    rejected_source_count: int
    current_count: int
    due_soon_count: int
    overdue_count: int
    withheld_count: int
    open_exception_count: int
    high_exception_count: int
    sources: tuple[ReliabilityAssuranceRenewalSource, ...] = field(default_factory=tuple)
    exceptions: tuple[ReliabilityAssuranceRenewalException, ...] = field(default_factory=tuple)
    gates: tuple[ReliabilityAssuranceRenewalGate, ...] = field(default_factory=tuple)

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
            "validity_days": self.validity_days,
            "due_soon_days": self.due_soon_days,
            "status": self.status,
            "status_summary": self.status_summary,
            "renewal_allowed": self.renewal_allowed,
            "selected_attestation_count": self.selected_attestation_count,
            "selected_pack_count": self.selected_pack_count,
            "selected_receipt_count": self.selected_receipt_count,
            "verified_triplet_count": self.verified_triplet_count,
            "rejected_source_count": self.rejected_source_count,
            "current_count": self.current_count,
            "due_soon_count": self.due_soon_count,
            "overdue_count": self.overdue_count,
            "withheld_count": self.withheld_count,
            "open_exception_count": self.open_exception_count,
            "high_exception_count": self.high_exception_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "sources": [source.to_dict() for source in self.sources],
            "exceptions": [item.to_dict() for item in self.exceptions],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class ReliabilityAssuranceRenewalRecord:
    renewal_id: str
    created_at: str
    decision: str
    renewal_path: Path
    follow_up_path: Path
    audit_pack_path: Path
    receipt_path: Path
    source_count: int
    exception_count: int
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "renewal_path",
            "follow_up_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
