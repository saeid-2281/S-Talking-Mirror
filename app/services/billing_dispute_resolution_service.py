from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.billing_dispute_resolution import (
    BillingDisputeCaseRecord,
    BillingDisputeGate,
    BillingDisputeSnapshot,
    BillingDisputeSource,
    BillingSettlementRecord,
)
from app.services.billing_reconciliation_service import BillingReconciliationService


class BillingDisputeResolutionService:
    """Create privacy-safe billing dispute cases and verify provider settlements.

    Phase 76 consumes verified Phase 75 reconciliation evidence. It records local
    dispute and settlement evidence only. It never submits a provider dispute,
    requests a refund, changes a ledger, uploads evidence or sends email.
    """

    SCHEMA_VERSION = 1
    MAX_COUNT = 1_000_000
    MAX_AMOUNT = Decimal("1000000000")
    _MONEY_QUANT = Decimal("0.0001")
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        billing_reconciliation_service: BillingReconciliationService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.billing_reconciliation_service = billing_reconciliation_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "billing-dispute-resolution"
        self.snapshots_dir = self.root / "snapshots"
        self.cases_dir = self.root / "cases"
        self.settlements_dir = self.root / "settlements"
        self.attestations_dir = self.root / "attestations"
        self.closure_packs_dir = self.root / "closure-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.cases_dir,
            self.settlements_dir,
            self.attestations_dir,
            self.closure_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_result_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.results_dir,
            "*-result.json",
        )

    def default_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.attestations_dir,
            "*-attestation.json",
        )

    def default_dispute_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.dispute_packs_dir,
            "*-dispute-pack.zip",
        )

    def default_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_reconciliation_service.receipts_dir,
            "*-receipt.json",
        )

    def snapshot(
        self,
        *,
        result_paths: Iterable[Path] | None = None,
        attestation_paths: Iterable[Path] | None = None,
        dispute_pack_paths: Iterable[Path] | None = None,
        receipt_paths: Iterable[Path] | None = None,
    ) -> BillingDisputeSnapshot:
        results = tuple(result_paths or self.default_result_paths())
        attestations = tuple(attestation_paths or self.default_attestation_paths())
        packs = tuple(dispute_pack_paths or self.default_dispute_pack_paths())
        receipts = tuple(receipt_paths or self.default_receipt_paths())

        sources, rejected = self._collect_sources(
            results=results,
            attestations=attestations,
            packs=packs,
            receipts=receipts,
        )
        gates: list[BillingDisputeGate] = []

        if not results:
            gates.append(
                self._gate(
                    "reconciliation_sources_present",
                    "Phase 75 reconciliation evidence",
                    "block",
                    "No Phase 75 billing reconciliation result was selected.",
                    "Select a verified reconciliation result and its linked evidence.",
                )
            )
        elif rejected:
            gates.append(
                self._gate(
                    "reconciliation_sources_verified",
                    "Reconciliation evidence integrity",
                    "block",
                    f"{rejected} selected reconciliation source set(s) were rejected.",
                    "Restore the original Phase 75 result, attestation, pack and receipt.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "reconciliation_sources_verified",
                    "Reconciliation evidence integrity",
                    "pass",
                    f"{len(sources)} reconciliation source set(s) verified.",
                    "",
                )
            )

        identifiers = [source.reconciliation_id for source in sources]
        duplicate_ids = len(identifiers) != len(set(identifiers))
        gates.append(
            self._gate(
                "unique_reconciliation_ids",
                "Unique reconciliation identifiers",
                "block" if duplicate_ids else "pass",
                (
                    "Duplicate reconciliation identifiers were selected."
                    if duplicate_ids
                    else "Every selected reconciliation identifier is unique."
                ),
                "Select one complete evidence set per reconciliation identifier.",
            )
        )

        currencies = {source.currency for source in sources if source.currency}
        currency_mismatch = len(currencies) > 1
        gates.append(
            self._gate(
                "single_currency_scope",
                "Single-currency review scope",
                "block" if currency_mismatch else "pass",
                (
                    "Selected reconciliation evidence contains multiple currencies."
                    if currency_mismatch
                    else "Selected reconciliation evidence uses one currency."
                ),
                "Review and settle each currency in a separate snapshot.",
            )
        )

        dispute_required = sum(source.outcome_status == "withheld" for source in sources)
        no_dispute_required = sum(source.outcome_status == "verified" for source in sources)
        if sources and not dispute_required:
            gates.append(
                self._gate(
                    "dispute_required",
                    "Manual dispute requirement",
                    "warn",
                    "All selected reconciliation results are verified; no dispute is required.",
                    "Keep the evidence as a no-dispute closure record.",
                )
            )
        elif dispute_required:
            gates.append(
                self._gate(
                    "dispute_required",
                    "Manual dispute requirement",
                    "pass",
                    f"{dispute_required} withheld reconciliation result(s) require human follow-up.",
                    "",
                )
            )

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        if blockers:
            status = "blocked"
            release_gate = "hold"
            recommended_decision = "repair_evidence"
            summary = "Billing dispute evidence is incomplete or invalid."
        elif dispute_required:
            status = "ready"
            release_gate = "manual_review"
            recommended_decision = "open_manual_provider_dispute"
            summary = "Verified reconciliation evidence is ready for a human dispute case."
        else:
            status = "ready_with_warnings" if warnings else "ready"
            release_gate = "allow"
            recommended_decision = "record_no_dispute_closure"
            summary = "No provider dispute is required for the selected evidence."

        total_claim = sum(
            abs(source.variance_amount)
            for source in sources
            if source.outcome_status == "withheld"
        )
        return BillingDisputeSnapshot(
            snapshot_id=f"billing-dispute-snapshot-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            status=status,
            status_summary=summary,
            release_gate=release_gate,
            recommended_decision=recommended_decision,
            selected_result_count=len(results),
            verified_source_count=len(sources),
            rejected_source_count=rejected,
            dispute_required_count=dispute_required,
            no_dispute_required_count=no_dispute_required,
            total_claim_amount=round(total_claim, 4),
            currency=next(iter(currencies), ""),
            sources=tuple(sources),
            gates=tuple(gates),
        )

    def export_snapshot(self, snapshot: BillingDisputeSnapshot) -> Path:
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
            return False, "Billing dispute snapshot is unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing dispute snapshot SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Billing dispute snapshot safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Billing dispute snapshot contains private material."
        return True, "Billing dispute snapshot verified."

    def create_dispute_case(
        self,
        snapshot: BillingDisputeSnapshot,
        *,
        result_path: Path,
        requested_credit_amount: float,
        owner: str,
        summary: str,
        internal_reference: str = "",
        acknowledge: bool = False,
    ) -> BillingDisputeCaseRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Billing dispute readiness has blocking gates.")
        path = Path(result_path)
        source = next((item for item in snapshot.sources if item.result_path == path), None)
        if source is None:
            return self._blocked("Selected result is not part of the verified snapshot.")
        if source.outcome_status != "withheld":
            return self._blocked("A dispute case can only be opened for a withheld reconciliation result.")

        requested = self._decimal(requested_credit_amount)
        owner_text = self._clean_text(owner, required=True, limit=160)
        summary_text = self._clean_text(summary, required=True, limit=1200)
        reference_text = self._clean_text(internal_reference, required=False, limit=160)
        if requested is None or requested <= 0 or requested > self.MAX_AMOUNT:
            return self._blocked("Requested credit amount is invalid.")
        maximum_claim = Decimal(str(abs(source.variance_amount))).quantize(
            self._MONEY_QUANT, rounding=ROUND_HALF_UP
        )
        if maximum_claim > 0 and requested > maximum_claim:
            return self._blocked("Requested credit exceeds the verified reconciliation variance.")
        if not owner_text or not summary_text:
            return self._blocked("A human owner and privacy-safe summary are required.")
        if any(
            self._contains_private_material(value)
            for value in (owner_text, summary_text, reference_text)
        ):
            return self._blocked("Dispute case fields contain private or secret material.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the local dispute case before recording it.",
            }

        snapshot_path = self.export_snapshot(snapshot)
        case_id = f"billing-dispute-case-{uuid.uuid4().hex[:12]}"
        issues = []
        if source.variance_amount:
            issues.append("invoice_ledger_variance")
        if source.duplicate_charge_count:
            issues.append("duplicate_charge")
        if source.unmatched_request_count:
            issues.append("unmatched_request")
        case_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "case_id": case_id,
            "created_at": self._now_iso(),
            "case_status": "open",
            "reconciliation_id": source.reconciliation_id,
            "source_result_filename": source.result_path.name,
            "source_result_sha256": self._sha256(source.result_path),
            "source_attestation_filename": source.attestation_path.name,
            "source_attestation_sha256": self._sha256(source.attestation_path),
            "source_dispute_pack_filename": source.dispute_pack_path.name,
            "source_dispute_pack_sha256": self._sha256(source.dispute_pack_path),
            "source_receipt_filename": source.receipt_path.name,
            "source_receipt_sha256": self._sha256(source.receipt_path),
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "provider": source.provider,
            "invoice_id": source.invoice_id,
            "currency": source.currency,
            "verified_variance_amount": self._money_text(maximum_claim),
            "requested_credit_amount": self._money_text(requested),
            "issue_codes": issues,
            "owner": owner_text,
            "summary": summary_text,
            "internal_reference": reference_text,
            "human_reviewed": True,
            "provider_submission_required": True,
        }
        case_payload.update(self._safety_contract())
        case_payload["case_sha256"] = self._payload_digest(case_payload)
        case_path = self.cases_dir / f"{case_id}.json"
        self._write_json(case_path, case_payload)
        return BillingDisputeCaseRecord(
            case_id=case_id,
            created_at=str(case_payload["created_at"]),
            case_status="open",
            requested_credit_amount=float(requested),
            snapshot_path=snapshot_path,
            case_path=case_path,
            source_result_path=source.result_path,
        )

    def verify_case(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing dispute case is unreadable."
        expected = str(payload.pop("case_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing dispute case SHA-256 changed."
        if payload.get("case_status") != "open" or payload.get("human_reviewed") is not True:
            return False, "Billing dispute case state is invalid."
        if not self._verify_common_contract(payload):
            return False, "Billing dispute case safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Billing dispute case contains private material."
        source_result = (
            self.billing_reconciliation_service.results_dir
            / str(payload.get("source_result_filename") or "")
        )
        source_attestation = (
            self.billing_reconciliation_service.attestations_dir
            / str(payload.get("source_attestation_filename") or "")
        )
        source_pack = (
            self.billing_reconciliation_service.dispute_packs_dir
            / str(payload.get("source_dispute_pack_filename") or "")
        )
        source_receipt = (
            self.billing_reconciliation_service.receipts_dir
            / str(payload.get("source_receipt_filename") or "")
        )
        for source_path, hash_key in (
            (source_result, "source_result_sha256"),
            (source_attestation, "source_attestation_sha256"),
            (source_pack, "source_dispute_pack_sha256"),
            (source_receipt, "source_receipt_sha256"),
        ):
            if not source_path.is_file() or self._sha256(source_path) != payload.get(hash_key):
                return False, "Linked Phase 75 billing evidence changed."
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != payload.get(
            "snapshot_sha256"
        ):
            return False, "Linked billing dispute snapshot changed."
        return True, "Billing dispute case verified."

    def record_settlement(
        self,
        *,
        case_path: Path,
        provider_response_reference: str,
        credit_memo_reference: str,
        approved_credit_amount: float,
        applied_credit_amount: float,
        remaining_variance_amount: float,
        owner: str,
        statement: str,
        provider_response_verified: bool,
        ledger_entry_verified: bool,
        acknowledge: bool = False,
    ) -> BillingSettlementRecord | dict[str, str]:
        path = Path(case_path)
        case_ok, detail = self.verify_case(path)
        if not case_ok:
            return self._blocked(detail)
        case_payload = self._read_json(path)
        if case_payload is None:
            return self._blocked("Billing dispute case is unreadable.")

        provider_reference = self._clean_text(
            provider_response_reference, required=True, limit=200
        )
        credit_reference = self._clean_text(
            credit_memo_reference, required=False, limit=200
        )
        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1200)
        values = {
            "requested": self._decimal(case_payload.get("requested_credit_amount")),
            "approved": self._decimal(approved_credit_amount),
            "applied": self._decimal(applied_credit_amount),
            "remaining": self._decimal(remaining_variance_amount),
        }
        if any(value is None or value < 0 or value > self.MAX_AMOUNT for value in values.values()):
            return self._blocked("Settlement amounts are invalid.")
        requested = values["requested"] or Decimal("0")
        approved = values["approved"] or Decimal("0")
        applied = values["applied"] or Decimal("0")
        remaining = values["remaining"] or Decimal("0")
        if approved > requested or applied > approved:
            return self._blocked("Applied and approved credits exceed the dispute claim.")
        if approved > 0 and not credit_reference:
            return self._blocked("A credit memo reference is required for approved credit.")
        if not provider_reference or not owner_text or not statement_text:
            return self._blocked("Provider response, owner and settlement statement are required.")
        if any(
            self._contains_private_material(value)
            for value in (
                provider_reference,
                credit_reference,
                owner_text,
                statement_text,
            )
        ):
            return self._blocked("Settlement fields contain private or secret material.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review provider response and ledger evidence before recording settlement.",
            }

        checks = {
            "case_verified": True,
            "provider_response_verified": bool(provider_response_verified),
            "ledger_entry_verified": bool(ledger_entry_verified),
            "credit_limits_respected": applied <= approved <= requested,
            "remaining_variance_consistent": remaining
            == (requested - applied).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP),
        }
        if all(checks.values()) and applied == requested and remaining == 0:
            outcome_status = "settled"
            decision = "close_billing_dispute"
        elif all(checks.values()) and (applied > 0 or approved > 0):
            outcome_status = "partially_settled"
            decision = "continue_manual_provider_follow_up"
        elif all(checks.values()) and approved == 0 and applied == 0:
            outcome_status = "rejected"
            decision = "continue_manual_provider_follow_up"
        else:
            outcome_status = "withheld"
            decision = "withhold_ledger_closure"

        settlement_id = f"billing-settlement-{uuid.uuid4().hex[:12]}"
        settlement_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "settlement_id": settlement_id,
            "case_id": str(case_payload.get("case_id") or ""),
            "created_at": self._now_iso(),
            "outcome_status": outcome_status,
            "decision": decision,
            "case_filename": path.name,
            "case_sha256": self._sha256(path),
            "reconciliation_id": str(case_payload.get("reconciliation_id") or ""),
            "provider": str(case_payload.get("provider") or ""),
            "invoice_id": str(case_payload.get("invoice_id") or ""),
            "currency": str(case_payload.get("currency") or ""),
            "requested_credit_amount": self._money_text(requested),
            "approved_credit_amount": self._money_text(approved),
            "applied_credit_amount": self._money_text(applied),
            "remaining_variance_amount": self._money_text(remaining),
            "provider_response_reference": provider_reference,
            "credit_memo_reference": credit_reference,
            "checks": checks,
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
        }
        settlement_payload.update(self._safety_contract())
        settlement_payload["settlement_sha256"] = self._payload_digest(
            settlement_payload
        )
        settlement_path = self.settlements_dir / f"{settlement_id}.json"
        self._write_json(settlement_path, settlement_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "settlement_id": settlement_id,
            "case_id": str(case_payload.get("case_id") or ""),
            "created_at": self._now_iso(),
            "status": outcome_status,
            "decision": decision,
            "settlement_filename": settlement_path.name,
            "settlement_sha256": self._sha256(settlement_path),
            "case_filename": path.name,
            "case_sha256": self._sha256(path),
            "human_decision_required": True,
        }
        attestation_payload.update(self._safety_contract())
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = self.attestations_dir / f"{settlement_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_closure_pack(
            settlement_id=settlement_id,
            case_path=path,
            settlement_path=settlement_path,
            attestation_path=attestation_path,
        )
        return BillingSettlementRecord(
            settlement_id=settlement_id,
            case_id=str(case_payload.get("case_id") or ""),
            created_at=str(settlement_payload["created_at"]),
            outcome_status=outcome_status,
            approved_credit_amount=float(approved),
            applied_credit_amount=float(applied),
            remaining_variance_amount=float(remaining),
            case_path=path,
            settlement_path=settlement_path,
            attestation_path=attestation_path,
            closure_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_settlement(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing settlement record is unreadable."
        expected = str(payload.pop("settlement_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing settlement record SHA-256 changed."
        if payload.get("outcome_status") not in {
            "settled",
            "partially_settled",
            "rejected",
            "withheld",
        }:
            return False, "Billing settlement outcome is invalid."
        if payload.get("human_reviewed") is not True:
            return False, "Billing settlement is not human reviewed."
        if not self._verify_common_contract(payload):
            return False, "Billing settlement safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Billing settlement contains private material."
        case_path = self.cases_dir / str(payload.get("case_filename") or "")
        if not case_path.is_file() or self._sha256(case_path) != payload.get("case_sha256"):
            return False, "Linked billing dispute case changed."
        return True, "Billing settlement record verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Billing settlement attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Billing settlement attestation SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Billing settlement attestation safety contract changed."
        settlement_path = self.settlements_dir / str(payload.get("settlement_filename") or "")
        case_path = self.cases_dir / str(payload.get("case_filename") or "")
        for source_path, expected_hash in (
            (settlement_path, payload.get("settlement_sha256")),
            (case_path, payload.get("case_sha256")),
        ):
            if not source_path.is_file() or self._sha256(source_path) != expected_hash:
                return False, "Linked billing settlement evidence changed."
        return True, "Billing settlement attestation verified."

    def verify_closure_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        pack = Path(pack_path)
        receipt = self._read_json(receipt_path)
        if receipt is None or not pack.is_file():
            return False, "Billing closure pack or receipt is missing."
        expected_receipt = str(receipt.pop("receipt_sha256", ""))
        if not expected_receipt or expected_receipt != self._payload_digest(receipt):
            return False, "Billing closure receipt SHA-256 changed."
        if not self._verify_common_contract(receipt):
            return False, "Billing closure receipt safety contract changed."
        if receipt.get("pack_filename") != pack.name:
            return False, "Billing closure pack filename changed."
        if receipt.get("pack_sha256") != self._sha256(pack):
            return False, "Billing closure pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Billing closure pack contains an unsafe path."
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                expected_manifest = str(manifest.pop("manifest_sha256", ""))
                if expected_manifest != self._payload_digest(manifest):
                    return False, "Billing closure manifest SHA-256 changed."
                for entry in manifest.get("entries", []):
                    name = str(entry.get("path") or "")
                    data = archive.read(name)
                    if len(data) != int(entry.get("size_bytes") or -1):
                        return False, "Billing closure pack entry size changed."
                    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                        return False, "Billing closure pack entry SHA-256 changed."
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            return False, "Billing closure pack is unreadable."
        return True, "Billing closure pack and receipt verified."

    def _collect_sources(
        self,
        *,
        results: tuple[Path, ...],
        attestations: tuple[Path, ...],
        packs: tuple[Path, ...],
        receipts: tuple[Path, ...],
    ) -> tuple[list[BillingDisputeSource], int]:
        attestation_index = self._index_json(attestations, "reconciliation_id")
        receipt_index = self._index_json(receipts, "reconciliation_id")
        pack_index = {
            self._reconciliation_id_from_name(path.name, "-dispute-pack.zip"): path
            for path in packs
        }
        sources: list[BillingDisputeSource] = []
        rejected = 0
        for result_path in results:
            payload = self._read_json(result_path)
            if payload is None:
                rejected += 1
                continue
            reconciliation_id = str(payload.get("reconciliation_id") or "")
            attestation_path = attestation_index.get(reconciliation_id)
            pack_path = pack_index.get(reconciliation_id)
            receipt_path = receipt_index.get(reconciliation_id)
            if not all((reconciliation_id, attestation_path, pack_path, receipt_path)):
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
                BillingDisputeSource(
                    reconciliation_id=reconciliation_id,
                    outcome_status=str(payload.get("outcome_status") or ""),
                    decision=str(payload.get("decision") or ""),
                    provider=str(payload.get("provider") or ""),
                    invoice_id=str(payload.get("invoice_id") or ""),
                    currency=str(payload.get("currency") or ""),
                    variance_amount=self._safe_float(payload.get("variance_amount")),
                    duplicate_charge_count=self._safe_int(
                        payload.get("duplicate_charge_count")
                    ),
                    unmatched_request_count=(
                        self._safe_int(payload.get("missing_invoice_request_count"))
                        + self._safe_int(payload.get("unexpected_invoice_request_count"))
                    ),
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

    def _create_closure_pack(
        self,
        *,
        settlement_id: str,
        case_path: Path,
        settlement_path: Path,
        attestation_path: Path,
    ) -> tuple[Path, Path]:
        case_payload = self._read_json(case_path) or {}
        source_result = (
            self.billing_reconciliation_service.results_dir
            / str(case_payload.get("source_result_filename") or "")
        )
        entries: dict[str, bytes] = {
            "billing-dispute/case.json": case_path.read_bytes(),
            "billing-dispute/settlement.json": settlement_path.read_bytes(),
            "billing-dispute/attestation.json": attestation_path.read_bytes(),
        }
        if source_result.is_file():
            entries["phase75/reconciliation-result.json"] = source_result.read_bytes()
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
            "settlement_id": settlement_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        pack_path = self.closure_packs_dir / f"{settlement_id}-closure-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "settlement_id": settlement_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{settlement_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _gate(
        self,
        code: str,
        label: str,
        status: str,
        detail: str,
        remediation: str,
    ) -> BillingDisputeGate:
        severity = "info" if status == "pass" else (
            "warning" if status == "warn" else "blocker"
        )
        return BillingDisputeGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    def _safety_contract(self) -> dict[str, bool]:
        return {
            "automatic_provider_submission": False,
            "automatic_refund_request": False,
            "automatic_email": False,
            "automatic_evidence_upload": False,
            "automatic_ledger_change": False,
            "automatic_provider_action": False,
            "automatic_release_decision": False,
        }

    def _verify_common_contract(self, payload: Mapping[str, object]) -> bool:
        return all(payload.get(key) is False for key in self._safety_contract())

    def _contains_private_payload(self, payload: Mapping[str, object]) -> bool:
        def walk(value: object) -> bool:
            if isinstance(value, Mapping):
                return any(walk(key) or walk(item) for key, item in value.items())
            if isinstance(value, (list, tuple, set)):
                return any(walk(item) for item in value)
            if isinstance(value, str):
                return self._contains_private_material(value)
            return False

        safe_filename_keys = {
            "source_result_filename",
            "source_attestation_filename",
            "source_dispute_pack_filename",
            "source_receipt_filename",
            "snapshot_filename",
            "case_filename",
            "settlement_filename",
            "pack_filename",
        }
        filtered = {key: value for key, value in payload.items() if key not in safe_filename_keys}
        return walk(filtered)

    def _contains_private_material(self, value: str) -> bool:
        text = str(value or "")
        return bool(self._SECRET_RE.search(text) or self._WINDOWS_PATH_RE.search(text))

    def _clean_text(self, value: object, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
        if required and not text:
            return ""
        return text[:limit]

    def _decimal(self, value: object) -> Decimal | None:
        try:
            decimal_value = Decimal(str(value)).quantize(
                self._MONEY_QUANT, rounding=ROUND_HALF_UP
            )
        except (InvalidOperation, ValueError, TypeError):
            return None
        return decimal_value if decimal_value.is_finite() else None

    def _money_text(self, value: Decimal) -> str:
        return format(value.quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP), "f")

    def _safe_int(self, value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
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
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _read_json(self, path: Path) -> dict[str, object] | None:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _index_json(
        self, paths: Iterable[Path], identifier_key: str
    ) -> dict[str, Path]:
        result: dict[str, Path] = {}
        duplicates: set[str] = set()
        for path in paths:
            payload = self._read_json(path)
            identifier = str((payload or {}).get(identifier_key) or "")
            if not identifier:
                continue
            if identifier in result:
                duplicates.add(identifier)
            result[identifier] = path
        for identifier in duplicates:
            result.pop(identifier, None)
        return result

    def _reconciliation_id_from_name(self, name: str, suffix: str) -> str:
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    def _safe_archive_name(self, name: str) -> bool:
        path = PurePosixPath(name)
        return bool(name) and not path.is_absolute() and ".." not in path.parts

    def _sorted_files(self, root: Path, pattern: str) -> tuple[Path, ...]:
        return tuple(sorted(root.glob(pattern), key=lambda path: path.name.lower()))
