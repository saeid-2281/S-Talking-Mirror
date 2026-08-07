from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.provider_governance import (
    ProviderFinancialAuditSource,
    ProviderGovernanceGate,
    ProviderGovernanceRecord,
    ProviderGovernanceSnapshot,
    ProviderPerformanceScorecard,
)
from app.services.financial_audit_service import FinancialAuditService
from app.services.generation_reliability_service import GenerationReliabilityService


class ProviderGovernanceService:
    """Build evidence-backed provider scorecards without changing routing.

    Phase 79 combines current provider reliability aggregates with verified Phase 78
    financial-audit evidence. It produces human-reviewed governance records only;
    no provider preference, failover, routing, quota, billing or account mutation is
    performed automatically.
    """

    SCHEMA_VERSION = 1
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )
    _DECISION_RANK = {
        "restricted": 0,
        "watch": 1,
        "approved": 2,
        "preferred": 3,
    }

    def __init__(
        self,
        runtime: RuntimeConfig,
        generation_reliability_service: GenerationReliabilityService,
        financial_audit_service: FinancialAuditService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.generation_reliability_service = generation_reliability_service
        self.financial_audit_service = financial_audit_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "provider-governance"
        self.snapshots_dir = self.root / "snapshots"
        self.governance_dir = self.root / "records"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.snapshots_dir,
            self.governance_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_financial_audit_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(self.financial_audit_service.audits_dir, "*.json")

    def default_financial_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.financial_audit_service.attestations_dir, "*-attestation.json"
        )

    def default_financial_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.financial_audit_service.audit_packs_dir, "*-audit-pack.zip"
        )

    def default_financial_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.financial_audit_service.receipts_dir, "*-receipt.json"
        )

    def snapshot(
        self,
        *,
        project_id: int | None = None,
        minimum_sessions: int = 3,
        preferred_threshold: float = 90.0,
        approved_threshold: float = 80.0,
        watch_threshold: float = 65.0,
        financial_audit_paths: Iterable[Path] | None = None,
        financial_attestation_paths: Iterable[Path] | None = None,
        financial_pack_paths: Iterable[Path] | None = None,
        financial_receipt_paths: Iterable[Path] | None = None,
    ) -> ProviderGovernanceSnapshot:
        minimum_sessions = max(1, min(100000, int(minimum_sessions)))
        preferred_threshold = self._percentage(preferred_threshold)
        approved_threshold = self._percentage(approved_threshold)
        watch_threshold = self._percentage(watch_threshold)
        if not (
            0.0 <= watch_threshold <= approved_threshold <= preferred_threshold <= 100.0
        ):
            raise ValueError(
                "Provider governance thresholds must satisfy watch <= approved <= preferred."
            )

        dashboard = self.generation_reliability_service.dashboard(project_id=project_id)
        reliability_metrics = tuple(dashboard.snapshot.provider_metrics)

        audit_paths = tuple(
            financial_audit_paths
            if financial_audit_paths is not None
            else self.default_financial_audit_paths()
        )
        attestation_paths = tuple(
            financial_attestation_paths
            if financial_attestation_paths is not None
            else self.default_financial_attestation_paths()
        )
        pack_paths = tuple(
            financial_pack_paths
            if financial_pack_paths is not None
            else self.default_financial_pack_paths()
        )
        receipt_paths = tuple(
            financial_receipt_paths
            if financial_receipt_paths is not None
            else self.default_financial_receipt_paths()
        )

        financial_sources, rejected_financial, financial_findings, overlap_count = (
            self._collect_financial_sources(
                audits=audit_paths,
                attestations=attestation_paths,
                packs=pack_paths,
                receipts=receipt_paths,
            )
        )
        financial_by_provider = self._financial_by_provider(financial_findings)

        scorecards: list[ProviderPerformanceScorecard] = []
        for metric in reliability_metrics:
            provider = self._clean_provider_name(getattr(metric, "provider", "unknown"))
            finance = financial_by_provider.get(provider.casefold())
            scorecards.append(
                self._score_provider(
                    provider=provider,
                    session_count=int(getattr(metric, "session_count", 0) or 0),
                    total_jobs=int(getattr(metric, "total_jobs", 0) or 0),
                    completed_jobs=int(getattr(metric, "completed_jobs", 0) or 0),
                    failed_jobs=int(getattr(metric, "failed_jobs", 0) or 0),
                    retry_events=int(getattr(metric, "retry_events", 0) or 0),
                    job_success_rate=float(
                        getattr(metric, "job_success_rate", 0.0) or 0.0
                    ),
                    failure_rate=float(getattr(metric, "failure_rate", 0.0) or 0.0),
                    retry_rate=float(getattr(metric, "retry_rate", 0.0) or 0.0),
                    average_files_per_minute=float(
                        getattr(metric, "average_files_per_minute", 0.0) or 0.0
                    ),
                    average_health_score=float(
                        getattr(metric, "average_health_score", 0.0) or 0.0
                    ),
                    finance=finance,
                    minimum_sessions=minimum_sessions,
                    preferred_threshold=preferred_threshold,
                    approved_threshold=approved_threshold,
                    watch_threshold=watch_threshold,
                )
            )

        # Financial evidence may contain a provider not present in the current
        # reliability window. Keep it visible and conservatively restricted.
        reliability_names = {item.provider.casefold() for item in scorecards}
        for provider_key, finance in sorted(financial_by_provider.items()):
            if provider_key in reliability_names:
                continue
            provider = str(finance["provider"])
            scorecards.append(
                self._score_provider(
                    provider=provider,
                    session_count=0,
                    total_jobs=0,
                    completed_jobs=0,
                    failed_jobs=0,
                    retry_events=0,
                    job_success_rate=0.0,
                    failure_rate=0.0,
                    retry_rate=0.0,
                    average_files_per_minute=0.0,
                    average_health_score=0.0,
                    finance=finance,
                    minimum_sessions=minimum_sessions,
                    preferred_threshold=preferred_threshold,
                    approved_threshold=approved_threshold,
                    watch_threshold=watch_threshold,
                )
            )

        scorecards.sort(key=lambda item: (-item.overall_score, item.provider.casefold()))

        provider_count = len(scorecards)
        preferred_count = sum(
            item.recommended_governance == "preferred" for item in scorecards
        )
        approved_count = sum(
            item.recommended_governance == "approved" for item in scorecards
        )
        watch_count = sum(item.recommended_governance == "watch" for item in scorecards)
        restricted_count = sum(
            item.recommended_governance == "restricted" for item in scorecards
        )
        missing_financial_count = sum(
            item.evidence_status != "complete" for item in scorecards
        )

        gates: list[ProviderGovernanceGate] = []
        gates.append(
            self._gate(
                "provider_reliability",
                "Provider reliability evidence",
                "pass" if reliability_metrics else "block",
                (
                    f"{len(reliability_metrics)} provider reliability aggregate(s) available."
                    if reliability_metrics
                    else "No provider reliability aggregates are available for this scope."
                ),
                "Generate production sessions before recording provider governance.",
            )
        )

        if audit_paths and not financial_sources:
            financial_status = "block"
            financial_detail = (
                f"0 of {len(audit_paths)} selected Phase 78 financial audit(s) verified."
            )
        elif not financial_sources:
            financial_status = "warn"
            financial_detail = "No verified Phase 78 financial audit is available."
        elif rejected_financial:
            financial_status = "warn"
            financial_detail = (
                f"{len(financial_sources)} financial audit(s) verified; "
                f"{rejected_financial} rejected."
            )
        else:
            financial_status = "pass"
            financial_detail = f"{len(financial_sources)} financial audit(s) verified."
        gates.append(
            self._gate(
                "financial_integrity",
                "Financial integrity evidence",
                financial_status,
                financial_detail,
                "Verify Phase 78 audit, attestation, pack and receipt evidence.",
            )
        )

        gates.append(
            self._gate(
                "financial_overlap",
                "Financial audit overlap",
                "block" if overlap_count else "pass",
                (
                    f"{overlap_count} provider invoice(s) appear in more than one selected audit."
                    if overlap_count
                    else "No duplicated provider invoice evidence was detected."
                ),
                "Select non-overlapping Phase 78 audit evidence.",
            )
        )

        gates.append(
            self._gate(
                "provider_coverage",
                "Provider evidence coverage",
                "warn" if missing_financial_count else "pass",
                (
                    f"{missing_financial_count} provider(s) lack complete financial evidence."
                    if missing_financial_count
                    else "All scored providers have reliability and financial evidence."
                ),
                "Complete Phase 78 financial audit evidence before approving the provider.",
            )
        )

        gates.append(
            self._gate(
                "provider_risk",
                "Provider governance risk",
                "warn" if (watch_count or restricted_count) else "pass",
                (
                    f"{watch_count} provider(s) are on watch and {restricted_count} restricted."
                    if (watch_count or restricted_count)
                    else "All providers meet approved or preferred thresholds."
                ),
                "Review scorecard reasons before changing any external routing policy.",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        status = (
            "blocked"
            if blocker_count
            else "ready_with_warnings"
            if warning_count
            else "ready"
        )
        governance_gate = "hold" if blocker_count else "manual_review" if warning_count else "allow"
        recommended_decision = (
            "hold_governance"
            if blocker_count
            else "record_with_review"
            if warning_count
            else "record_governance"
        )
        status_summary = (
            f"{provider_count} provider(s): {preferred_count} preferred, "
            f"{approved_count} approved, {watch_count} watch, {restricted_count} restricted."
        )

        return ProviderGovernanceSnapshot(
            snapshot_id=f"provider-governance-snapshot-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            project_id=project_id,
            status=status,
            status_summary=status_summary,
            governance_gate=governance_gate,
            recommended_decision=recommended_decision,
            minimum_sessions=minimum_sessions,
            preferred_threshold=preferred_threshold,
            approved_threshold=approved_threshold,
            watch_threshold=watch_threshold,
            selected_financial_audit_count=len(audit_paths),
            verified_financial_audit_count=len(financial_sources),
            rejected_financial_audit_count=rejected_financial,
            provider_count=provider_count,
            preferred_count=preferred_count,
            approved_count=approved_count,
            watch_count=watch_count,
            restricted_count=restricted_count,
            financial_sources=tuple(financial_sources),
            scorecards=tuple(scorecards),
            gates=tuple(gates),
        )

    def export_snapshot(self, snapshot: ProviderGovernanceSnapshot) -> Path:
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
            return False, "Provider governance snapshot is unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Provider governance snapshot SHA-256 changed."
        if payload.get("status") not in {"ready", "ready_with_warnings", "blocked"}:
            return False, "Provider governance snapshot status is invalid."
        if not self._verify_common_contract(payload):
            return False, "Provider governance snapshot safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Provider governance snapshot contains private material."
        return True, "Provider governance snapshot verified."

    def create_governance(
        self,
        snapshot: ProviderGovernanceSnapshot,
        *,
        owner: str,
        statement: str,
        decisions: Mapping[str, str] | None = None,
        acknowledge: bool = False,
    ) -> ProviderGovernanceRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Provider governance snapshot contains blockers.")
        if not snapshot.scorecards:
            return self._blocked("No provider scorecards are available.")

        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1600)
        if not owner_text or not statement_text:
            return self._blocked("Governance owner and review statement are required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked("Governance fields contain private or secret material.")

        selected_decisions: dict[str, str] = {}
        input_decisions = {str(key).casefold(): str(value) for key, value in (decisions or {}).items()}
        for scorecard in snapshot.scorecards:
            decision = input_decisions.get(
                scorecard.provider.casefold(), scorecard.recommended_governance
            ).strip().lower()
            if decision not in self._DECISION_RANK:
                return self._blocked(
                    f"Governance decision for {scorecard.provider} is invalid."
                )
            if self._DECISION_RANK[decision] > self._DECISION_RANK[
                scorecard.recommended_governance
            ]:
                return self._blocked(
                    f"Governance decision for {scorecard.provider} is more permissive than the evidence-backed recommendation."
                )
            selected_decisions[scorecard.provider] = decision

        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review provider scorecards and governance decisions before recording the baseline.",
            }

        snapshot_path = self.export_snapshot(snapshot)
        governance_id = f"provider-governance-{uuid.uuid4().hex[:12]}"
        governance_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "governance_id": governance_id,
            "created_at": self._now_iso(),
            "project_id": snapshot.project_id,
            "outcome_status": "recorded",
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
            "routing_change_applied": False,
            "provider_decisions": [
                {
                    "provider": scorecard.provider,
                    "decision": selected_decisions[scorecard.provider],
                    "recommended_governance": scorecard.recommended_governance,
                    "overall_score": scorecard.overall_score,
                    "risk_level": scorecard.risk_level,
                    "evidence_status": scorecard.evidence_status,
                }
                for scorecard in snapshot.scorecards
            ],
            "financial_sources": [
                {
                    "audit_id": source.audit_id,
                    "audit_filename": source.audit_path.name,
                    "audit_sha256": source.audit_sha256,
                    "attestation_filename": source.attestation_path.name,
                    "attestation_sha256": source.attestation_sha256,
                    "audit_pack_filename": source.audit_pack_path.name,
                    "audit_pack_sha256": source.audit_pack_sha256,
                    "receipt_filename": source.receipt_path.name,
                    "receipt_sha256": source.receipt_sha256,
                }
                for source in snapshot.financial_sources
            ],
        }
        governance_payload.update(self._safety_contract())
        governance_payload["governance_sha256"] = self._payload_digest(governance_payload)
        governance_path = self.governance_dir / f"{governance_id}.json"
        self._write_json(governance_path, governance_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "governance_id": governance_id,
            "created_at": self._now_iso(),
            "status": "verified",
            "governance_filename": governance_path.name,
            "governance_sha256": self._sha256(governance_path),
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "provider_count": snapshot.provider_count,
            "human_decision_required": True,
            "routing_change_applied": False,
        }
        attestation_payload.update(self._safety_contract())
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = self.attestations_dir / f"{governance_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_audit_pack(
            governance_id=governance_id,
            snapshot_path=snapshot_path,
            governance_path=governance_path,
            attestation_path=attestation_path,
            financial_sources=snapshot.financial_sources,
        )
        counts = defaultdict(int)
        for decision in selected_decisions.values():
            counts[decision] += 1
        return ProviderGovernanceRecord(
            governance_id=governance_id,
            created_at=str(governance_payload["created_at"]),
            project_id=snapshot.project_id,
            provider_count=snapshot.provider_count,
            preferred_count=counts["preferred"],
            approved_count=counts["approved"],
            watch_count=counts["watch"],
            restricted_count=counts["restricted"],
            snapshot_path=snapshot_path,
            governance_path=governance_path,
            attestation_path=attestation_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_governance(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Provider governance record is unreadable."
        expected = str(payload.pop("governance_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Provider governance record SHA-256 changed."
        if payload.get("outcome_status") != "recorded":
            return False, "Provider governance outcome is invalid."
        if payload.get("human_reviewed") is not True:
            return False, "Provider governance record is not human reviewed."
        if payload.get("routing_change_applied") is not False:
            return False, "Provider governance record claims an automatic routing change."
        if not self._verify_common_contract(payload):
            return False, "Provider governance safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Provider governance record contains private material."

        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != payload.get(
            "snapshot_sha256"
        ):
            return False, "Linked provider governance snapshot changed."
        snapshot_ok, _detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return False, "Linked provider governance snapshot is invalid."
        if not self._verify_financial_links(payload):
            return False, "Linked Phase 78 financial evidence changed."
        return True, "Provider governance record verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Provider governance attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Provider governance attestation SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Provider governance attestation safety contract changed."
        if payload.get("routing_change_applied") is not False:
            return False, "Provider governance attestation safety state changed."
        governance_path = self.governance_dir / str(
            payload.get("governance_filename") or ""
        )
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        for source_path, hash_key in (
            (governance_path, "governance_sha256"),
            (snapshot_path, "snapshot_sha256"),
        ):
            if not source_path.is_file() or self._sha256(source_path) != payload.get(
                hash_key
            ):
                return False, "Linked provider governance artifact changed."
        governance_ok, _detail = self.verify_governance(governance_path)
        if not governance_ok:
            return False, "Linked provider governance record is invalid."
        return True, "Provider governance attestation verified."

    def verify_audit_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        receipt = self._read_json(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Provider governance audit pack or receipt is missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if not expected or expected != self._payload_digest(receipt):
            return False, "Provider governance receipt SHA-256 changed."
        if not self._verify_common_contract(receipt):
            return False, "Provider governance receipt safety contract changed."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Provider governance pack filename changed."
        if int(receipt.get("pack_size_bytes") or -1) != pack_path.stat().st_size:
            return False, "Provider governance pack size changed."
        if receipt.get("pack_sha256") != self._sha256(pack_path):
            return False, "Provider governance pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path, "r") as archive:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                expected_manifest = str(manifest.pop("manifest_sha256", ""))
                if not expected_manifest or expected_manifest != self._payload_digest(
                    manifest
                ):
                    return False, "Provider governance manifest SHA-256 changed."
                for entry in manifest.get("entries", []):
                    if not isinstance(entry, Mapping):
                        return False, "Provider governance manifest entry is invalid."
                    name = str(entry.get("path") or "")
                    data = archive.read(name)
                    if len(data) != int(entry.get("size_bytes") or -1):
                        return False, "Provider governance pack entry size changed."
                    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                        return False, "Provider governance pack entry SHA-256 changed."
        except (OSError, KeyError, ValueError, TypeError, zipfile.BadZipFile):
            return False, "Provider governance audit pack is unreadable."
        return True, "Provider governance audit pack and receipt verified."

    def _collect_financial_sources(
        self,
        *,
        audits: tuple[Path, ...],
        attestations: tuple[Path, ...],
        packs: tuple[Path, ...],
        receipts: tuple[Path, ...],
    ) -> tuple[
        list[ProviderFinancialAuditSource],
        int,
        list[dict[str, object]],
        int,
    ]:
        attestation_index = self._index_json(attestations, "audit_id")
        receipt_index = self._index_json(receipts, "audit_id")
        pack_index = {
            self._identifier_from_pack_name(path.name, "-audit-pack.zip"): path
            for path in packs
            if self._identifier_from_pack_name(path.name, "-audit-pack.zip")
        }
        sources: list[ProviderFinancialAuditSource] = []
        findings: list[dict[str, object]] = []
        rejected = 0
        seen_audits: set[str] = set()
        seen_invoices: set[tuple[str, str]] = set()
        overlap_count = 0

        for audit_path in audits:
            payload = self._read_json(audit_path)
            audit_id = str((payload or {}).get("audit_id") or "")
            attestation_path = attestation_index.get(audit_id)
            pack_path = pack_index.get(audit_id)
            receipt_path = receipt_index.get(audit_id)
            if not payload or not all((audit_id, attestation_path, pack_path, receipt_path)):
                rejected += 1
                continue
            if audit_id in seen_audits:
                rejected += 1
                continue
            audit_ok, _detail = self.financial_audit_service.verify_audit(audit_path)
            attestation_ok, _detail = self.financial_audit_service.verify_attestation(
                attestation_path
            )
            pack_ok, _detail = self.financial_audit_service.verify_audit_pack(
                pack_path, receipt_path
            )
            if not all((audit_ok, attestation_ok, pack_ok)):
                rejected += 1
                continue

            snapshot_path = self.financial_audit_service.snapshots_dir / str(
                payload.get("snapshot_filename") or ""
            )
            snapshot_ok, _detail = self.financial_audit_service.verify_snapshot(
                snapshot_path
            )
            snapshot_payload = self._read_json(snapshot_path)
            if not snapshot_ok or snapshot_payload is None:
                rejected += 1
                continue

            seen_audits.add(audit_id)
            source = ProviderFinancialAuditSource(
                audit_id=audit_id,
                accounting_period=str(payload.get("accounting_period") or ""),
                audit_path=audit_path,
                attestation_path=attestation_path,
                audit_pack_path=pack_path,
                receipt_path=receipt_path,
                audit_sha256=self._sha256(audit_path),
                attestation_sha256=self._sha256(attestation_path),
                audit_pack_sha256=self._sha256(pack_path),
                receipt_sha256=self._sha256(receipt_path),
            )
            sources.append(source)

            for raw in snapshot_payload.get("findings", []):
                if not isinstance(raw, Mapping):
                    continue
                provider = self._clean_provider_name(str(raw.get("provider") or "unknown"))
                invoice_id = str(raw.get("invoice_id") or "").strip()
                key = (provider.casefold(), invoice_id.casefold())
                if invoice_id and key in seen_invoices:
                    overlap_count += 1
                    continue
                if invoice_id:
                    seen_invoices.add(key)
                findings.append(dict(raw))

        return sources, rejected, findings, overlap_count

    def _financial_by_provider(
        self, findings: Iterable[Mapping[str, object]]
    ) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for finding in findings:
            provider = self._clean_provider_name(str(finding.get("provider") or "unknown"))
            key = provider.casefold()
            aggregate = result.setdefault(
                key,
                {
                    "provider": provider,
                    "invoice_count": 0,
                    "invoice_total_amount": 0.0,
                    "settlement_adjustment_amount": 0.0,
                    "final_residual_variance": 0.0,
                },
            )
            aggregate["invoice_count"] = int(aggregate["invoice_count"]) + 1
            aggregate["invoice_total_amount"] = float(
                aggregate["invoice_total_amount"]
            ) + abs(self._as_float(finding.get("invoice_total_amount")))
            aggregate["settlement_adjustment_amount"] = float(
                aggregate["settlement_adjustment_amount"]
            ) + abs(self._as_float(finding.get("settlement_credit_amount")))
            aggregate["final_residual_variance"] = float(
                aggregate["final_residual_variance"]
            ) + abs(self._as_float(finding.get("residual_variance_amount")))
        return result

    def _score_provider(
        self,
        *,
        provider: str,
        session_count: int,
        total_jobs: int,
        completed_jobs: int,
        failed_jobs: int,
        retry_events: int,
        job_success_rate: float,
        failure_rate: float,
        retry_rate: float,
        average_files_per_minute: float,
        average_health_score: float,
        finance: Mapping[str, object] | None,
        minimum_sessions: int,
        preferred_threshold: float,
        approved_threshold: float,
        watch_threshold: float,
    ) -> ProviderPerformanceScorecard:
        success = self._percentage(job_success_rate)
        failure = self._percentage(failure_rate)
        retry = self._percentage(retry_rate)
        health = self._percentage(average_health_score) if average_health_score > 0 else 50.0
        reliability_score = self._round_score(
            0.65 * success + 0.20 * (100.0 - failure) + 0.15 * (100.0 - retry)
        )

        invoice_count = int((finance or {}).get("invoice_count") or 0)
        invoice_total = float((finance or {}).get("invoice_total_amount") or 0.0)
        adjustment = float((finance or {}).get("settlement_adjustment_amount") or 0.0)
        residual = float((finance or {}).get("final_residual_variance") or 0.0)
        adjustment_rate = (
            self._round_score((adjustment / invoice_total) * 100.0)
            if invoice_total > 0
            else 0.0
        )
        billing_accuracy_score = (
            self._round_score(max(0.0, 100.0 - adjustment_rate))
            if finance is not None
            else 70.0
        )
        financial_integrity_score = 100.0 if residual <= 0.0001 else 0.0
        financial_score = min(billing_accuracy_score, financial_integrity_score)
        overall_score = self._round_score(
            0.55 * reliability_score + 0.15 * health + 0.30 * financial_score
        )

        reasons: list[str] = []
        evidence_status = "complete"
        recommendation_cap = "preferred"
        if session_count < minimum_sessions:
            reasons.append(
                f"Only {session_count} session(s) are available; minimum is {minimum_sessions}."
            )
            evidence_status = "limited_reliability"
            recommendation_cap = "watch"
        if finance is None:
            reasons.append("No verified Phase 78 financial audit covers this provider.")
            evidence_status = (
                "limited_financial"
                if evidence_status == "complete"
                else "limited_reliability_and_financial"
            )
            recommendation_cap = "watch"
        if residual > 0.0001:
            reasons.append("Final audited financial residual is non-zero.")
            recommendation_cap = "restricted"
        if adjustment_rate >= 10.0:
            reasons.append(
                f"Provider billing required {adjustment_rate:.1f}% settlement adjustment."
            )
        if failure >= 5.0:
            reasons.append(f"Failure rate is {failure:.1f}%.")
        if retry >= 10.0:
            reasons.append(f"Retry rate is {retry:.1f}%.")
        if health < 70.0:
            reasons.append(f"Average provider health score is {health:.1f}.")

        if overall_score >= preferred_threshold and success >= 99.0 and financial_score >= 95.0:
            recommendation = "preferred"
        elif overall_score >= approved_threshold:
            recommendation = "approved"
        elif overall_score >= watch_threshold:
            recommendation = "watch"
        else:
            recommendation = "restricted"

        if self._DECISION_RANK[recommendation] > self._DECISION_RANK[recommendation_cap]:
            recommendation = recommendation_cap

        if overall_score >= 90.0 and recommendation not in {"restricted", "watch"}:
            risk_level = "low"
        elif overall_score >= 75.0 and recommendation != "restricted":
            risk_level = "moderate"
        elif overall_score >= 60.0:
            risk_level = "high"
        else:
            risk_level = "critical"

        if not reasons:
            reasons.append("Provider reliability and financial integrity are within policy.")

        return ProviderPerformanceScorecard(
            provider=provider,
            session_count=max(0, session_count),
            total_jobs=max(0, total_jobs),
            completed_jobs=max(0, completed_jobs),
            failed_jobs=max(0, failed_jobs),
            retry_events=max(0, retry_events),
            job_success_rate=success,
            failure_rate=failure,
            retry_rate=retry,
            average_files_per_minute=round(max(0.0, average_files_per_minute), 2),
            average_health_score=self._round_score(health),
            invoice_count=invoice_count,
            invoice_total_amount=round(invoice_total, 4),
            settlement_adjustment_amount=round(adjustment, 4),
            final_residual_variance=round(residual, 4),
            billing_adjustment_rate=adjustment_rate,
            billing_accuracy_score=billing_accuracy_score,
            reliability_score=reliability_score,
            overall_score=overall_score,
            risk_level=risk_level,
            recommended_governance=recommendation,
            evidence_status=evidence_status,
            reasons=tuple(reasons),
        )

    def _create_audit_pack(
        self,
        *,
        governance_id: str,
        snapshot_path: Path,
        governance_path: Path,
        attestation_path: Path,
        financial_sources: tuple[ProviderFinancialAuditSource, ...],
    ) -> tuple[Path, Path]:
        pack_path = self.audit_packs_dir / f"{governance_id}-audit-pack.zip"
        entries: list[tuple[str, Path]] = [
            ("snapshot.json", snapshot_path),
            ("governance.json", governance_path),
            ("attestation.json", attestation_path),
        ]
        for source in financial_sources:
            prefix = f"phase78/{source.audit_id}"
            entries.extend(
                [
                    (f"{prefix}/audit.json", source.audit_path),
                    (f"{prefix}/attestation.json", source.attestation_path),
                ]
            )

        manifest_entries = [
            {
                "path": archive_name,
                "size_bytes": source_path.stat().st_size,
                "sha256": self._sha256(source_path),
            }
            for archive_name, source_path in entries
        ]
        manifest: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "governance_id": governance_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)

        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for archive_name, source_path in entries:
                archive.write(source_path, archive_name)
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            )

        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "governance_id": governance_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{governance_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _verify_financial_links(self, payload: Mapping[str, object]) -> bool:
        for raw in payload.get("financial_sources", []):
            if not isinstance(raw, Mapping):
                return False
            audit_path = self.financial_audit_service.audits_dir / str(
                raw.get("audit_filename") or ""
            )
            attestation_path = self.financial_audit_service.attestations_dir / str(
                raw.get("attestation_filename") or ""
            )
            pack_path = self.financial_audit_service.audit_packs_dir / str(
                raw.get("audit_pack_filename") or ""
            )
            receipt_path = self.financial_audit_service.receipts_dir / str(
                raw.get("receipt_filename") or ""
            )
            for source_path, hash_key in (
                (audit_path, "audit_sha256"),
                (attestation_path, "attestation_sha256"),
                (pack_path, "audit_pack_sha256"),
                (receipt_path, "receipt_sha256"),
            ):
                if not source_path.is_file() or self._sha256(source_path) != raw.get(
                    hash_key
                ):
                    return False
            if not self.financial_audit_service.verify_audit(audit_path)[0]:
                return False
            if not self.financial_audit_service.verify_attestation(attestation_path)[0]:
                return False
            if not self.financial_audit_service.verify_audit_pack(
                pack_path, receipt_path
            )[0]:
                return False
        return True

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "human_decision_required": True,
            "automatic_routing_change": False,
            "automatic_provider_disable": False,
            "automatic_failover": False,
            "automatic_cost_change": False,
            "external_upload": False,
        }

    @classmethod
    def _verify_common_contract(cls, payload: Mapping[str, object]) -> bool:
        contract = cls._safety_contract()
        return all(payload.get(key) == value for key, value in contract.items())

    @classmethod
    def _contains_private_material(cls, text: str) -> bool:
        return bool(cls._SECRET_RE.search(text) or cls._WINDOWS_PATH_RE.search(text))

    @classmethod
    def _contains_private_payload(cls, payload: object) -> bool:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return cls._contains_private_material(text)

    @classmethod
    def _payload_digest(cls, payload: Mapping[str, object]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _index_json(
        cls, paths: Iterable[Path], identifier_key: str
    ) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for path in paths:
            payload = cls._read_json(path)
            identifier = str((payload or {}).get(identifier_key) or "")
            if identifier and identifier not in result:
                result[identifier] = path
        return result

    @staticmethod
    def _identifier_from_pack_name(name: str, suffix: str) -> str:
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    @staticmethod
    def _sorted_files(directory: Path, pattern: str) -> tuple[Path, ...]:
        if not directory.is_dir():
            return ()
        return tuple(sorted(directory.glob(pattern), key=lambda path: path.name.casefold()))

    @classmethod
    def _gate(
        cls,
        code: str,
        label: str,
        status: str,
        detail: str,
        remediation: str,
    ) -> ProviderGovernanceGate:
        severity = "error" if status == "block" else "warning" if status == "warn" else "info"
        return ProviderGovernanceGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @classmethod
    def _blocked(cls, detail: str) -> dict[str, str]:
        return {"status": "blocked", "detail": detail}

    @classmethod
    def _clean_text(cls, value: object, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        if required and not text:
            return ""
        return text[:limit]

    @classmethod
    def _clean_provider_name(cls, value: str) -> str:
        text = cls._clean_text(value, required=False, limit=160)
        return text or "unknown"

    @staticmethod
    def _as_float(value: object) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _percentage(value: object) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        return round(max(0.0, min(100.0, number)), 2)

    @staticmethod
    def _round_score(value: float) -> float:
        return round(max(0.0, min(100.0, float(value))), 2)

    def _now_iso(self) -> str:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
