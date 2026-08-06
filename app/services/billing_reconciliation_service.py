from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.billing_reconciliation import (
    BillingInvoiceSource,
    BillingReconciliationGate,
    BillingReconciliationRecord,
    BillingReconciliationSnapshot,
    BillingReplaySource,
)
from app.services.recovery_replay_service import RecoveryReplayService


class BillingReconciliationService:
    """Reconcile provider invoices against verified recovery replay evidence.

    Phase 75 normalizes a locally selected provider invoice, compares it with
    reviewed internal usage totals and Phase 74 recovery evidence, and produces
    tamper-evident reconciliation or manual-dispute evidence. It never requests
    refunds, opens disputes, emails providers, uploads files or changes billing.
    """

    SCHEMA_VERSION = 1
    MAX_CSV_BYTES = 20 * 1024 * 1024
    MAX_INVOICE_LINES = 1_000_000
    MAX_COUNT = 1_000_000
    MAX_AMOUNT = Decimal("1000000000")
    MAX_VARIANCE_PERCENT = 1000.0
    _MONEY_QUANT = Decimal("0.0001")
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        recovery_replay_service: RecoveryReplayService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.recovery_replay_service = recovery_replay_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "billing-reconciliation"
        self.invoices_dir = self.root / "invoices"
        self.snapshots_dir = self.root / "snapshots"
        self.results_dir = self.root / "results"
        self.attestations_dir = self.root / "attestations"
        self.dispute_packs_dir = self.root / "dispute-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.invoices_dir,
            self.snapshots_dir,
            self.results_dir,
            self.attestations_dir,
            self.dispute_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_invoice_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(self.invoices_dir, "billing-invoice-*.json")

    def default_replay_result_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.recovery_replay_service.results_dir,
            "*-result.json",
        )

    def default_replay_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.recovery_replay_service.attestations_dir,
            "*-attestation.json",
        )

    def default_replay_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.recovery_replay_service.audit_packs_dir,
            "*-audit-pack.zip",
        )

    def default_replay_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.recovery_replay_service.receipts_dir,
            "*-receipt.json",
        )

    def import_invoice_csv(
        self,
        csv_path: Path,
        *,
        invoice_id: str,
        provider: str,
        currency: str,
        billing_period_start: str,
        billing_period_end: str,
        owner: str,
        notes: str = "",
        acknowledge: bool = False,
    ) -> BillingInvoiceSource | dict[str, str]:
        path = Path(csv_path)
        invoice_text = self._clean_text(invoice_id, required=True, limit=160)
        provider_text = self._clean_text(provider, required=True, limit=160)
        currency_text = self._clean_currency(currency)
        owner_text = self._clean_text(owner, required=True, limit=160)
        notes_text = self._clean_text(notes, required=False, limit=1200)
        period_start = self._parse_date(billing_period_start)
        period_end = self._parse_date(billing_period_end)

        if not path.is_file():
            return self._blocked("Provider invoice CSV was not found.")
        if path.stat().st_size <= 0 or path.stat().st_size > self.MAX_CSV_BYTES:
            return self._blocked("Provider invoice CSV size is outside the supported range.")
        if not all((invoice_text, provider_text, currency_text, owner_text)):
            return self._blocked("Invoice identifier, provider, currency and owner are required.")
        if period_start is None or period_end is None or period_start > period_end:
            return self._blocked("Billing period is invalid.")
        if any(
            self._contains_private_material(value)
            for value in (invoice_text, provider_text, owner_text, notes_text)
        ):
            return self._blocked("Invoice metadata contains private material.")

        parsed = self._parse_invoice_csv(path)
        if isinstance(parsed, dict):
            return parsed
        entries, total_amount, unique_request_count, duplicate_request_count = parsed

        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": (
                    f"Invoice CSV parsed: {len(entries)} lines, "
                    f"{unique_request_count} unique requests, total "
                    f"{self._decimal_text(total_amount)} {currency_text}."
                ),
            }

        record_id = f"billing-invoice-{uuid.uuid4().hex[:12]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "record_id": record_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "invoice_id": invoice_text,
            "provider": provider_text,
            "currency": currency_text,
            "billing_period_start": period_start.isoformat(),
            "billing_period_end": period_end.isoformat(),
            "line_count": len(entries),
            "unique_request_count": unique_request_count,
            "duplicate_request_count": duplicate_request_count,
            "total_amount": self._decimal_text(total_amount),
            "source_csv_sha256": self._sha256(path),
            "entries": entries,
            "owner": owner_text,
            "notes": notes_text,
            "human_reviewed": True,
            "raw_invoice_embedded": False,
            "request_identifiers_hashed": True,
        }
        payload.update(self._safety_contract())
        payload["invoice_sha256"] = self._payload_digest(payload)
        invoice_path = self.invoices_dir / f"{record_id}.json"
        self._write_json(invoice_path, payload)
        return self._invoice_source(invoice_path, payload)

    def verify_invoice(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing invoice record is unreadable."
        expected = str(payload.pop("invoice_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing invoice record SHA-256 changed."
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            return False, "Billing invoice record schema is unsupported."
        if payload.get("human_reviewed") is not True:
            return False, "Billing invoice record is not human reviewed."
        if payload.get("raw_invoice_embedded") is not False:
            return False, "Billing invoice record raw-source contract changed."
        if payload.get("request_identifiers_hashed") is not True:
            return False, "Billing invoice request-identifier contract changed."
        if not self._verify_common_contract(payload):
            return False, "Billing invoice record safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Billing invoice record contains private material."
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            return False, "Billing invoice record has no normalized lines."
        if self._safe_int(payload.get("line_count"), -1) != len(entries):
            return False, "Billing invoice line count changed."
        total = Decimal("0")
        request_hashes: list[str] = []
        line_hashes: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                return False, "Billing invoice line is invalid."
            line_hash = str(entry.get("line_id_sha256") or "")
            request_hash = str(entry.get("request_id_sha256") or "")
            if not self._is_sha256(line_hash) or not self._is_sha256(request_hash):
                return False, "Billing invoice normalized identifier changed."
            if line_hash in line_hashes:
                return False, "Billing invoice contains duplicate line identifiers."
            line_hashes.add(line_hash)
            request_hashes.append(request_hash)
            amount = self._decimal(entry.get("amount"))
            if amount is None or amount < 0:
                return False, "Billing invoice amount is invalid."
            total += amount
        if self._decimal_text(total) != str(payload.get("total_amount") or ""):
            return False, "Billing invoice total changed."
        unique_requests = len(set(request_hashes))
        duplicate_requests = len(request_hashes) - unique_requests
        if unique_requests != self._safe_int(payload.get("unique_request_count"), -1):
            return False, "Billing invoice unique-request count changed."
        if duplicate_requests != self._safe_int(
            payload.get("duplicate_request_count"), -1
        ):
            return False, "Billing invoice duplicate-request count changed."
        return True, "Billing invoice record verified."

    def snapshot(
        self,
        *,
        invoice_paths: Iterable[Path] | None = None,
        replay_result_paths: Iterable[Path] | None = None,
        replay_attestation_paths: Iterable[Path] | None = None,
        replay_pack_paths: Iterable[Path] | None = None,
        replay_receipt_paths: Iterable[Path] | None = None,
    ) -> BillingReconciliationSnapshot:
        selected_invoices = tuple(
            Path(path) for path in (invoice_paths or self.default_invoice_paths())
        )
        selected_results = tuple(
            Path(path)
            for path in (replay_result_paths or self.default_replay_result_paths())
        )
        selected_attestations = tuple(
            Path(path)
            for path in (
                replay_attestation_paths or self.default_replay_attestation_paths()
            )
        )
        selected_packs = tuple(
            Path(path) for path in (replay_pack_paths or self.default_replay_pack_paths())
        )
        selected_receipts = tuple(
            Path(path)
            for path in (replay_receipt_paths or self.default_replay_receipt_paths())
        )

        invoices: list[BillingInvoiceSource] = []
        invoice_rejected = 0
        for path in selected_invoices:
            ok, _detail = self.verify_invoice(path)
            payload = self._read_json(path)
            if not ok or payload is None:
                invoice_rejected += 1
                continue
            invoices.append(self._invoice_source(path, payload))

        replay_sources, replay_rejected = self._collect_replay_sources(
            selected_results,
            selected_attestations,
            selected_packs,
            selected_receipts,
        )
        gates: list[BillingReconciliationGate] = []

        invoice_count_ok = len(selected_invoices) == 1 and len(invoices) == 1
        gates.append(
            self._gate(
                "invoice_custody",
                "Provider invoice custody",
                "pass" if invoice_count_ok else "block",
                (
                    "Exactly one verified normalized provider invoice is selected."
                    if invoice_count_ok
                    else "Select exactly one verified normalized provider invoice."
                ),
                "Import and select one reviewed provider invoice CSV.",
            )
        )

        replay_ok = bool(replay_sources) and replay_rejected == 0
        verified_replays = tuple(
            source for source in replay_sources if source.outcome_status == "verified"
        )
        if replay_ok and len(verified_replays) == len(replay_sources):
            replay_status = "pass"
            replay_detail = "All selected Phase 74 recovery replay evidence is verified."
        elif replay_sources:
            replay_status = "block"
            replay_detail = "One or more recovery replay sources are withheld or rejected."
        else:
            replay_status = "block"
            replay_detail = "No complete Phase 74 recovery replay evidence was selected."
        gates.append(
            self._gate(
                "replay_evidence",
                "Recovery replay evidence",
                replay_status,
                replay_detail,
                "Select matching verified result, attestation, audit pack and receipt files.",
            )
        )

        expected_request_count = sum(source.attempted_jobs for source in verified_replays)
        invoice_request_count = invoices[0].unique_request_count if invoices else 0
        duplicate_count = invoices[0].duplicate_request_count if invoices else 0
        invoice_total = invoices[0].total_amount if invoices else 0.0
        invoice_currency = invoices[0].currency if invoices else ""

        if invoice_count_ok and duplicate_count == 0:
            duplicate_status = "pass"
            duplicate_detail = "The normalized invoice contains no repeated request identifier."
        elif invoice_count_ok:
            duplicate_status = "warn"
            duplicate_detail = (
                f"The invoice contains {duplicate_count} repeated request identifier(s); "
                "manual charge review is required."
            )
        else:
            duplicate_status = "block"
            duplicate_detail = "Invoice duplicate-charge analysis is unavailable."
        gates.append(
            self._gate(
                "duplicate_screen",
                "Duplicate-charge screen",
                duplicate_status,
                duplicate_detail,
                "Review repeated request identifiers before approving reconciliation.",
            )
        )

        if invoice_count_ok and replay_status == "pass":
            if expected_request_count == invoice_request_count:
                count_status = "pass"
                count_detail = "Invoice and replay request counts align."
            else:
                count_status = "warn"
                count_detail = (
                    f"Replay expects {expected_request_count} request(s), while the invoice "
                    f"contains {invoice_request_count} unique request(s)."
                )
        else:
            count_status = "block"
            count_detail = "Request-count comparison is unavailable."
        gates.append(
            self._gate(
                "request_alignment",
                "Request-count alignment",
                count_status,
                count_detail,
                "Classify matched, missing and unexpected requests during reconciliation.",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            release_gate = "hold"
            recommended = "repair_billing_evidence"
            summary = "Billing reconciliation is blocked by incomplete or invalid evidence."
        elif warning_count:
            status = "ready_with_warnings"
            release_gate = "manual_review"
            recommended = "review_billing_variance"
            summary = "Billing reconciliation can proceed with explicit manual review."
        else:
            status = "ready"
            release_gate = "allow"
            recommended = "approve_billing_reconciliation"
            summary = "Billing reconciliation evidence is ready for reviewed comparison."

        return BillingReconciliationSnapshot(
            snapshot_id=f"billing-reconciliation-snapshot-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            status=status,
            status_summary=summary,
            release_gate=release_gate,
            recommended_decision=recommended,
            selected_invoice_count=len(selected_invoices),
            verified_invoice_count=len(invoices),
            selected_replay_count=len(
                set(self._replay_id_from_path(path) for path in selected_results)
            ),
            verified_replay_count=len(verified_replays),
            rejected_source_count=invoice_rejected + replay_rejected,
            expected_request_count=expected_request_count,
            invoice_request_count=invoice_request_count,
            invoice_total_amount=round(invoice_total, 4),
            invoice_currency=invoice_currency,
            invoices=tuple(invoices),
            replay_sources=verified_replays,
            gates=tuple(gates),
        )

    def export_snapshot(self, snapshot: BillingReconciliationSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        return path

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing reconciliation snapshot is unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing reconciliation snapshot SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Billing reconciliation snapshot safety contract changed."
        if payload.get("status") not in {"ready", "ready_with_warnings", "blocked"}:
            return False, "Billing reconciliation snapshot status is invalid."
        if self._contains_private_payload(payload):
            return False, "Billing reconciliation snapshot contains private material."
        return True, "Billing reconciliation snapshot verified."

    def create_reconciliation_result(
        self,
        snapshot: BillingReconciliationSnapshot,
        *,
        invoice_path: Path,
        ledger_total_amount: float | str,
        provider_credits_amount: float | str,
        matched_request_count: int,
        missing_invoice_request_count: int,
        unexpected_invoice_request_count: int,
        duplicate_charge_count: int,
        max_variance_percent: float,
        max_duplicate_charges: int,
        max_unmatched_requests: int,
        provider_statement_verified: bool,
        owner: str,
        statement: str,
        acknowledge: bool = False,
    ) -> BillingReconciliationRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Billing reconciliation snapshot contains blockers.")
        path = Path(invoice_path)
        invoice_ok, invoice_detail = self.verify_invoice(path)
        if not invoice_ok:
            return self._blocked(invoice_detail)
        invoice_payload = self._read_json(path)
        if invoice_payload is None:
            return self._blocked("Billing invoice record is unreadable.")
        if path.resolve() not in {source.invoice_path.resolve() for source in snapshot.invoices}:
            return self._blocked("Selected invoice is not part of this snapshot.")

        ledger_total = self._decimal(ledger_total_amount)
        credits = self._decimal(provider_credits_amount)
        counts = {
            "matched_request_count": self._safe_int(matched_request_count, -1),
            "missing_invoice_request_count": self._safe_int(
                missing_invoice_request_count, -1
            ),
            "unexpected_invoice_request_count": self._safe_int(
                unexpected_invoice_request_count, -1
            ),
            "duplicate_charge_count": self._safe_int(duplicate_charge_count, -1),
            "max_duplicate_charges": self._safe_int(max_duplicate_charges, -1),
            "max_unmatched_requests": self._safe_int(max_unmatched_requests, -1),
        }
        max_variance = self._safe_float(max_variance_percent, -1.0)
        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1600)

        if ledger_total is None or credits is None:
            return self._blocked("Ledger amount or provider credit is invalid.")
        if ledger_total < 0 or credits < 0 or ledger_total > self.MAX_AMOUNT:
            return self._blocked("Billing amounts are outside the supported range.")
        invoice_total = self._decimal(invoice_payload.get("total_amount"))
        if invoice_total is None or credits > invoice_total:
            return self._blocked("Provider credits exceed the invoice total.")
        if any(value < 0 or value > self.MAX_COUNT for value in counts.values()):
            return self._blocked("Billing reconciliation counts are invalid.")
        if not 0.0 <= max_variance <= self.MAX_VARIANCE_PERCENT:
            return self._blocked("Maximum billing variance is invalid.")
        if not owner_text or not statement_text:
            return self._blocked("Reviewer and reconciliation statement are required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked("Billing reconciliation statement contains private material.")

        matched = counts["matched_request_count"]
        missing = counts["missing_invoice_request_count"]
        unexpected = counts["unexpected_invoice_request_count"]
        if matched + missing != snapshot.expected_request_count:
            return self._blocked(
                "Matched plus missing requests must equal the verified replay request count."
            )
        if matched + unexpected != snapshot.invoice_request_count:
            return self._blocked(
                "Matched plus unexpected requests must equal the invoice request count."
            )
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review billing totals, thresholds and request classifications.",
            }

        net_invoice = invoice_total - credits
        variance = net_invoice - ledger_total
        if ledger_total == 0:
            variance_percent = Decimal("0") if net_invoice == 0 else Decimal("100")
        else:
            variance_percent = (
                abs(variance) / ledger_total * Decimal("100")
            ).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)

        unmatched_total = missing + unexpected
        checks = {
            "invoice_record_verified": invoice_ok,
            "replay_evidence_verified": bool(snapshot.replay_sources),
            "request_classification_consistent": True,
            "variance_limit_met": float(variance_percent) <= max_variance,
            "duplicate_charge_limit_met": counts["duplicate_charge_count"]
            <= counts["max_duplicate_charges"],
            "unmatched_request_limit_met": unmatched_total
            <= counts["max_unmatched_requests"],
            "provider_statement_verified": bool(provider_statement_verified),
            "replay_duplicate_safety_verified": all(
                source.duplicate_api_requests == 0 and source.duplicate_outputs == 0
                for source in snapshot.replay_sources
            ),
        }
        outcome_status = "verified" if all(checks.values()) else "withheld"
        decision = (
            "approve_billing_reconciliation"
            if outcome_status == "verified"
            else "prepare_manual_billing_dispute"
        )

        snapshot_path = self.export_snapshot(snapshot)
        reconciliation_id = f"billing-reconciliation-{uuid.uuid4().hex[:12]}"
        result_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "reconciliation_id": reconciliation_id,
            "created_at": self._now_iso(),
            "outcome_status": outcome_status,
            "decision": decision,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "invoice_filename": path.name,
            "invoice_sha256": self._sha256(path),
            "provider": str(invoice_payload.get("provider") or ""),
            "invoice_id": str(invoice_payload.get("invoice_id") or ""),
            "currency": str(invoice_payload.get("currency") or ""),
            "invoice_total_amount": self._decimal_text(invoice_total),
            "provider_credits_amount": self._decimal_text(credits),
            "net_invoice_amount": self._decimal_text(net_invoice),
            "ledger_total_amount": self._decimal_text(ledger_total),
            "variance_amount": self._decimal_text(variance),
            "variance_percent": self._decimal_text(variance_percent),
            **counts,
            "max_variance_percent": round(max_variance, 4),
            "checks": checks,
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
        }
        result_payload.update(self._safety_contract())
        result_payload["result_sha256"] = self._payload_digest(result_payload)
        result_path = self.results_dir / f"{reconciliation_id}-result.json"
        self._write_json(result_path, result_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "reconciliation_id": reconciliation_id,
            "created_at": self._now_iso(),
            "status": outcome_status,
            "decision": decision,
            "result_filename": result_path.name,
            "result_sha256": self._sha256(result_path),
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "invoice_filename": path.name,
            "invoice_sha256": self._sha256(path),
            "human_decision_required": True,
        }
        attestation_payload.update(self._safety_contract())
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = (
            self.attestations_dir / f"{reconciliation_id}-attestation.json"
        )
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_dispute_pack(
            reconciliation_id=reconciliation_id,
            snapshot=snapshot,
            snapshot_path=snapshot_path,
            invoice_path=path,
            result_path=result_path,
            attestation_path=attestation_path,
        )
        return BillingReconciliationRecord(
            reconciliation_id=reconciliation_id,
            created_at=str(result_payload["created_at"]),
            outcome_status=outcome_status,
            snapshot_path=snapshot_path,
            invoice_path=path,
            result_path=result_path,
            attestation_path=attestation_path,
            dispute_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_result(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing reconciliation result is unreadable."
        expected = str(payload.pop("result_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing reconciliation result SHA-256 changed."
        if payload.get("outcome_status") not in {"verified", "withheld"}:
            return False, "Billing reconciliation outcome is invalid."
        if payload.get("human_reviewed") is not True:
            return False, "Billing reconciliation result is not human reviewed."
        if not self._verify_common_contract(payload):
            return False, "Billing reconciliation result safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Billing reconciliation result contains private material."
        return True, "Billing reconciliation result verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing reconciliation attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing reconciliation attestation SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Billing reconciliation attestation safety contract changed."
        result_path = self.results_dir / str(payload.get("result_filename") or "")
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        invoice_path = self.invoices_dir / str(payload.get("invoice_filename") or "")
        for label, source_path, expected_hash in (
            ("result", result_path, payload.get("result_sha256")),
            ("snapshot", snapshot_path, payload.get("snapshot_sha256")),
            ("invoice", invoice_path, payload.get("invoice_sha256")),
        ):
            if not source_path.is_file() or self._sha256(source_path) != expected_hash:
                return False, f"Billing reconciliation {label} evidence changed."
        result_payload = self._read_json(result_path) or {}
        if result_payload.get("reconciliation_id") != payload.get("reconciliation_id"):
            return False, "Billing reconciliation attestation identifier changed."
        return True, "Billing reconciliation attestation verified."

    def verify_dispute_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        pack = Path(pack_path)
        receipt_file = Path(receipt_path)
        receipt = self._read_json(receipt_file)
        if receipt is None or not pack.is_file():
            return False, "Billing dispute pack or receipt is missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if not expected or expected != self._payload_digest(receipt):
            return False, "Billing dispute receipt SHA-256 changed."
        if not self._verify_common_contract(receipt):
            return False, "Billing dispute receipt safety contract changed."
        if receipt.get("pack_filename") != pack.name:
            return False, "Billing dispute pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack.stat().st_size:
            return False, "Billing dispute pack size changed."
        if receipt.get("pack_sha256") != self._sha256(pack):
            return False, "Billing dispute pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack) as archive:
                names = archive.namelist()
                if not names or any(not self._safe_archive_name(name) for name in names):
                    return False, "Billing dispute pack contains an unsafe path."
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    return False, "Billing dispute manifest is invalid."
                manifest_digest = str(manifest.pop("manifest_sha256", ""))
                if manifest_digest != self._payload_digest(manifest):
                    return False, "Billing dispute manifest SHA-256 changed."
                if not self._verify_common_contract(manifest):
                    return False, "Billing dispute manifest safety contract changed."
                for entry in manifest.get("entries", []):
                    if not isinstance(entry, dict):
                        return False, "Billing dispute manifest entry is invalid."
                    name = str(entry.get("path") or "")
                    data = archive.read(name)
                    if len(data) != self._safe_int(entry.get("size_bytes"), -1):
                        return False, "Billing dispute manifest size changed."
                    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                        return False, "Billing dispute manifest entry SHA-256 changed."
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            return False, "Billing dispute pack is unreadable."
        return True, "Billing dispute pack verified."

    def _parse_invoice_csv(
        self, path: Path
    ) -> tuple[list[dict[str, object]], Decimal, int, int] | dict[str, str]:
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except (OSError, UnicodeError):
            return self._blocked("Provider invoice CSV is unreadable as UTF-8.")
        with handle:
            reader = csv.DictReader(handle)
            required = {"line_id", "request_id", "amount"}
            fieldnames = {str(name or "").strip().lower() for name in (reader.fieldnames or [])}
            if not required.issubset(fieldnames):
                return self._blocked(
                    "Invoice CSV requires line_id, request_id and amount columns."
                )
            entries: list[dict[str, object]] = []
            line_hashes: set[str] = set()
            request_hashes: list[str] = []
            total = Decimal("0")
            for row_number, raw_row in enumerate(reader, start=2):
                if len(entries) >= self.MAX_INVOICE_LINES:
                    return self._blocked("Invoice CSV exceeds the supported line limit.")
                row = {
                    str(key or "").strip().lower(): str(value or "").strip()
                    for key, value in raw_row.items()
                }
                if not any(row.values()):
                    continue
                line_id = row.get("line_id", "")
                request_id = row.get("request_id", "")
                amount = self._decimal(row.get("amount"))
                quantity = self._decimal(row.get("quantity") or "1")
                usage_type = self._clean_text(
                    row.get("usage_type", "usage"), required=False, limit=80
                )
                if not line_id or not request_id:
                    return self._blocked(f"Invoice CSV row {row_number} has a missing identifier.")
                if amount is None or quantity is None or amount < 0 or quantity < 0:
                    return self._blocked(f"Invoice CSV row {row_number} has an invalid amount.")
                if amount > self.MAX_AMOUNT or quantity > self.MAX_AMOUNT:
                    return self._blocked(f"Invoice CSV row {row_number} exceeds supported limits.")
                if self._contains_private_material(usage_type):
                    return self._blocked(f"Invoice CSV row {row_number} contains private material.")
                line_hash = hashlib.sha256(line_id.encode("utf-8")).hexdigest()
                request_hash = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
                if line_hash in line_hashes:
                    return self._blocked("Invoice CSV contains a duplicate line_id.")
                line_hashes.add(line_hash)
                request_hashes.append(request_hash)
                amount = amount.quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
                quantity = quantity.quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
                total += amount
                entries.append(
                    {
                        "line_id_sha256": line_hash,
                        "request_id_sha256": request_hash,
                        "usage_type": usage_type or "usage",
                        "quantity": self._decimal_text(quantity),
                        "amount": self._decimal_text(amount),
                    }
                )
        if not entries:
            return self._blocked("Invoice CSV contains no billing lines.")
        unique_requests = len(set(request_hashes))
        duplicate_requests = len(request_hashes) - unique_requests
        return entries, total, unique_requests, duplicate_requests

    def _collect_replay_sources(
        self,
        result_paths: tuple[Path, ...],
        attestation_paths: tuple[Path, ...],
        pack_paths: tuple[Path, ...],
        receipt_paths: tuple[Path, ...],
    ) -> tuple[tuple[BillingReplaySource, ...], int]:
        results = self._index_json(result_paths, "replay_id")
        attestations = self._index_json(attestation_paths, "replay_id")
        receipts = self._index_json(receipt_paths, "replay_id")
        packs = {self._pack_replay_id(path): path for path in pack_paths}
        all_ids = set(results) | set(attestations) | set(receipts) | set(packs)
        sources: list[BillingReplaySource] = []
        rejected = 0
        for replay_id in sorted(all_ids):
            result_path = results.get(replay_id)
            attestation_path = attestations.get(replay_id)
            pack_path = packs.get(replay_id)
            receipt_path = receipts.get(replay_id)
            if not all((result_path, attestation_path, pack_path, receipt_path)):
                rejected += 1
                continue
            assert result_path is not None
            assert attestation_path is not None
            assert pack_path is not None
            assert receipt_path is not None
            checks = (
                self.recovery_replay_service.verify_result(result_path)[0],
                self.recovery_replay_service.verify_attestation(attestation_path)[0],
                self.recovery_replay_service.verify_audit_pack(
                    pack_path, receipt_path
                )[0],
            )
            result_payload = self._read_json(result_path) or {}
            attestation_payload = self._read_json(attestation_path) or {}
            if not all(checks) or attestation_payload.get("replay_id") != replay_id:
                rejected += 1
                continue
            sources.append(
                BillingReplaySource(
                    replay_id=replay_id,
                    outcome_status=str(result_payload.get("outcome_status") or ""),
                    attempted_jobs=self._safe_int(result_payload.get("attempted_jobs")),
                    completed_jobs=self._safe_int(result_payload.get("completed_jobs")),
                    duplicate_api_requests=self._safe_int(
                        result_payload.get("duplicate_api_requests")
                    ),
                    duplicate_outputs=self._safe_int(
                        result_payload.get("duplicate_outputs")
                    ),
                    result_path=result_path,
                    attestation_path=attestation_path,
                    audit_pack_path=pack_path,
                    receipt_path=receipt_path,
                    result_sha256=self._sha256(result_path),
                    attestation_sha256=self._sha256(attestation_path),
                    audit_pack_sha256=self._sha256(pack_path),
                    receipt_sha256=self._sha256(receipt_path),
                )
            )
        return tuple(sources), rejected

    def _create_dispute_pack(
        self,
        *,
        reconciliation_id: str,
        snapshot: BillingReconciliationSnapshot,
        snapshot_path: Path,
        invoice_path: Path,
        result_path: Path,
        attestation_path: Path,
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "billing/invoice-record.json": invoice_path.read_bytes(),
            "billing/snapshot.json": snapshot_path.read_bytes(),
            "billing/result.json": result_path.read_bytes(),
            "billing/attestation.json": attestation_path.read_bytes(),
        }
        for source in snapshot.replay_sources:
            entries[f"recovery-replay/{source.result_path.name}"] = (
                source.result_path.read_bytes()
            )
            entries[f"recovery-replay/{source.attestation_path.name}"] = (
                source.attestation_path.read_bytes()
            )
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
            "reconciliation_id": reconciliation_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
            "raw_provider_invoice_included": False,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        pack_path = self.dispute_packs_dir / f"{reconciliation_id}-dispute-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "reconciliation_id": reconciliation_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{reconciliation_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _invoice_source(
        self, path: Path, payload: Mapping[str, object]
    ) -> BillingInvoiceSource:
        return BillingInvoiceSource(
            invoice_id=str(payload.get("invoice_id") or ""),
            provider=str(payload.get("provider") or ""),
            currency=str(payload.get("currency") or ""),
            billing_period_start=str(payload.get("billing_period_start") or ""),
            billing_period_end=str(payload.get("billing_period_end") or ""),
            line_count=self._safe_int(payload.get("line_count")),
            unique_request_count=self._safe_int(payload.get("unique_request_count")),
            duplicate_request_count=self._safe_int(
                payload.get("duplicate_request_count")
            ),
            total_amount=self._safe_float(payload.get("total_amount")),
            invoice_path=path,
            invoice_sha256=self._sha256(path),
        )

    def _gate(
        self,
        code: str,
        label: str,
        status: str,
        detail: str,
        remediation: str,
    ) -> BillingReconciliationGate:
        severity = "info" if status == "pass" else ("warning" if status == "warn" else "blocker")
        return BillingReconciliationGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    def _safety_contract(self) -> dict[str, bool]:
        return {
            "automatic_refund": False,
            "automatic_dispute_submission": False,
            "automatic_email": False,
            "automatic_upload": False,
            "automatic_provider_action": False,
            "automatic_billing_change": False,
            "automatic_queue_action": False,
            "automatic_release_decision": False,
        }

    def _verify_common_contract(self, payload: Mapping[str, object]) -> bool:
        return all(payload.get(key) is value for key, value in self._safety_contract().items())

    def _contains_private_payload(self, payload: Mapping[str, object]) -> bool:
        safe_identifier_keys = {
            "line_id_sha256",
            "request_id_sha256",
            "source_csv_sha256",
            "invoice_sha256",
            "snapshot_sha256",
            "result_sha256",
            "attestation_sha256",
            "pack_sha256",
            "receipt_sha256",
            "manifest_sha256",
        }

        def visit(value: object, key: str = "") -> bool:
            if isinstance(value, Mapping):
                return any(visit(item, str(item_key)) for item_key, item in value.items())
            if isinstance(value, list):
                return any(visit(item, key) for item in value)
            if isinstance(value, str):
                if key in safe_identifier_keys or key.endswith("_filename"):
                    return False
                return self._contains_private_material(value)
            return False

        return visit(payload)

    def _contains_private_material(self, value: str) -> bool:
        text = str(value or "")
        return bool(self._WINDOWS_PATH_RE.search(text) or self._SECRET_RE.search(text))

    def _clean_text(self, value: object, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
        if len(text) > limit:
            text = text[:limit].rstrip()
        return text if text or not required else ""

    def _clean_currency(self, value: object) -> str:
        text = str(value or "").strip().upper()
        return text if re.fullmatch(r"[A-Z]{3}", text) else ""

    def _parse_date(self, value: object) -> date | None:
        try:
            return date.fromisoformat(str(value or "").strip())
        except ValueError:
            return None

    def _decimal(self, value: object) -> Decimal | None:
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError):
            return None
        return number if number.is_finite() else None

    def _decimal_text(self, value: Decimal) -> str:
        quantized = value.quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
        return format(quantized, "f")

    def _safe_int(self, value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    def _safe_float(self, value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default

    def _blocked(self, detail: str) -> dict[str, str]:
        return {"status": "blocked", "detail": detail}

    def _now_iso(self) -> str:
        current = self._now_provider()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat()

    def _json_bytes(self, payload: Mapping[str, object]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _payload_digest(self, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(self._json_bytes(payload)).hexdigest()

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def _write_json(self, path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _read_json(self, path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _index_json(
        self, paths: Iterable[Path], identifier_key: str
    ) -> dict[str, Path]:
        index: dict[str, Path] = {}
        duplicates: set[str] = set()
        for path in paths:
            payload = self._read_json(Path(path))
            identifier = str((payload or {}).get(identifier_key) or "")
            if not identifier:
                continue
            if identifier in index:
                duplicates.add(identifier)
            else:
                index[identifier] = Path(path)
        for identifier in duplicates:
            index.pop(identifier, None)
        return index

    def _pack_replay_id(self, path: Path) -> str:
        suffix = "-audit-pack.zip"
        name = Path(path).name
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    def _replay_id_from_path(self, path: Path) -> str:
        name = Path(path).name
        for suffix in ("-result.json", "-attestation.json", "-audit-pack.zip", "-receipt.json"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return name

    def _safe_archive_name(self, name: str) -> bool:
        pure = PurePosixPath(name)
        return bool(name) and not pure.is_absolute() and ".." not in pure.parts and "\\" not in name

    def _is_sha256(self, value: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-f]{64}", value))

    def _sorted_files(self, root: Path, pattern: str) -> tuple[Path, ...]:
        return tuple(sorted(root.glob(pattern), key=lambda path: path.name))
