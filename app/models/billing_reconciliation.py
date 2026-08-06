from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BillingReconciliationGate:
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
class BillingInvoiceSource:
    invoice_id: str
    provider: str
    currency: str
    billing_period_start: str
    billing_period_end: str
    line_count: int
    unique_request_count: int
    duplicate_request_count: int
    total_amount: float
    invoice_path: Path
    invoice_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["invoice_path"] = str(self.invoice_path)
        return payload


@dataclass(frozen=True)
class BillingReplaySource:
    replay_id: str
    outcome_status: str
    attempted_jobs: int
    completed_jobs: int
    duplicate_api_requests: int
    duplicate_outputs: int
    result_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path
    result_sha256: str
    attestation_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "result_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload


@dataclass(frozen=True)
class BillingReconciliationSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    status: str
    status_summary: str
    release_gate: str
    recommended_decision: str
    selected_invoice_count: int
    verified_invoice_count: int
    selected_replay_count: int
    verified_replay_count: int
    rejected_source_count: int
    expected_request_count: int
    invoice_request_count: int
    invoice_total_amount: float
    invoice_currency: str
    invoices: tuple[BillingInvoiceSource, ...] = field(default_factory=tuple)
    replay_sources: tuple[BillingReplaySource, ...] = field(default_factory=tuple)
    gates: tuple[BillingReconciliationGate, ...] = field(default_factory=tuple)

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
            "selected_invoice_count": self.selected_invoice_count,
            "verified_invoice_count": self.verified_invoice_count,
            "selected_replay_count": self.selected_replay_count,
            "verified_replay_count": self.verified_replay_count,
            "rejected_source_count": self.rejected_source_count,
            "expected_request_count": self.expected_request_count,
            "invoice_request_count": self.invoice_request_count,
            "invoice_total_amount": self.invoice_total_amount,
            "invoice_currency": self.invoice_currency,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "invoices": [source.to_dict() for source in self.invoices],
            "replay_sources": [source.to_dict() for source in self.replay_sources],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class BillingReconciliationRecord:
    reconciliation_id: str
    created_at: str
    outcome_status: str
    snapshot_path: Path
    invoice_path: Path
    result_path: Path
    attestation_path: Path
    dispute_pack_path: Path
    receipt_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "invoice_path",
            "result_path",
            "attestation_path",
            "dispute_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
