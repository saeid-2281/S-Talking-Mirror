from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.financial_audit import (
    FinancialAuditCloseSource,
    FinancialAuditGate,
    FinancialAuditInvoiceFinding,
    FinancialAuditRecord,
    FinancialAuditReconciliationSource,
    FinancialAuditSnapshot,
)
from app.services.billing_reconciliation_service import BillingReconciliationService
from app.services.provider_credit_close_service import ProviderCreditCloseService


class FinancialAuditService:
    """Verify invoice-to-ledger-to-credit financial integrity without mutations.

    Phase 78 consumes immutable Phase 75 reconciliation evidence and Phase 77
    provider-credit closes. It proves that provider invoice totals, reviewed
    internal ledger totals, dispute credits and final accounting closes reconcile
    within a human-selected tolerance. No provider, payment or ledger mutation is
    performed by this service.
    """

    SCHEMA_VERSION = 1
    MAX_AMOUNT = Decimal("1000000000")
    MAX_TOLERANCE = Decimal("1000000")
    _MONEY_QUANT = Decimal("0.0001")
    _PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        billing_reconciliation_service: BillingReconciliationService,
        provider_credit_close_service: ProviderCreditCloseService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.billing_reconciliation_service = billing_reconciliation_service
        self.provider_credit_close_service = provider_credit_close_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "financial-audit"
        self.snapshots_dir = self.root / "snapshots"
        self.audits_dir = self.root / "audits"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.audits_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_reconciliation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.results_dir, "*-result.json"
        )

    def default_reconciliation_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.attestations_dir,
            "*-attestation.json",
        )

    def default_reconciliation_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.dispute_packs_dir,
            "*-dispute-pack.zip",
        )

    def default_reconciliation_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.receipts_dir,
            "*-receipt.json",
        )

    def default_close_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(self.provider_credit_close_service.closes_dir, "*.json")

    def default_close_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.provider_credit_close_service.attestations_dir,
            "*-attestation.json",
        )

    def default_close_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.provider_credit_close_service.audit_packs_dir,
            "*-audit-pack.zip",
        )

    def default_close_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.provider_credit_close_service.receipts_dir,
            "*-receipt.json",
        )

    def snapshot(
        self,
        *,
        accounting_period: str,
        tolerance_amount: float | str = 0.01,
        reconciliation_paths: Iterable[Path] | None = None,
        reconciliation_attestation_paths: Iterable[Path] | None = None,
        reconciliation_pack_paths: Iterable[Path] | None = None,
        reconciliation_receipt_paths: Iterable[Path] | None = None,
        close_paths: Iterable[Path] | None = None,
        close_attestation_paths: Iterable[Path] | None = None,
        close_pack_paths: Iterable[Path] | None = None,
        close_receipt_paths: Iterable[Path] | None = None,
    ) -> FinancialAuditSnapshot:
        period = self._clean_text(accounting_period, required=True, limit=16)
        tolerance = self._decimal(tolerance_amount)
        if tolerance is None or tolerance < 0 or tolerance > self.MAX_TOLERANCE:
            tolerance = Decimal("0.01")

        reconciliation_selected = tuple(
            Path(path)
            for path in (
                reconciliation_paths or self.default_reconciliation_paths()
            )
        )
        reconciliation_attestations = tuple(
            Path(path)
            for path in (
                reconciliation_attestation_paths
                or self.default_reconciliation_attestation_paths()
            )
        )
        reconciliation_packs = tuple(
            Path(path)
            for path in (
                reconciliation_pack_paths or self.default_reconciliation_pack_paths()
            )
        )
        reconciliation_receipts = tuple(
            Path(path)
            for path in (
                reconciliation_receipt_paths
                or self.default_reconciliation_receipt_paths()
            )
        )
        close_selected = tuple(
            Path(path) for path in (close_paths or self.default_close_paths())
        )
        close_attestations = tuple(
            Path(path)
            for path in (
                close_attestation_paths or self.default_close_attestation_paths()
            )
        )
        close_packs = tuple(
            Path(path) for path in (close_pack_paths or self.default_close_pack_paths())
        )
        close_receipts = tuple(
            Path(path)
            for path in (close_receipt_paths or self.default_close_receipt_paths())
        )

        reconciliation_sources, reconciliation_rejected = (
            self._collect_reconciliation_sources(
                results=reconciliation_selected,
                attestations=reconciliation_attestations,
                packs=reconciliation_packs,
                receipts=reconciliation_receipts,
            )
        )
        close_sources, close_rejected, settlement_rows = self._collect_close_sources(
            closes=close_selected,
            attestations=close_attestations,
            packs=close_packs,
            receipts=close_receipts,
            accounting_period=period,
        )

        gates: list[FinancialAuditGate] = []
        period_valid = bool(self._PERIOD_RE.fullmatch(period))
        gates.append(
            self._gate(
                "accounting_period",
                "Accounting period",
                "pass" if period_valid else "block",
                (
                    f"Accounting period {period} is valid."
                    if period_valid
                    else "Accounting period must use YYYY-MM."
                ),
                "Enter a valid accounting period." if not period_valid else "",
            )
        )

        if not reconciliation_selected:
            gates.append(
                self._gate(
                    "reconciliation_sources_present",
                    "Phase 75 reconciliation evidence",
                    "block",
                    "No Phase 75 reconciliation result was selected.",
                    "Select verified Phase 75 result, attestation, pack and receipt evidence.",
                )
            )
        elif reconciliation_rejected:
            gates.append(
                self._gate(
                    "reconciliation_sources_verified",
                    "Reconciliation evidence integrity",
                    "block",
                    f"{reconciliation_rejected} reconciliation source set(s) were rejected.",
                    "Restore the original Phase 75 evidence and retry.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "reconciliation_sources_verified",
                    "Reconciliation evidence integrity",
                    "pass",
                    f"{len(reconciliation_sources)} reconciliation source set(s) verified.",
                    "",
                )
            )

        if close_rejected:
            gates.append(
                self._gate(
                    "close_sources_verified",
                    "Phase 77 close evidence integrity",
                    "block",
                    f"{close_rejected} provider-credit close source set(s) were rejected.",
                    "Restore the original Phase 77 close evidence and retry.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "close_sources_verified",
                    "Phase 77 close evidence integrity",
                    "pass",
                    f"{len(close_sources)} close source set(s) verified for {period}.",
                    "",
                )
            )

        invoice_keys = [
            self._invoice_key(source.provider, source.invoice_id, source.currency)
            for source in reconciliation_sources
        ]
        duplicate_invoice_count = len(invoice_keys) - len(set(invoice_keys))
        gates.append(
            self._gate(
                "unique_reconciliation_invoice",
                "Unique reconciliation per invoice",
                "pass" if duplicate_invoice_count == 0 else "block",
                (
                    "Each provider invoice appears once in the financial audit scope."
                    if duplicate_invoice_count == 0
                    else f"{duplicate_invoice_count} duplicate reconciliation invoice record(s) detected."
                ),
                "Remove duplicate reconciliation evidence before auditing."
                if duplicate_invoice_count
                else "",
            )
        )

        currencies = {
            source.currency.upper()
            for source in reconciliation_sources
            if source.currency.strip()
        }
        currencies.update(
            source.currency.upper() for source in close_sources if source.currency.strip()
        )
        currency_ok = len(currencies) <= 1
        gates.append(
            self._gate(
                "single_currency",
                "Single-currency audit scope",
                "pass" if currency_ok else "block",
                (
                    f"Audit scope uses {next(iter(currencies), 'no')} currency."
                    if currency_ok
                    else f"Audit scope mixes {len(currencies)} currencies."
                ),
                "Audit each currency independently." if not currency_ok else "",
            )
        )

        settlement_credit_by_invoice: dict[tuple[str, str, str], Decimal] = {}
        settlement_count_by_invoice: dict[tuple[str, str, str], int] = {}
        settlement_id_seen: set[str] = set()
        duplicate_settlement_ids = 0
        for row in settlement_rows:
            settlement_id = str(row.get("settlement_id") or "")
            if settlement_id in settlement_id_seen:
                duplicate_settlement_ids += 1
            settlement_id_seen.add(settlement_id)
            key = self._invoice_key(
                str(row.get("provider") or ""),
                str(row.get("invoice_id") or ""),
                str(row.get("currency") or ""),
            )
            amount = self._decimal(row.get("applied_credit_amount")) or Decimal("0")
            settlement_credit_by_invoice[key] = settlement_credit_by_invoice.get(
                key, Decimal("0")
            ) + amount
            settlement_count_by_invoice[key] = settlement_count_by_invoice.get(key, 0) + 1

        gates.append(
            self._gate(
                "unique_settlement_application",
                "Unique settlement application",
                "pass" if duplicate_settlement_ids == 0 else "block",
                (
                    "No settlement identifier is applied more than once."
                    if duplicate_settlement_ids == 0
                    else f"{duplicate_settlement_ids} duplicate settlement application(s) detected."
                ),
                "Remove duplicate close evidence before auditing."
                if duplicate_settlement_ids
                else "",
            )
        )

        findings: list[FinancialAuditInvoiceFinding] = []
        matched_invoice_count = 0
        unmatched_invoice_count = 0
        residual_failure_count = 0
        unmatched_settlement_keys = set(settlement_credit_by_invoice)

        for source in reconciliation_sources:
            key = self._invoice_key(source.provider, source.invoice_id, source.currency)
            unmatched_settlement_keys.discard(key)
            settlement_credit = settlement_credit_by_invoice.get(key, Decimal("0"))
            settlement_count = settlement_count_by_invoice.get(key, 0)
            net_invoice = Decimal(str(source.net_invoice_amount))
            ledger_total = Decimal(str(source.ledger_total_amount))
            original_variance = net_invoice - ledger_total
            final_net = net_invoice - settlement_credit
            residual = final_net - ledger_total
            requires_settlement = abs(original_variance) > tolerance
            settlement_present = settlement_count > 0
            matched = (not requires_settlement) or settlement_present
            residual_ok = abs(residual) <= tolerance
            status = "verified" if matched and residual_ok else "withheld"
            if matched:
                matched_invoice_count += 1
            else:
                unmatched_invoice_count += 1
            if not residual_ok:
                residual_failure_count += 1

            findings.append(
                FinancialAuditInvoiceFinding(
                    provider=source.provider,
                    invoice_id=source.invoice_id,
                    currency=source.currency,
                    invoice_total_amount=source.invoice_total_amount,
                    original_provider_credits_amount=source.provider_credits_amount,
                    net_invoice_amount=source.net_invoice_amount,
                    ledger_total_amount=source.ledger_total_amount,
                    settlement_credit_amount=float(settlement_credit),
                    final_net_invoice_amount=float(final_net),
                    residual_variance_amount=float(residual),
                    settlement_count=settlement_count,
                    status=status,
                )
            )

        if unmatched_settlement_keys:
            unmatched_invoice_count += len(unmatched_settlement_keys)

        gates.append(
            self._gate(
                "invoice_settlement_coverage",
                "Invoice-to-settlement coverage",
                "pass" if unmatched_invoice_count == 0 else "block",
                (
                    "All reconciliation variances and settlement credits map to a unique invoice."
                    if unmatched_invoice_count == 0
                    else f"{unmatched_invoice_count} invoice/settlement mapping issue(s) remain."
                ),
                "Match each disputed invoice to the corresponding Phase 77 settlement close."
                if unmatched_invoice_count
                else "",
            )
        )

        gates.append(
            self._gate(
                "residual_variance",
                "Final net invoice versus ledger",
                "pass" if residual_failure_count == 0 else "block",
                (
                    f"All invoices reconcile within {self._money_text(tolerance)}."
                    if residual_failure_count == 0
                    else f"{residual_failure_count} invoice(s) exceed the selected residual tolerance."
                ),
                "Review provider credits, settlement application and ledger totals."
                if residual_failure_count
                else "",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        status = "blocked" if blocker_count else "ready_with_warnings" if warning_count else "ready"
        audit_gate = "hold" if blocker_count else "manual_review" if warning_count else "allow"
        recommended_decision = (
            "withhold_financial_audit"
            if blocker_count
            else "review_financial_audit"
            if warning_count
            else "record_financial_audit"
        )
        summary = (
            f"{len(findings)} invoice(s); {matched_invoice_count} matched; "
            f"{residual_failure_count} residual variance issue(s)."
        )

        total_invoice = sum(Decimal(str(item.invoice_total_amount)) for item in findings)
        total_original_credits = sum(
            Decimal(str(item.original_provider_credits_amount)) for item in findings
        )
        total_settlement_credits = sum(
            Decimal(str(item.settlement_credit_amount)) for item in findings
        )
        total_final_net = sum(
            Decimal(str(item.final_net_invoice_amount)) for item in findings
        )
        total_ledger = sum(Decimal(str(item.ledger_total_amount)) for item in findings)
        total_residual = sum(
            Decimal(str(item.residual_variance_amount)) for item in findings
        )

        return FinancialAuditSnapshot(
            snapshot_id=f"financial-audit-snapshot-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            accounting_period=period,
            status=status,
            status_summary=summary,
            audit_gate=audit_gate,
            recommended_decision=recommended_decision,
            selected_reconciliation_count=len(reconciliation_selected),
            verified_reconciliation_count=len(reconciliation_sources),
            selected_close_count=len(close_selected),
            verified_close_count=len(close_sources),
            rejected_source_count=reconciliation_rejected + close_rejected,
            invoice_count=len(findings),
            matched_invoice_count=matched_invoice_count,
            unmatched_invoice_count=unmatched_invoice_count,
            duplicate_invoice_count=duplicate_invoice_count,
            total_invoice_amount=float(total_invoice),
            total_original_provider_credits=float(total_original_credits),
            total_settlement_credits=float(total_settlement_credits),
            total_final_net_invoice=float(total_final_net),
            total_ledger_amount=float(total_ledger),
            total_residual_variance=float(total_residual),
            currency=next(iter(currencies), ""),
            tolerance_amount=float(tolerance),
            reconciliation_sources=tuple(reconciliation_sources),
            close_sources=tuple(close_sources),
            findings=tuple(findings),
            gates=tuple(gates),
        )

    def export_snapshot(self, snapshot: FinancialAuditSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        return path

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Financial audit snapshot is unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Financial audit snapshot SHA-256 changed."
        if payload.get("status") not in {"ready", "ready_with_warnings", "blocked"}:
            return False, "Financial audit snapshot status is invalid."
        if not self._verify_common_contract(payload):
            return False, "Financial audit snapshot safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Financial audit snapshot contains private material."
        return True, "Financial audit snapshot verified."

    def create_audit(
        self,
        snapshot: FinancialAuditSnapshot,
        *,
        owner: str,
        statement: str,
        acknowledge: bool = False,
    ) -> FinancialAuditRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Financial audit snapshot contains blockers.")
        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1600)
        if not owner_text or not statement_text:
            return self._blocked("Financial audit owner and statement are required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked("Financial audit fields contain private or secret material.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the financial integrity evidence before recording the audit.",
            }

        snapshot_path = self.export_snapshot(snapshot)
        audit_id = f"financial-audit-{uuid.uuid4().hex[:12]}"
        audit_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "audit_id": audit_id,
            "created_at": self._now_iso(),
            "accounting_period": snapshot.accounting_period,
            "outcome_status": "verified",
            "decision": "record_financial_audit",
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "currency": snapshot.currency,
            "invoice_count": snapshot.invoice_count,
            "total_invoice_amount": self._money_text(
                Decimal(str(snapshot.total_invoice_amount))
            ),
            "total_original_provider_credits": self._money_text(
                Decimal(str(snapshot.total_original_provider_credits))
            ),
            "total_settlement_credits": self._money_text(
                Decimal(str(snapshot.total_settlement_credits))
            ),
            "total_final_net_invoice": self._money_text(
                Decimal(str(snapshot.total_final_net_invoice))
            ),
            "total_ledger_amount": self._money_text(
                Decimal(str(snapshot.total_ledger_amount))
            ),
            "total_residual_variance": self._money_text(
                Decimal(str(snapshot.total_residual_variance))
            ),
            "tolerance_amount": self._money_text(Decimal(str(snapshot.tolerance_amount))),
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
            "source_reconciliations": [
                {
                    "reconciliation_id": source.reconciliation_id,
                    "result_filename": source.result_path.name,
                    "result_sha256": source.result_sha256,
                    "attestation_filename": source.attestation_path.name,
                    "attestation_sha256": source.attestation_sha256,
                    "dispute_pack_filename": source.dispute_pack_path.name,
                    "dispute_pack_sha256": source.dispute_pack_sha256,
                    "receipt_filename": source.receipt_path.name,
                    "receipt_sha256": source.receipt_sha256,
                }
                for source in snapshot.reconciliation_sources
            ],
            "source_closes": [
                {
                    "close_id": source.close_id,
                    "close_filename": source.close_path.name,
                    "close_sha256": source.close_sha256,
                    "attestation_filename": source.attestation_path.name,
                    "attestation_sha256": source.attestation_sha256,
                    "audit_pack_filename": source.audit_pack_path.name,
                    "audit_pack_sha256": source.audit_pack_sha256,
                    "receipt_filename": source.receipt_path.name,
                    "receipt_sha256": source.receipt_sha256,
                }
                for source in snapshot.close_sources
            ],
        }
        audit_payload.update(self._safety_contract())
        audit_payload["audit_sha256"] = self._payload_digest(audit_payload)
        audit_path = self.audits_dir / f"{audit_id}.json"
        self._write_json(audit_path, audit_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "audit_id": audit_id,
            "created_at": self._now_iso(),
            "accounting_period": snapshot.accounting_period,
            "status": "verified",
            "audit_filename": audit_path.name,
            "audit_sha256": self._sha256(audit_path),
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "human_decision_required": True,
        }
        attestation_payload.update(self._safety_contract())
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = self.attestations_dir / f"{audit_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_audit_pack(
            audit_id=audit_id,
            snapshot_path=snapshot_path,
            audit_path=audit_path,
            attestation_path=attestation_path,
            reconciliation_sources=snapshot.reconciliation_sources,
            close_sources=snapshot.close_sources,
        )
        return FinancialAuditRecord(
            audit_id=audit_id,
            created_at=str(audit_payload["created_at"]),
            accounting_period=snapshot.accounting_period,
            outcome_status="verified",
            invoice_count=snapshot.invoice_count,
            total_ledger_amount=snapshot.total_ledger_amount,
            total_residual_variance=snapshot.total_residual_variance,
            snapshot_path=snapshot_path,
            audit_path=audit_path,
            attestation_path=attestation_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_audit(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Financial audit record is unreadable."
        expected = str(payload.pop("audit_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Financial audit record SHA-256 changed."
        if payload.get("outcome_status") != "verified":
            return False, "Financial audit outcome is invalid."
        if payload.get("human_reviewed") is not True:
            return False, "Financial audit record is not human reviewed."
        if not self._verify_common_contract(payload):
            return False, "Financial audit safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Financial audit record contains private material."
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != payload.get(
            "snapshot_sha256"
        ):
            return False, "Linked financial audit snapshot changed."
        snapshot_ok, _detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return False, "Linked financial audit snapshot is invalid."
        if not self._verify_linked_sources(payload):
            return False, "Linked financial source evidence changed."
        return True, "Financial audit record verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Financial audit attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Financial audit attestation SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Financial audit attestation safety contract changed."
        audit_path = self.audits_dir / str(payload.get("audit_filename") or "")
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        for source_path, hash_key in (
            (audit_path, "audit_sha256"),
            (snapshot_path, "snapshot_sha256"),
        ):
            if not source_path.is_file() or self._sha256(source_path) != payload.get(hash_key):
                return False, "Linked financial audit artifact changed."
        audit_ok, _detail = self.verify_audit(audit_path)
        if not audit_ok:
            return False, "Linked financial audit record is invalid."
        return True, "Financial audit attestation verified."

    def verify_audit_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        receipt = self._read_json(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Financial audit pack or receipt is missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if not expected or expected != self._payload_digest(receipt):
            return False, "Financial audit receipt SHA-256 changed."
        if not self._verify_common_contract(receipt):
            return False, "Financial audit receipt safety contract changed."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Financial audit pack filename changed."
        if int(receipt.get("pack_size_bytes") or -1) != pack_path.stat().st_size:
            return False, "Financial audit pack size changed."
        if receipt.get("pack_sha256") != self._sha256(pack_path):
            return False, "Financial audit pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path, "r") as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                expected_manifest = str(manifest.pop("manifest_sha256", ""))
                if not expected_manifest or expected_manifest != self._payload_digest(
                    manifest
                ):
                    return False, "Financial audit manifest SHA-256 changed."
                for entry in manifest.get("entries", []):
                    if not isinstance(entry, Mapping):
                        return False, "Financial audit manifest entry is invalid."
                    name = str(entry.get("path") or "")
                    data = archive.read(name)
                    if len(data) != int(entry.get("size_bytes") or -1):
                        return False, "Financial audit pack entry size changed."
                    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                        return False, "Financial audit pack entry SHA-256 changed."
        except (OSError, KeyError, ValueError, TypeError, zipfile.BadZipFile):
            return False, "Financial audit pack is unreadable."
        return True, "Financial audit pack and receipt verified."

    def _collect_reconciliation_sources(
        self,
        *,
        results: tuple[Path, ...],
        attestations: tuple[Path, ...],
        packs: tuple[Path, ...],
        receipts: tuple[Path, ...],
    ) -> tuple[list[FinancialAuditReconciliationSource], int]:
        attestation_index = self._index_json(attestations, "reconciliation_id")
        receipt_index = self._index_json(receipts, "reconciliation_id")
        pack_index = {
            self._identifier_from_pack_name(path.name, "-dispute-pack.zip"): path
            for path in packs
            if self._identifier_from_pack_name(path.name, "-dispute-pack.zip")
        }
        sources: list[FinancialAuditReconciliationSource] = []
        rejected = 0
        for result_path in results:
            payload = self._read_json(result_path)
            reconciliation_id = str((payload or {}).get("reconciliation_id") or "")
            attestation_path = attestation_index.get(reconciliation_id)
            pack_path = pack_index.get(reconciliation_id)
            receipt_path = receipt_index.get(reconciliation_id)
            if not payload or not all(
                (reconciliation_id, attestation_path, pack_path, receipt_path)
            ):
                rejected += 1
                continue
            result_ok, _detail = self.billing_reconciliation_service.verify_result(
                result_path
            )
            attestation_ok, _detail = (
                self.billing_reconciliation_service.verify_attestation(attestation_path)
            )
            pack_ok, _detail = self.billing_reconciliation_service.verify_dispute_pack(
                pack_path, receipt_path
            )
            if not all((result_ok, attestation_ok, pack_ok)):
                rejected += 1
                continue
            sources.append(
                FinancialAuditReconciliationSource(
                    reconciliation_id=reconciliation_id,
                    provider=str(payload.get("provider") or ""),
                    invoice_id=str(payload.get("invoice_id") or ""),
                    currency=str(payload.get("currency") or ""),
                    invoice_total_amount=self._safe_float(
                        payload.get("invoice_total_amount")
                    ),
                    provider_credits_amount=self._safe_float(
                        payload.get("provider_credits_amount")
                    ),
                    net_invoice_amount=self._safe_float(payload.get("net_invoice_amount")),
                    ledger_total_amount=self._safe_float(payload.get("ledger_total_amount")),
                    variance_amount=self._safe_float(payload.get("variance_amount")),
                    result_path=result_path,
                    attestation_path=attestation_path,
                    dispute_pack_path=pack_path,
                    receipt_path=receipt_path,
                    result_sha256=self._sha256(result_path),
                    attestation_sha256=self._sha256(attestation_path),
                    dispute_pack_sha256=self._sha256(pack_path),
                    receipt_sha256=self._sha256(receipt_path),
                )
            )
        return sources, rejected

    def _collect_close_sources(
        self,
        *,
        closes: tuple[Path, ...],
        attestations: tuple[Path, ...],
        packs: tuple[Path, ...],
        receipts: tuple[Path, ...],
        accounting_period: str,
    ) -> tuple[list[FinancialAuditCloseSource], int, list[dict[str, object]]]:
        attestation_index = self._index_json(attestations, "close_id")
        receipt_index = self._index_json(receipts, "close_id")
        pack_index = {
            self._identifier_from_pack_name(path.name, "-audit-pack.zip"): path
            for path in packs
            if self._identifier_from_pack_name(path.name, "-audit-pack.zip")
        }
        sources: list[FinancialAuditCloseSource] = []
        settlement_rows: list[dict[str, object]] = []
        rejected = 0
        for close_path in closes:
            payload = self._read_json(close_path)
            close_id = str((payload or {}).get("close_id") or "")
            if payload and str(payload.get("accounting_period") or "") != accounting_period:
                continue
            attestation_path = attestation_index.get(close_id)
            pack_path = pack_index.get(close_id)
            receipt_path = receipt_index.get(close_id)
            if not payload or not all((close_id, attestation_path, pack_path, receipt_path)):
                rejected += 1
                continue
            close_ok, _detail = self.provider_credit_close_service.verify_close(close_path)
            attestation_ok, _detail = self.provider_credit_close_service.verify_attestation(
                attestation_path
            )
            pack_ok, _detail = self.provider_credit_close_service.verify_audit_pack(
                pack_path, receipt_path
            )
            if not all((close_ok, attestation_ok, pack_ok)):
                rejected += 1
                continue
            snapshot_path = self.provider_credit_close_service.snapshots_dir / str(
                payload.get("snapshot_filename") or ""
            )
            snapshot_payload = self._read_json(snapshot_path)
            if snapshot_payload is None:
                rejected += 1
                continue
            source_rows = snapshot_payload.get("sources")
            if not isinstance(source_rows, list):
                rejected += 1
                continue
            for row in source_rows:
                if isinstance(row, Mapping):
                    settlement_rows.append(dict(row))
            sources.append(
                FinancialAuditCloseSource(
                    close_id=close_id,
                    accounting_period=str(payload.get("accounting_period") or ""),
                    currency=str(payload.get("currency") or ""),
                    total_applied_credit=self._safe_float(payload.get("total_applied_credit")),
                    total_remaining_variance=self._safe_float(
                        payload.get("total_remaining_variance")
                    ),
                    close_path=close_path,
                    attestation_path=attestation_path,
                    audit_pack_path=pack_path,
                    receipt_path=receipt_path,
                    close_sha256=self._sha256(close_path),
                    attestation_sha256=self._sha256(attestation_path),
                    audit_pack_sha256=self._sha256(pack_path),
                    receipt_sha256=self._sha256(receipt_path),
                )
            )
        return sources, rejected, settlement_rows

    def _verify_linked_sources(self, payload: Mapping[str, object]) -> bool:
        reconciliations = payload.get("source_reconciliations")
        closes = payload.get("source_closes")
        if not isinstance(reconciliations, list) or not reconciliations:
            return False
        if not isinstance(closes, list):
            return False
        for row in reconciliations:
            if not isinstance(row, Mapping):
                return False
            result_path = self.billing_reconciliation_service.results_dir / str(
                row.get("result_filename") or ""
            )
            attestation_path = self.billing_reconciliation_service.attestations_dir / str(
                row.get("attestation_filename") or ""
            )
            pack_path = self.billing_reconciliation_service.dispute_packs_dir / str(
                row.get("dispute_pack_filename") or ""
            )
            receipt_path = self.billing_reconciliation_service.receipts_dir / str(
                row.get("receipt_filename") or ""
            )
            for source_path, hash_key in (
                (result_path, "result_sha256"),
                (attestation_path, "attestation_sha256"),
                (pack_path, "dispute_pack_sha256"),
                (receipt_path, "receipt_sha256"),
            ):
                if not source_path.is_file() or self._sha256(source_path) != row.get(hash_key):
                    return False
        for row in closes:
            if not isinstance(row, Mapping):
                return False
            close_path = self.provider_credit_close_service.closes_dir / str(
                row.get("close_filename") or ""
            )
            attestation_path = self.provider_credit_close_service.attestations_dir / str(
                row.get("attestation_filename") or ""
            )
            pack_path = self.provider_credit_close_service.audit_packs_dir / str(
                row.get("audit_pack_filename") or ""
            )
            receipt_path = self.provider_credit_close_service.receipts_dir / str(
                row.get("receipt_filename") or ""
            )
            for source_path, hash_key in (
                (close_path, "close_sha256"),
                (attestation_path, "attestation_sha256"),
                (pack_path, "audit_pack_sha256"),
                (receipt_path, "receipt_sha256"),
            ):
                if not source_path.is_file() or self._sha256(source_path) != row.get(hash_key):
                    return False
        return True

    def _create_audit_pack(
        self,
        *,
        audit_id: str,
        snapshot_path: Path,
        audit_path: Path,
        attestation_path: Path,
        reconciliation_sources: Iterable[FinancialAuditReconciliationSource],
        close_sources: Iterable[FinancialAuditCloseSource],
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "financial-audit/snapshot.json": snapshot_path.read_bytes(),
            "financial-audit/audit.json": audit_path.read_bytes(),
            "financial-audit/attestation.json": attestation_path.read_bytes(),
        }
        for index, source in enumerate(reconciliation_sources, start=1):
            prefix = f"phase75/reconciliation-{index:03d}"
            entries[f"{prefix}/result.json"] = source.result_path.read_bytes()
            entries[f"{prefix}/attestation.json"] = source.attestation_path.read_bytes()
        for index, source in enumerate(close_sources, start=1):
            prefix = f"phase77/close-{index:03d}"
            entries[f"{prefix}/close.json"] = source.close_path.read_bytes()
            entries[f"{prefix}/attestation.json"] = source.attestation_path.read_bytes()

        manifest_entries = [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(entries.items())
        ]
        manifest: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "audit_id": audit_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)

        pack_path = self.audit_packs_dir / f"{audit_id}-audit-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))

        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "audit_id": audit_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{audit_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _gate(
        self,
        code: str,
        label: str,
        status: str,
        detail: str,
        remediation: str,
    ) -> FinancialAuditGate:
        severity = "blocker" if status == "block" else "warning" if status == "warn" else "info"
        return FinancialAuditGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    def _safety_contract(self) -> dict[str, bool]:
        return {
            "automatic_ledger_change": False,
            "automatic_invoice_change": False,
            "automatic_payment_action": False,
            "automatic_credit_action": False,
            "automatic_provider_action": False,
            "automatic_accounting_export": False,
            "automatic_evidence_upload": False,
        }

    def _verify_common_contract(self, payload: Mapping[str, object]) -> bool:
        return all(payload.get(key) is False for key in self._safety_contract())

    def _contains_private_payload(self, payload: Mapping[str, object]) -> bool:
        safe_filename_keys = {
            "snapshot_filename",
            "audit_filename",
            "result_filename",
            "attestation_filename",
            "dispute_pack_filename",
            "close_filename",
            "audit_pack_filename",
            "receipt_filename",
            "pack_filename",
            "settlement_filename",
            "closure_pack_filename",
        }

        def walk(value: object) -> bool:
            if isinstance(value, Mapping):
                return any(
                    walk(item)
                    for key, item in value.items()
                    if str(key) not in safe_filename_keys
                )
            if isinstance(value, (list, tuple, set)):
                return any(walk(item) for item in value)
            if isinstance(value, str):
                return self._contains_private_material(value)
            return False

        return walk(payload)

    def _contains_private_material(self, value: str) -> bool:
        text = str(value or "")
        return bool(self._SECRET_RE.search(text) or self._WINDOWS_PATH_RE.search(text))

    def _invoice_key(self, provider: str, invoice_id: str, currency: str) -> tuple[str, str, str]:
        return (
            str(provider or "").strip().casefold(),
            str(invoice_id or "").strip().casefold(),
            str(currency or "").strip().upper(),
        )

    def _index_json(self, paths: Iterable[Path], key: str) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for path in paths:
            payload = self._read_json(path)
            identifier = str((payload or {}).get(key) or "")
            if identifier:
                result[identifier] = path
        return result

    @staticmethod
    def _identifier_from_pack_name(name: str, suffix: str) -> str:
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    @staticmethod
    def _sorted_files(root: Path, pattern: str) -> tuple[Path, ...]:
        return tuple(sorted(root.glob(pattern), key=lambda path: path.name.casefold()))

    def _clean_text(self, value: object, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
        if required and not text:
            return ""
        return text[:limit]

    def _decimal(self, value: object) -> Decimal | None:
        try:
            parsed = Decimal(str(value)).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not parsed.is_finite() or abs(parsed) > self.MAX_AMOUNT:
            return None
        return parsed

    def _money_text(self, value: Decimal) -> str:
        try:
            decimal_value = Decimal(str(value)).quantize(
                self._MONEY_QUANT, rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError, TypeError):
            decimal_value = Decimal("0")
        return format(decimal_value, "f")

    def _safe_float(self, value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _blocked(self, detail: str) -> dict[str, str]:
        return {"status": "blocked", "detail": detail}

    def _now_iso(self) -> str:
        return self._now_provider().astimezone(timezone.utc).isoformat()

    @staticmethod
    def _json_bytes(payload: Mapping[str, object]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _payload_digest(self, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(self._json_bytes(payload)).hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
