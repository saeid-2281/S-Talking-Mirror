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
from app.models.provider_credit_close import (
    ProviderCreditCloseGate,
    ProviderCreditCloseRecord,
    ProviderCreditCloseSnapshot,
    ProviderCreditSettlementSource,
)
from app.services.billing_dispute_resolution_service import (
    BillingDisputeResolutionService,
)


class ProviderCreditCloseService:
    """Close verified provider credit settlements without changing financial systems.

    Phase 77 consumes verified Phase 76 settlement evidence and creates a local,
    privacy-safe accounting-period close record. It never changes a provider
    account, ledger, invoice, payment, credit memo or external accounting system.
    """

    SCHEMA_VERSION = 1
    MAX_AMOUNT = Decimal("1000000000")
    _MONEY_QUANT = Decimal("0.0001")
    _PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        billing_dispute_resolution_service: BillingDisputeResolutionService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.billing_dispute_resolution_service = billing_dispute_resolution_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "provider-credit-close"
        self.snapshots_dir = self.root / "snapshots"
        self.closes_dir = self.root / "closes"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.closes_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_settlement_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_dispute_resolution_service.settlements_dir,
            "*.json",
        )

    def default_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_dispute_resolution_service.attestations_dir,
            "*-attestation.json",
        )

    def default_closure_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_dispute_resolution_service.closure_packs_dir,
            "*-closure-pack.zip",
        )

    def default_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.billing_dispute_resolution_service.receipts_dir,
            "*-receipt.json",
        )

    def snapshot(
        self,
        *,
        accounting_period: str,
        settlement_paths: Iterable[Path] | None = None,
        attestation_paths: Iterable[Path] | None = None,
        closure_pack_paths: Iterable[Path] | None = None,
        receipt_paths: Iterable[Path] | None = None,
    ) -> ProviderCreditCloseSnapshot:
        settlements = tuple(settlement_paths or self.default_settlement_paths())
        attestations = tuple(attestation_paths or self.default_attestation_paths())
        packs = tuple(closure_pack_paths or self.default_closure_pack_paths())
        receipts = tuple(receipt_paths or self.default_receipt_paths())
        period = self._clean_text(accounting_period, required=True, limit=16)

        sources, rejected = self._collect_sources(
            settlements=settlements,
            attestations=attestations,
            packs=packs,
            receipts=receipts,
        )
        gates: list[ProviderCreditCloseGate] = []

        if not settlements:
            gates.append(
                self._gate(
                    "settlement_sources_present",
                    "Phase 76 settlement evidence",
                    "block",
                    "No Phase 76 settlement evidence was selected.",
                    "Select verified settlement, attestation, closure pack and receipt files.",
                )
            )
        elif rejected:
            gates.append(
                self._gate(
                    "settlement_sources_verified",
                    "Settlement evidence integrity",
                    "block",
                    f"{rejected} selected settlement source set(s) were rejected.",
                    "Restore the original Phase 76 settlement evidence and retry.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "settlement_sources_verified",
                    "Settlement evidence integrity",
                    "pass",
                    f"{len(sources)} settlement source set(s) verified.",
                    "",
                )
            )

        period_valid = bool(self._PERIOD_RE.fullmatch(period))
        gates.append(
            self._gate(
                "accounting_period_valid",
                "Accounting period",
                "pass" if period_valid else "block",
                (
                    f"Accounting period {period} is valid."
                    if period_valid
                    else "Accounting period must use YYYY-MM."
                ),
                "Use a calendar accounting period such as 2026-08.",
            )
        )

        settlement_ids = [source.settlement_id for source in sources]
        duplicate_ids = len(settlement_ids) != len(set(settlement_ids))
        gates.append(
            self._gate(
                "unique_settlement_ids",
                "Unique settlement identifiers",
                "block" if duplicate_ids else "pass",
                (
                    "Duplicate settlement identifiers were selected."
                    if duplicate_ids
                    else "Every selected settlement identifier is unique."
                ),
                "Select one complete evidence set per settlement identifier.",
            )
        )

        currencies = {source.currency for source in sources if source.currency}
        mixed_currency = len(currencies) > 1
        gates.append(
            self._gate(
                "single_currency_scope",
                "Single-currency close scope",
                "block" if mixed_currency else "pass",
                (
                    "Selected settlements contain multiple currencies."
                    if mixed_currency
                    else "Selected settlements use one currency."
                ),
                "Create a separate close record for each currency.",
            )
        )

        unresolved = [source for source in sources if source.outcome_status != "settled"]
        gates.append(
            self._gate(
                "all_settlements_closed",
                "All disputes fully settled",
                "block" if unresolved else "pass",
                (
                    f"{len(unresolved)} settlement(s) are not fully settled."
                    if unresolved
                    else "Every selected dispute is fully settled."
                ),
                "Resolve partial, rejected or withheld disputes before financial close.",
            )
        )

        remaining = sum(
            (Decimal(str(source.remaining_variance_amount)) for source in sources),
            Decimal("0"),
        ).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
        gates.append(
            self._gate(
                "zero_remaining_variance",
                "Remaining variance",
                "block" if remaining != 0 else "pass",
                (
                    f"Remaining verified variance is {self._money_text(remaining)}."
                    if remaining
                    else "No remaining settlement variance exists."
                ),
                "Reconcile all remaining credit variance before closing the period.",
            )
        )

        requested = sum(
            (Decimal(str(source.requested_credit_amount)) for source in sources),
            Decimal("0"),
        ).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
        approved = sum(
            (Decimal(str(source.approved_credit_amount)) for source in sources),
            Decimal("0"),
        ).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)
        applied = sum(
            (Decimal(str(source.applied_credit_amount)) for source in sources),
            Decimal("0"),
        ).quantize(self._MONEY_QUANT, rounding=ROUND_HALF_UP)

        if requested > 0 and applied < requested:
            gates.append(
                self._gate(
                    "credit_recovery_complete",
                    "Credit recovery completeness",
                    "warn" if not unresolved and remaining == 0 else "block",
                    (
                        f"Applied credits {self._money_text(applied)} are below "
                        f"requested credits {self._money_text(requested)}."
                    ),
                    "Confirm the provider decision and accounting treatment before close.",
                )
            )
        else:
            gates.append(
                self._gate(
                    "credit_recovery_complete",
                    "Credit recovery completeness",
                    "pass",
                    "Applied credits fully cover reviewed requested credits.",
                    "",
                )
            )

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        if blockers:
            status = "blocked"
            close_gate = "hold"
            recommended_decision = "repair_financial_close_evidence"
            summary = "Provider credit close is blocked by unresolved financial controls."
        elif warnings:
            status = "ready_with_warnings"
            close_gate = "manual_review"
            recommended_decision = "review_provider_credit_close"
            summary = "Provider credit close requires human review before recording."
        else:
            status = "ready"
            close_gate = "allow"
            recommended_decision = "record_provider_credit_close"
            summary = "Verified provider credit evidence is ready for period close."

        recovery_rate = (
            float((applied / requested * Decimal("100")).quantize(Decimal("0.01")))
            if requested > 0
            else 100.0
        )
        return ProviderCreditCloseSnapshot(
            snapshot_id=f"provider-credit-close-snapshot-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            accounting_period=period,
            status=status,
            status_summary=summary,
            close_gate=close_gate,
            recommended_decision=recommended_decision,
            selected_settlement_count=len(settlements),
            verified_source_count=len(sources),
            rejected_source_count=rejected,
            settled_count=sum(source.outcome_status == "settled" for source in sources),
            unresolved_count=len(unresolved),
            total_requested_credit=float(requested),
            total_approved_credit=float(approved),
            total_applied_credit=float(applied),
            total_remaining_variance=float(remaining),
            recovery_rate_percent=recovery_rate,
            currency=next(iter(currencies), ""),
            sources=tuple(sources),
            gates=tuple(gates),
        )

    def export_snapshot(self, snapshot: ProviderCreditCloseSnapshot) -> Path:
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
            return False, "Provider credit close snapshot is unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Provider credit close snapshot SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Provider credit close snapshot safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Provider credit close snapshot contains private material."
        return True, "Provider credit close snapshot verified."

    def create_close(
        self,
        snapshot: ProviderCreditCloseSnapshot,
        *,
        owner: str,
        statement: str,
        ledger_export_verified: bool,
        acknowledge: bool = False,
    ) -> ProviderCreditCloseRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Provider credit close readiness has blocking gates.")
        if snapshot.warning_count:
            return self._blocked(
                "Provider credit close has warnings and cannot be recorded as a clean close."
            )

        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1200)
        if not owner_text or not statement_text:
            return self._blocked("A human owner and close statement are required.")
        if any(
            self._contains_private_material(value)
            for value in (owner_text, statement_text, snapshot.accounting_period)
        ):
            return self._blocked("Close fields contain private or secret material.")
        if not ledger_export_verified:
            return self._blocked("Human verification of the reviewed ledger export is required.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the financial close evidence before recording it.",
            }

        snapshot_path = self.export_snapshot(snapshot)
        close_id = f"provider-credit-close-{uuid.uuid4().hex[:12]}"
        close_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "close_id": close_id,
            "created_at": self._now_iso(),
            "accounting_period": snapshot.accounting_period,
            "outcome_status": "closed",
            "decision": "record_provider_credit_close",
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "currency": snapshot.currency,
            "settlement_count": snapshot.verified_source_count,
            "total_requested_credit": self._money_text(
                Decimal(str(snapshot.total_requested_credit))
            ),
            "total_approved_credit": self._money_text(
                Decimal(str(snapshot.total_approved_credit))
            ),
            "total_applied_credit": self._money_text(
                Decimal(str(snapshot.total_applied_credit))
            ),
            "total_remaining_variance": self._money_text(
                Decimal(str(snapshot.total_remaining_variance))
            ),
            "recovery_rate_percent": round(snapshot.recovery_rate_percent, 2),
            "ledger_export_verified": True,
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
            "source_settlements": [
                {
                    "settlement_id": source.settlement_id,
                    "settlement_filename": source.settlement_path.name,
                    "settlement_sha256": source.settlement_sha256,
                    "attestation_filename": source.attestation_path.name,
                    "attestation_sha256": source.attestation_sha256,
                    "closure_pack_filename": source.closure_pack_path.name,
                    "closure_pack_sha256": source.closure_pack_sha256,
                    "receipt_filename": source.receipt_path.name,
                    "receipt_sha256": source.receipt_sha256,
                }
                for source in snapshot.sources
            ],
        }
        close_payload.update(self._safety_contract())
        close_payload["close_sha256"] = self._payload_digest(close_payload)
        close_path = self.closes_dir / f"{close_id}.json"
        self._write_json(close_path, close_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "close_id": close_id,
            "created_at": self._now_iso(),
            "accounting_period": snapshot.accounting_period,
            "status": "closed",
            "close_filename": close_path.name,
            "close_sha256": self._sha256(close_path),
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "human_decision_required": True,
        }
        attestation_payload.update(self._safety_contract())
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = self.attestations_dir / f"{close_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)

        audit_pack_path, receipt_path = self._create_audit_pack(
            close_id=close_id,
            snapshot_path=snapshot_path,
            close_path=close_path,
            attestation_path=attestation_path,
            sources=snapshot.sources,
        )
        return ProviderCreditCloseRecord(
            close_id=close_id,
            created_at=str(close_payload["created_at"]),
            accounting_period=snapshot.accounting_period,
            outcome_status="closed",
            total_applied_credit=snapshot.total_applied_credit,
            total_remaining_variance=snapshot.total_remaining_variance,
            snapshot_path=snapshot_path,
            close_path=close_path,
            attestation_path=attestation_path,
            audit_pack_path=audit_pack_path,
            receipt_path=receipt_path,
        )

    def verify_close(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Provider credit close record is unreadable."
        expected = str(payload.pop("close_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Provider credit close record SHA-256 changed."
        if payload.get("outcome_status") != "closed":
            return False, "Provider credit close status is invalid."
        if payload.get("ledger_export_verified") is not True:
            return False, "Provider credit close ledger verification is missing."
        if payload.get("human_reviewed") is not True:
            return False, "Provider credit close is not human reviewed."
        if not self._verify_common_contract(payload):
            return False, "Provider credit close safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Provider credit close contains private material."

        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != payload.get(
            "snapshot_sha256"
        ):
            return False, "Linked provider credit close snapshot changed."
        snapshot_ok, _detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return False, "Linked provider credit close snapshot is invalid."

        source_rows = payload.get("source_settlements")
        if not isinstance(source_rows, list) or not source_rows:
            return False, "Provider credit close source list is missing."
        for row in source_rows:
            if not isinstance(row, Mapping):
                return False, "Provider credit close source row is invalid."
            settlement_path = (
                self.billing_dispute_resolution_service.settlements_dir
                / str(row.get("settlement_filename") or "")
            )
            attestation_path = (
                self.billing_dispute_resolution_service.attestations_dir
                / str(row.get("attestation_filename") or "")
            )
            pack_path = (
                self.billing_dispute_resolution_service.closure_packs_dir
                / str(row.get("closure_pack_filename") or "")
            )
            receipt_path = (
                self.billing_dispute_resolution_service.receipts_dir
                / str(row.get("receipt_filename") or "")
            )
            for source_path, hash_key in (
                (settlement_path, "settlement_sha256"),
                (attestation_path, "attestation_sha256"),
                (pack_path, "closure_pack_sha256"),
                (receipt_path, "receipt_sha256"),
            ):
                if not source_path.is_file() or self._sha256(source_path) != row.get(
                    hash_key
                ):
                    return False, "Linked Phase 76 settlement evidence changed."
            settlement_ok, _detail = (
                self.billing_dispute_resolution_service.verify_settlement(
                    settlement_path
                )
            )
            attestation_ok, _detail = (
                self.billing_dispute_resolution_service.verify_attestation(
                    attestation_path
                )
            )
            pack_ok, _detail = (
                self.billing_dispute_resolution_service.verify_closure_pack(
                    pack_path, receipt_path
                )
            )
            if not all((settlement_ok, attestation_ok, pack_ok)):
                return False, "Linked Phase 76 settlement evidence is invalid."
        return True, "Provider credit close record verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Provider credit close attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Provider credit close attestation SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Provider credit close attestation safety contract changed."
        close_path = self.closes_dir / str(payload.get("close_filename") or "")
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        for source_path, expected_hash in (
            (close_path, payload.get("close_sha256")),
            (snapshot_path, payload.get("snapshot_sha256")),
        ):
            if not source_path.is_file() or self._sha256(source_path) != expected_hash:
                return False, "Linked provider credit close evidence changed."
        close_ok, _detail = self.verify_close(close_path)
        if not close_ok:
            return False, "Linked provider credit close record is invalid."
        return True, "Provider credit close attestation verified."

    def verify_audit_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        pack = Path(pack_path)
        receipt = self._read_json(receipt_path)
        if receipt is None or not pack.is_file():
            return False, "Provider credit close audit pack or receipt is missing."
        expected_receipt = str(receipt.pop("receipt_sha256", ""))
        if not expected_receipt or expected_receipt != self._payload_digest(receipt):
            return False, "Provider credit close receipt SHA-256 changed."
        if not self._verify_common_contract(receipt):
            return False, "Provider credit close receipt safety contract changed."
        if receipt.get("pack_filename") != pack.name:
            return False, "Provider credit close audit pack filename changed."
        if receipt.get("pack_sha256") != self._sha256(pack):
            return False, "Provider credit close audit pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Provider credit close audit pack has an unsafe path."
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                expected_manifest = str(manifest.pop("manifest_sha256", ""))
                if not expected_manifest or expected_manifest != self._payload_digest(
                    manifest
                ):
                    return False, "Provider credit close manifest SHA-256 changed."
                for entry in manifest.get("entries", []):
                    if not isinstance(entry, Mapping):
                        return False, "Provider credit close manifest entry is invalid."
                    name = str(entry.get("path") or "")
                    data = archive.read(name)
                    if len(data) != int(entry.get("size_bytes") or -1):
                        return False, "Provider credit close audit entry size changed."
                    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                        return False, "Provider credit close audit entry SHA-256 changed."
        except (OSError, KeyError, ValueError, TypeError, zipfile.BadZipFile):
            return False, "Provider credit close audit pack is unreadable."
        return True, "Provider credit close audit pack and receipt verified."

    def _collect_sources(
        self,
        *,
        settlements: tuple[Path, ...],
        attestations: tuple[Path, ...],
        packs: tuple[Path, ...],
        receipts: tuple[Path, ...],
    ) -> tuple[list[ProviderCreditSettlementSource], int]:
        attestation_index = self._index_json(attestations, "settlement_id")
        receipt_index = self._index_json(receipts, "settlement_id")
        pack_index = {
            self._identifier_from_pack_name(path.name): path
            for path in packs
            if self._identifier_from_pack_name(path.name)
        }
        sources: list[ProviderCreditSettlementSource] = []
        rejected = 0
        for settlement_path in settlements:
            payload = self._read_json(settlement_path)
            settlement_id = str((payload or {}).get("settlement_id") or "")
            attestation_path = attestation_index.get(settlement_id)
            pack_path = pack_index.get(settlement_id)
            receipt_path = receipt_index.get(settlement_id)
            if not payload or not all(
                (settlement_id, attestation_path, pack_path, receipt_path)
            ):
                rejected += 1
                continue

            settlement_ok, _detail = (
                self.billing_dispute_resolution_service.verify_settlement(
                    settlement_path
                )
            )
            attestation_ok, _detail = (
                self.billing_dispute_resolution_service.verify_attestation(
                    attestation_path
                )
            )
            pack_ok, _detail = (
                self.billing_dispute_resolution_service.verify_closure_pack(
                    pack_path, receipt_path
                )
            )
            if not all((settlement_ok, attestation_ok, pack_ok)):
                rejected += 1
                continue

            sources.append(
                ProviderCreditSettlementSource(
                    settlement_id=settlement_id,
                    case_id=str(payload.get("case_id") or ""),
                    outcome_status=str(payload.get("outcome_status") or ""),
                    provider=str(payload.get("provider") or ""),
                    invoice_id=str(payload.get("invoice_id") or ""),
                    currency=str(payload.get("currency") or ""),
                    requested_credit_amount=self._safe_float(
                        payload.get("requested_credit_amount")
                    ),
                    approved_credit_amount=self._safe_float(
                        payload.get("approved_credit_amount")
                    ),
                    applied_credit_amount=self._safe_float(
                        payload.get("applied_credit_amount")
                    ),
                    remaining_variance_amount=self._safe_float(
                        payload.get("remaining_variance_amount")
                    ),
                    settlement_path=settlement_path,
                    attestation_path=attestation_path,
                    closure_pack_path=pack_path,
                    receipt_path=receipt_path,
                    settlement_sha256=self._sha256(settlement_path),
                    attestation_sha256=self._sha256(attestation_path),
                    closure_pack_sha256=self._sha256(pack_path),
                    receipt_sha256=self._sha256(receipt_path),
                )
            )
        return sources, rejected

    def _create_audit_pack(
        self,
        *,
        close_id: str,
        snapshot_path: Path,
        close_path: Path,
        attestation_path: Path,
        sources: Iterable[ProviderCreditSettlementSource],
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "provider-credit-close/snapshot.json": snapshot_path.read_bytes(),
            "provider-credit-close/close.json": close_path.read_bytes(),
            "provider-credit-close/attestation.json": attestation_path.read_bytes(),
        }
        for index, source in enumerate(sources, start=1):
            prefix = f"phase76/settlement-{index:03d}"
            entries[f"{prefix}/settlement.json"] = source.settlement_path.read_bytes()
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
            "close_id": close_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)

        pack_path = self.audit_packs_dir / f"{close_id}-audit-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))

        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "close_id": close_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{close_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _gate(
        self,
        code: str,
        label: str,
        status: str,
        detail: str,
        remediation: str,
    ) -> ProviderCreditCloseGate:
        severity = "blocker" if status == "block" else "warning" if status == "warn" else "info"
        return ProviderCreditCloseGate(
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
            "automatic_provider_action": False,
            "automatic_credit_memo_action": False,
            "automatic_external_accounting_action": False,
            "automatic_evidence_upload": False,
        }

    def _verify_common_contract(self, payload: Mapping[str, object]) -> bool:
        return all(payload.get(key) is False for key in self._safety_contract())

    def _contains_private_payload(self, payload: Mapping[str, object]) -> bool:
        safe_filename_keys = {
            "snapshot_filename",
            "close_filename",
            "settlement_filename",
            "attestation_filename",
            "closure_pack_filename",
            "receipt_filename",
            "pack_filename",
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

    def _clean_text(self, value: object, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
        if required and not text:
            return ""
        return text[:limit]

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

    def _identifier_from_pack_name(self, name: str) -> str:
        suffix = "-closure-pack.zip"
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    def _sorted_files(self, directory: Path, pattern: str) -> tuple[Path, ...]:
        try:
            return tuple(sorted(directory.glob(pattern), key=lambda item: item.name.lower()))
        except OSError:
            return ()

    def _safe_archive_name(self, name: str) -> bool:
        path = PurePosixPath(name)
        return bool(
            name
            and not name.startswith(("/", "\\"))
            and ".." not in path.parts
            and "\\" not in name
        )
