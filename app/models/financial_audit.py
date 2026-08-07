from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FinancialAuditGate:
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
class FinancialAuditReconciliationSource:
    reconciliation_id: str
    provider: str
    invoice_id: str
    currency: str
    invoice_total_amount: float
    provider_credits_amount: float
    net_invoice_amount: float
    ledger_total_amount: float
    variance_amount: float
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
        for field_name in (
            "result_path",
            "attestation_path",
            "dispute_pack_path",
            "receipt_path",
        ):
            payload[field_name] = Path(payload[field_name]).name
        return payload


@dataclass(frozen=True)
class FinancialAuditCloseSource:
    close_id: str
    accounting_period: str
    currency: str
    total_applied_credit: float
    total_remaining_variance: float
    close_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path
    close_sha256: str
    attestation_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "close_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = Path(payload[field_name]).name
        return payload


@dataclass(frozen=True)
class FinancialAuditInvoiceFinding:
    provider: str
    invoice_id: str
    currency: str
    invoice_total_amount: float
    original_provider_credits_amount: float
    net_invoice_amount: float
    ledger_total_amount: float
    settlement_credit_amount: float
    final_net_invoice_amount: float
    residual_variance_amount: float
    settlement_count: int
    status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FinancialAuditSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    accounting_period: str
    status: str
    status_summary: str
    audit_gate: str
    recommended_decision: str
    selected_reconciliation_count: int
    verified_reconciliation_count: int
    selected_close_count: int
    verified_close_count: int
    rejected_source_count: int
    invoice_count: int
    matched_invoice_count: int
    unmatched_invoice_count: int
    duplicate_invoice_count: int
    total_invoice_amount: float
    total_original_provider_credits: float
    total_settlement_credits: float
    total_final_net_invoice: float
    total_ledger_amount: float
    total_residual_variance: float
    currency: str
    tolerance_amount: float
    reconciliation_sources: tuple[FinancialAuditReconciliationSource, ...] = field(
        default_factory=tuple
    )
    close_sources: tuple[FinancialAuditCloseSource, ...] = field(default_factory=tuple)
    findings: tuple[FinancialAuditInvoiceFinding, ...] = field(default_factory=tuple)
    gates: tuple[FinancialAuditGate, ...] = field(default_factory=tuple)

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
            "audit_gate": self.audit_gate,
            "recommended_decision": self.recommended_decision,
            "selected_reconciliation_count": self.selected_reconciliation_count,
            "verified_reconciliation_count": self.verified_reconciliation_count,
            "selected_close_count": self.selected_close_count,
            "verified_close_count": self.verified_close_count,
            "rejected_source_count": self.rejected_source_count,
            "invoice_count": self.invoice_count,
            "matched_invoice_count": self.matched_invoice_count,
            "unmatched_invoice_count": self.unmatched_invoice_count,
            "duplicate_invoice_count": self.duplicate_invoice_count,
            "total_invoice_amount": self.total_invoice_amount,
            "total_original_provider_credits": self.total_original_provider_credits,
            "total_settlement_credits": self.total_settlement_credits,
            "total_final_net_invoice": self.total_final_net_invoice,
            "total_ledger_amount": self.total_ledger_amount,
            "total_residual_variance": self.total_residual_variance,
            "currency": self.currency,
            "tolerance_amount": self.tolerance_amount,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "reconciliation_sources": [
                source.to_dict() for source in self.reconciliation_sources
            ],
            "close_sources": [source.to_dict() for source in self.close_sources],
            "findings": [finding.to_dict() for finding in self.findings],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class FinancialAuditRecord:
    audit_id: str
    created_at: str
    accounting_period: str
    outcome_status: str
    invoice_count: int
    total_ledger_amount: float
    total_residual_variance: float
    snapshot_path: Path
    audit_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "audit_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
