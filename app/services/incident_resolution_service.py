from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.incident_resolution import (
    IncidentResolutionAction,
    IncidentResolutionEvidence,
    IncidentResolutionGate,
    IncidentResolutionRecord,
    IncidentResolutionSnapshot,
)
from app.services.incident_triage_service import IncidentTriageService


class IncidentResolutionService:
    """Create privacy-safe, tamper-evident incident closure records.

    The service never deploys a fix, applies a patch, performs a rollback,
    restarts the application, closes an external ticket, sends a customer
    notification or publishes a knowledge article. It validates existing
    Phase 64 records and explicit test evidence, then creates local records
    only after human acknowledgement.
    """

    SCHEMA_VERSION = 1
    MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
    MIN_RESOLUTION_CHARS = 20
    MAX_RESOLUTION_CHARS = 1_000
    MIN_IMPACT_CHARS = 10
    MAX_IMPACT_CHARS = 600
    EVIDENCE_KINDS = {"dedicated_regression", "full_quality_gate"}
    RESOLUTION_TYPES = {
        "code_fix",
        "configuration_change",
        "rollback",
        "workaround",
        "data_repair",
        "no_fault_found",
    }
    _SAFE_TEXT_RE = re.compile(r"^[\s\S]*$")

    def __init__(
        self,
        runtime: RuntimeConfig,
        incident_triage_service: IncidentTriageService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.incident_triage_service = incident_triage_service or IncidentTriageService(runtime)
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "incident-resolution"
        self.records_dir = self.root / "records"
        self.closures_dir = self.root / "closures"
        self.knowledge_dir = self.root / "knowledge"
        self.evidence_dir = self.root / "evidence"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.records_dir,
            self.closures_dir,
            self.knowledge_dir,
            self.evidence_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_case_path(self) -> Path:
        candidates = sorted(
            self.incident_triage_service.cases_dir.glob("triage-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else self.incident_triage_service.cases_dir / ""

    def default_plan_path(self, case_path: Path | None = None) -> Path:
        case = Path(case_path or self.default_case_path())
        if not case.name:
            return self.incident_triage_service.plans_dir / ""
        return self.incident_triage_service.plans_dir / f"{case.stem}-remediation-plan.json"

    def snapshot(
        self,
        *,
        case_path: Path,
        plan_path: Path,
        resolution_summary: str,
        customer_impact: str,
        resolution_type: str = "code_fix",
        evidence_paths: Iterable[Path] = (),
    ) -> IncidentResolutionSnapshot:
        case = Path(case_path)
        plan = Path(plan_path)
        summary = str(resolution_summary or "").strip()
        impact = str(customer_impact or "").strip()
        normalized_type = str(resolution_type or "").strip().casefold()
        resolution_id = (
            f"resolution-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        generated_at = self._now_iso()
        gates: list[IncidentResolutionGate] = []

        case_ok, case_detail = self.incident_triage_service.verify_case(case)
        plan_ok, plan_detail = self.incident_triage_service.verify_plan(plan)
        gates.append(
            self._gate(
                "triage_case",
                "Verified incident triage case",
                "pass" if case_ok else "block",
                "blocker",
                case_detail,
                "Select an untampered Phase 64 triage case.",
            )
        )
        gates.append(
            self._gate(
                "remediation_plan",
                "Verified remediation plan",
                "pass" if plan_ok else "block",
                "blocker",
                plan_detail,
                "Select the matching untampered Phase 64 remediation plan.",
            )
        )

        case_payload = self._read_json(case) if case_ok else None
        plan_payload = self._read_json(plan) if plan_ok else None
        case_id = str((case_payload or {}).get("case_id") or "")
        incident_id = str((case_payload or {}).get("incident_id") or "")
        priority = str((case_payload or {}).get("priority") or "")
        component = str((case_payload or {}).get("component") or "general")

        custody_ok = bool(
            case_ok
            and plan_ok
            and case_id
            and case_id == str((plan_payload or {}).get("case_id") or "")
            and str((case_payload or {}).get("version") or "") == self.version
            and str((case_payload or {}).get("channel") or "") == "stable"
            and str((plan_payload or {}).get("version") or "") == self.version
            and str((plan_payload or {}).get("channel") or "") == "stable"
        )
        gates.append(
            self._gate(
                "case_custody",
                "Case and plan custody",
                "pass" if custody_ok else "block",
                "blocker",
                (
                    f"Case {case_id} and its remediation plan have matching stable identity."
                    if custody_ok
                    else "The case and remediation plan do not share a verified stable identity."
                ),
                "Use the plan generated for the selected verified triage case.",
            )
        )

        open_ok = bool(case_payload and case_payload.get("status") == "open")
        gates.append(
            self._gate(
                "open_case",
                "Open incident state",
                "pass" if open_ok else "block",
                "blocker",
                (
                    "The immutable Phase 64 case remains open and eligible for closure."
                    if open_ok
                    else "The selected case is not in the expected open state."
                ),
                "Select an open verified case; do not edit the original case file.",
            )
        )

        summary_ok, summary_detail = self._validate_safe_text(
            summary,
            minimum=self.MIN_RESOLUTION_CHARS,
            maximum=self.MAX_RESOLUTION_CHARS,
            label="Resolution summary",
        )
        gates.append(
            self._gate(
                "resolution_summary",
                "Privacy-safe resolution summary",
                "pass" if summary_ok else "block",
                "blocker",
                summary_detail,
                "Describe the verified change without credentials, personal paths or private source content.",
            )
        )

        impact_ok, impact_detail = self._validate_safe_text(
            impact,
            minimum=self.MIN_IMPACT_CHARS,
            maximum=self.MAX_IMPACT_CHARS,
            label="Customer impact",
        )
        gates.append(
            self._gate(
                "customer_impact",
                "Customer-safe impact statement",
                "pass" if impact_ok else "block",
                "blocker",
                impact_detail,
                "Use a concise customer-safe impact statement without internal identifiers.",
            )
        )

        type_ok = normalized_type in self.RESOLUTION_TYPES
        gates.append(
            self._gate(
                "resolution_type",
                "Supported resolution type",
                "pass" if type_ok else "block",
                "blocker",
                (
                    f"Resolution type is {normalized_type}."
                    if type_ok
                    else "Resolution type is not supported."
                ),
                "Choose one supported human-reviewed resolution type.",
            )
        )

        evidence: list[IncidentResolutionEvidence] = []
        evidence_errors: list[str] = []
        kinds: set[str] = set()
        for raw_path in evidence_paths:
            candidate = Path(raw_path)
            item, detail = self._inspect_evidence(candidate, expected_case_id=case_id)
            if item is None:
                evidence_errors.append(detail)
                continue
            if item.kind in kinds:
                evidence_errors.append(f"Duplicate evidence kind: {item.kind}.")
                continue
            kinds.add(item.kind)
            evidence.append(item)

        missing_kinds = sorted(self.EVIDENCE_KINDS - kinds)
        evidence_ok = not evidence_errors and not missing_kinds
        if evidence_errors:
            evidence_detail = " ".join(evidence_errors)
        elif missing_kinds:
            evidence_detail = "Missing required evidence: " + ", ".join(missing_kinds) + "."
        else:
            evidence_detail = (
                "Dedicated regression and full Quality Gate evidence are integrity verified."
            )
        gates.append(
            self._gate(
                "verification_evidence",
                "Regression and Quality Gate evidence",
                "pass" if evidence_ok else "block",
                "blocker",
                evidence_detail,
                "Provide one signed passed JSON record for each required evidence kind.",
            )
        )

        duplicate_count = self._verified_closure_count(case_id)
        gates.append(
            self._gate(
                "duplicate_closure",
                "Existing verified closure",
                "block" if duplicate_count else "pass",
                "blocker",
                (
                    f"Found {duplicate_count} verified closure record(s) for this case."
                    if duplicate_count
                    else "No verified closure record exists for this case."
                ),
                "Verify the existing closure instead of creating a second closure.",
            )
        )

        gates.append(
            self._gate(
                "manual_operations",
                "Human-controlled closure",
                "pass",
                "blocker",
                "Deployment, rollback, restart, ticket closure, customer notification and publication remain manual.",
                "Approve each operational or external action outside automatic execution.",
            )
        )

        actions = self._actions(component)
        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            status_summary = f"Incident closure is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_warnings"
            status_summary = f"Incident closure is ready with {warning_count} warning(s)."
        else:
            status = "ready"
            status_summary = "Resolution evidence is verified and ready for acknowledged closure."

        return IncidentResolutionSnapshot(
            resolution_id=resolution_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            case_id=case_id,
            incident_id=incident_id,
            case_path=case,
            plan_path=plan,
            priority=priority,
            component=component,
            resolution_type=normalized_type,
            resolution_summary=summary,
            customer_impact=impact,
            status=status,
            status_summary=status_summary,
            closure_allowed=blocker_count == 0,
            duplicate_count=duplicate_count,
            evidence=tuple(evidence),
            gates=tuple(gates),
            actions=tuple(actions),
        )

    def create_closure(
        self,
        snapshot: IncidentResolutionSnapshot,
        *,
        acknowledge: bool = False,
    ) -> IncidentResolutionRecord | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review and acknowledge every closure gate before creating local records.",
                "path": "",
            }

        case_ok, case_detail = self.incident_triage_service.verify_case(snapshot.case_path)
        if not case_ok:
            return {"status": "blocked", "detail": case_detail, "path": ""}
        plan_ok, plan_detail = self.incident_triage_service.verify_plan(snapshot.plan_path)
        if not plan_ok:
            return {"status": "blocked", "detail": plan_detail, "path": ""}
        if self._verified_closure_count(snapshot.case_id):
            return {
                "status": "blocked",
                "detail": "A verified closure already exists for this case.",
                "path": "",
            }

        evidence_target = self.evidence_dir / snapshot.resolution_id
        if evidence_target.exists():
            shutil.rmtree(evidence_target)
        evidence_target.mkdir(parents=True, exist_ok=False)
        evidence_records: list[dict[str, object]] = []
        try:
            for item in snapshot.evidence:
                inspected, detail = self._inspect_evidence(
                    item.path,
                    expected_case_id=snapshot.case_id,
                )
                if inspected is None:
                    raise ValueError(detail)
                source_payload = self._read_json(item.path)
                if not isinstance(source_payload, dict):
                    raise ValueError("Verification evidence became unreadable.")
                canonical = self._canonical_evidence(source_payload, item)
                target = evidence_target / f"{item.kind}.json"
                self._write_json(target, canonical)
                verified, verified_detail = self.verify_evidence(
                    target,
                    expected_case_id=snapshot.case_id,
                )
                if not verified:
                    raise ValueError(verified_detail)
                evidence_records.append(self._path_record(target))

            created_at = self._now_iso()
            case_record = self._path_record(snapshot.case_path)
            plan_record = self._path_record(snapshot.plan_path)
            resolution_payload: dict[str, object] = {
                "schema_version": self.SCHEMA_VERSION,
                "resolution_id": snapshot.resolution_id,
                "case_id": snapshot.case_id,
                "incident_id": snapshot.incident_id,
                "created_at": created_at,
                "version": snapshot.version,
                "channel": snapshot.channel,
                "priority": snapshot.priority,
                "component": snapshot.component,
                "resolution_type": snapshot.resolution_type,
                "resolution_summary": snapshot.resolution_summary,
                "customer_impact": snapshot.customer_impact,
                "status": "resolved",
                "case": case_record,
                "plan": plan_record,
                "evidence": evidence_records,
                "human_approval_required": True,
                "manual_review_required": True,
                "automatic_deploy": False,
                "automatic_patch": False,
                "automatic_rollback": False,
                "automatic_restart": False,
                "automatic_ticket_closure": False,
                "automatic_customer_notification": False,
                "automatic_publish": False,
                "private_data_included": False,
            }
            resolution_payload["resolution_sha256"] = self._payload_digest(
                resolution_payload
            )
            resolution_path = self.records_dir / f"{snapshot.resolution_id}.json"
            self._write_json(resolution_path, resolution_payload)

            customer_message = (
                f"Impact: {snapshot.customer_impact} "
                f"Resolution: {snapshot.resolution_summary}"
            )
            closure_payload: dict[str, object] = {
                "schema_version": self.SCHEMA_VERSION,
                "closure_id": f"closure-{uuid.uuid4().hex[:12]}",
                "resolution_id": snapshot.resolution_id,
                "case_id": snapshot.case_id,
                "incident_id": snapshot.incident_id,
                "created_at": created_at,
                "version": snapshot.version,
                "channel": snapshot.channel,
                "status": "closed",
                "priority": snapshot.priority,
                "component": snapshot.component,
                "customer_message": customer_message,
                "resolution": self._path_record(resolution_path),
                "human_closure_approval": True,
                "customer_notification_sent": False,
                "external_ticket_closed": False,
                "automatic_deploy": False,
                "automatic_patch": False,
                "automatic_rollback": False,
                "automatic_restart": False,
                "automatic_ticket_closure": False,
                "automatic_customer_notification": False,
                "automatic_publish": False,
                "private_data_included": False,
            }
            closure_payload["closure_sha256"] = self._payload_digest(closure_payload)
            closure_path = self.closures_dir / f"{snapshot.resolution_id}-closure.json"
            self._write_json(closure_path, closure_payload)

            knowledge_payload: dict[str, object] = {
                "schema_version": self.SCHEMA_VERSION,
                "knowledge_id": f"knowledge-{uuid.uuid4().hex[:12]}",
                "resolution_id": snapshot.resolution_id,
                "case_id": snapshot.case_id,
                "created_at": created_at,
                "version": snapshot.version,
                "channel": snapshot.channel,
                "component": snapshot.component,
                "resolution_type": snapshot.resolution_type,
                "resolution_summary": snapshot.resolution_summary,
                "customer_impact": snapshot.customer_impact,
                "verification_kinds": sorted(item.kind for item in snapshot.evidence),
                "closure": self._path_record(closure_path),
                "human_review_required_before_publish": True,
                "published": False,
                "automatic_publish": False,
                "automatic_customer_notification": False,
                "private_data_included": False,
            }
            knowledge_payload["knowledge_sha256"] = self._payload_digest(
                knowledge_payload
            )
            knowledge_path = self.knowledge_dir / f"{snapshot.resolution_id}-knowledge.json"
            self._write_json(knowledge_path, knowledge_payload)

            checks = (
                self.verify_resolution(resolution_path),
                self.verify_closure(closure_path),
                self.verify_knowledge(knowledge_path),
            )
            for ok, detail in checks:
                if not ok:
                    raise ValueError(detail)

            self._write_json(self.root / "latest-incident-resolution.json", resolution_payload)
            self._write_json(self.root / "latest-incident-closure.json", closure_payload)
            self._write_json(self.root / "latest-incident-knowledge.json", knowledge_payload)
            return IncidentResolutionRecord(
                resolution_id=snapshot.resolution_id,
                case_id=snapshot.case_id,
                created_at=created_at,
                resolution_path=resolution_path,
                closure_path=closure_path,
                knowledge_path=knowledge_path,
                evidence_dir=evidence_target,
                priority=snapshot.priority,
                component=snapshot.component,
                resolution_type=snapshot.resolution_type,
            )
        except (OSError, ValueError, TypeError) as exc:
            shutil.rmtree(evidence_target, ignore_errors=True)
            for path in (
                self.records_dir / f"{snapshot.resolution_id}.json",
                self.closures_dir / f"{snapshot.resolution_id}-closure.json",
                self.knowledge_dir / f"{snapshot.resolution_id}-knowledge.json",
            ):
                path.unlink(missing_ok=True)
            return {
                "status": "blocked",
                "detail": f"Incident closure records were not created: {self._safe_detail(exc)}",
                "path": "",
            }

    def verify_evidence(
        self,
        path: Path,
        *,
        expected_case_id: str = "",
    ) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Resolution evidence is unreadable."
        expected = str(payload.get("evidence_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("evidence_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Resolution evidence SHA-256 does not match."
        kind = str(payload.get("kind") or "")
        if kind not in self.EVIDENCE_KINDS:
            return False, "Resolution evidence kind is not supported."
        case_id = str(payload.get("case_id") or "")
        if expected_case_id and case_id != expected_case_id:
            return False, "Resolution evidence references a different case."
        if payload.get("status") != "passed":
            return False, "Resolution evidence is not passed."
        if self._safe_int(payload.get("tests_failed"), default=-1) != 0:
            return False, "Resolution evidence contains failed tests."
        if self._safe_int(payload.get("tests_passed"), default=0) <= 0:
            return False, "Resolution evidence contains no passed tests."
        if payload.get("private_data_included") is not False:
            return False, "Resolution evidence violates the privacy contract."
        if payload.get("manual_attestation") is not True:
            return False, "Resolution evidence is missing manual attestation."
        for name in (
            "automatic_deploy",
            "automatic_patch",
            "automatic_rollback",
            "automatic_restart",
            "automatic_publish",
        ):
            if payload.get(name) is not False:
                return False, "Resolution evidence contains an automatic operation."
        if kind == "full_quality_gate" and (
            payload.get("compileall_passed") is not True
            or payload.get("ruff_passed") is not True
        ):
            return False, "Full Quality Gate evidence is incomplete."
        return True, f"{kind} evidence is privacy-safe and integrity verified."

    def verify_resolution(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident resolution record is unreadable."
        expected = str(payload.get("resolution_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("resolution_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident resolution record SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "resolved":
            return False, "Incident resolution status is invalid."
        case_record = payload.get("case")
        plan_record = payload.get("plan")
        ok, detail = self._verify_artifact_record(
            case_record,
            self.incident_triage_service.cases_dir,
        )
        if not ok:
            return False, detail
        case_path = self.incident_triage_service.cases_dir / str(
            case_record.get("filename") or ""
        )
        ok, detail = self.incident_triage_service.verify_case(case_path)
        if not ok:
            return False, detail
        ok, detail = self._verify_artifact_record(
            plan_record,
            self.incident_triage_service.plans_dir,
        )
        if not ok:
            return False, detail
        plan_path = self.incident_triage_service.plans_dir / str(
            plan_record.get("filename") or ""
        )
        ok, detail = self.incident_triage_service.verify_plan(plan_path)
        if not ok:
            return False, detail
        evidence = payload.get("evidence")
        if not isinstance(evidence, list) or len(evidence) != 2:
            return False, "Incident resolution record is missing required evidence."
        kinds: set[str] = set()
        case_id = str(payload.get("case_id") or "")
        evidence_root = self.evidence_dir / str(payload.get("resolution_id") or "")
        for record in evidence:
            ok, detail = self._verify_artifact_record(record, evidence_root)
            if not ok:
                return False, detail
            candidate = evidence_root / str(record.get("filename") or "")
            ok, detail = self.verify_evidence(candidate, expected_case_id=case_id)
            if not ok:
                return False, detail
            evidence_payload = self._read_json(candidate) or {}
            kinds.add(str(evidence_payload.get("kind") or ""))
        if kinds != self.EVIDENCE_KINDS:
            return False, "Incident resolution evidence set is incomplete."
        return True, "Incident resolution record and verification evidence are intact."

    def verify_closure(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident closure certificate is unreadable."
        expected = str(payload.get("closure_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("closure_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident closure certificate SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "closed" or payload.get("human_closure_approval") is not True:
            return False, "Incident closure certificate is missing human closure approval."
        if payload.get("customer_notification_sent") is not False:
            return False, "Incident closure certificate incorrectly claims customer notification."
        if payload.get("external_ticket_closed") is not False:
            return False, "Incident closure certificate incorrectly claims external ticket closure."
        record = payload.get("resolution")
        ok, detail = self._verify_artifact_record(record, self.records_dir)
        if not ok:
            return False, detail
        resolution_path = self.records_dir / str(record.get("filename") or "")
        ok, detail = self.verify_resolution(resolution_path)
        if not ok:
            return False, detail
        return True, "Incident closure certificate is integrity verified and human controlled."

    def verify_knowledge(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident knowledge note is unreadable."
        expected = str(payload.get("knowledge_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("knowledge_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident knowledge note SHA-256 does not match."
        if str(payload.get("version") or "") != self.version:
            return False, "Incident knowledge note identity does not match the application."
        if str(payload.get("channel") or "") != "stable":
            return False, "Incident knowledge note channel is not stable."
        if payload.get("private_data_included") is not False:
            return False, "Incident knowledge note violates the privacy contract."
        if payload.get("published") is not False:
            return False, "Incident knowledge note incorrectly claims publication."
        if payload.get("human_review_required_before_publish") is not True:
            return False, "Incident knowledge note is missing human publication review."
        if payload.get("automatic_publish") is not False:
            return False, "Incident knowledge note enables automatic publication."
        record = payload.get("closure")
        ok, detail = self._verify_artifact_record(record, self.closures_dir)
        if not ok:
            return False, detail
        closure_path = self.closures_dir / str(record.get("filename") or "")
        ok, detail = self.verify_closure(closure_path)
        if not ok:
            return False, detail
        return True, "Incident knowledge note is privacy-safe and ready for human review."

    def export_snapshot(self, snapshot: IncidentResolutionSnapshot) -> Path:
        path = self.root / "incident-resolution-summary.json"
        payload = snapshot.to_dict()
        payload.update(
            {
                "private_data_included": False,
                "automatic_deploy": False,
                "automatic_patch": False,
                "automatic_rollback": False,
                "automatic_restart": False,
                "automatic_ticket_closure": False,
                "automatic_customer_notification": False,
                "automatic_publish": False,
            }
        )
        self._write_json(path, payload)
        return path

    def _inspect_evidence(
        self,
        path: Path,
        *,
        expected_case_id: str,
    ) -> tuple[IncidentResolutionEvidence | None, str]:
        candidate = Path(path)
        if not candidate.is_file():
            return None, f"Evidence file was not found: {candidate.name or candidate}."
        if candidate.suffix.casefold() != ".json":
            return None, f"Evidence must be JSON: {candidate.name}."
        if candidate.stat().st_size > self.MAX_EVIDENCE_BYTES:
            return None, f"Evidence exceeds the 2 MB limit: {candidate.name}."
        try:
            raw_text = candidate.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            return None, f"Evidence is unreadable: {self._safe_detail(exc)}"
        support = self.incident_triage_service.incident_support_service
        if support._contains_secret_text(raw_text) or support._contains_local_path(raw_text):
            return None, f"Evidence contains secret-like or local-path content: {candidate.name}."
        ok, detail = self.verify_evidence(candidate, expected_case_id=expected_case_id)
        if not ok:
            return None, detail
        payload = self._read_json(candidate) or {}
        return (
            IncidentResolutionEvidence(
                kind=str(payload.get("kind") or ""),
                path=candidate,
                status=str(payload.get("status") or ""),
                tests_passed=self._safe_int(payload.get("tests_passed")),
                tests_skipped=self._safe_int(payload.get("tests_skipped")),
                tests_failed=self._safe_int(payload.get("tests_failed")),
                sha256=self._sha256(candidate),
            ),
            detail,
        )

    def _canonical_evidence(
        self,
        payload: Mapping[str, object],
        item: IncidentResolutionEvidence,
    ) -> dict[str, object]:
        canonical: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "kind": item.kind,
            "case_id": str(payload.get("case_id") or ""),
            "generated_at": str(payload.get("generated_at") or ""),
            "status": "passed",
            "tests_collected": self._safe_int(payload.get("tests_collected")),
            "tests_passed": item.tests_passed,
            "tests_skipped": item.tests_skipped,
            "tests_failed": 0,
            "compileall_passed": bool(payload.get("compileall_passed")),
            "ruff_passed": bool(payload.get("ruff_passed")),
            "manual_attestation": True,
            "source_filename": item.path.name,
            "source_sha256": item.sha256,
            "automatic_deploy": False,
            "automatic_patch": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        canonical["evidence_sha256"] = self._payload_digest(canonical)
        return canonical

    def _verify_common_contract(self, payload: Mapping[str, object]) -> tuple[bool, str]:
        if str(payload.get("version") or "") != self.version:
            return False, "Incident resolution identity does not match the application."
        if str(payload.get("channel") or "") != "stable":
            return False, "Incident resolution channel is not stable."
        if payload.get("private_data_included") is not False:
            return False, "Incident resolution violates the privacy contract."
        for name in (
            "automatic_deploy",
            "automatic_rollback",
            "automatic_restart",
            "automatic_ticket_closure",
            "automatic_customer_notification",
            "automatic_publish",
        ):
            if payload.get(name) is not False:
                return False, "Incident resolution contains an automatic operation."
        return True, "Incident resolution manual-operation contract is intact."

    def _verified_closure_count(self, case_id: str) -> int:
        if not case_id:
            return 0
        count = 0
        for path in self.closures_dir.glob("*-closure.json"):
            payload = self._read_json(path)
            if not isinstance(payload, dict) or str(payload.get("case_id") or "") != case_id:
                continue
            ok, _detail = self.verify_closure(path)
            if ok:
                count += 1
        return count

    def _validate_safe_text(
        self,
        value: str,
        *,
        minimum: int,
        maximum: int,
        label: str,
    ) -> tuple[bool, str]:
        text = str(value or "").strip()
        support = self.incident_triage_service.incident_support_service
        if len(text) < minimum:
            return False, f"{label} requires at least {minimum} characters."
        if len(text) > maximum:
            return False, f"{label} exceeds the {maximum}-character limit."
        if not self._SAFE_TEXT_RE.fullmatch(text):
            return False, f"{label} contains unsupported text."
        if support._contains_secret_text(text):
            return False, f"{label} contains credential-like content."
        if support._contains_local_path(text):
            return False, f"{label} contains a local user or project path."
        return True, f"{label} is concise and privacy-safe."

    @staticmethod
    def _actions(component: str) -> tuple[IncidentResolutionAction, ...]:
        return (
            IncidentResolutionAction(1, "owner_confirmation", "Confirm the human incident owner and approved change", "incident_commander"),
            IncidentResolutionAction(2, "dedicated_regression", f"Review dedicated {component} regression evidence", "component_owner"),
            IncidentResolutionAction(3, "quality_gate", "Review the full compile, lint and test Quality Gate", "quality_owner"),
            IncidentResolutionAction(4, "operational_validation", "Confirm monitoring and rollback readiness after the change", "release_engineer"),
            IncidentResolutionAction(5, "customer_message", "Review the customer-safe impact and resolution message", "support_owner"),
            IncidentResolutionAction(6, "closure_approval", "Approve local closure and knowledge capture without automatic publication", "release_approver"),
        )

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> IncidentResolutionGate:
        return IncidentResolutionGate(code, label, status, severity, detail, remediation)

    @staticmethod
    def _path_record(path: Path) -> dict[str, object]:
        candidate = Path(path)
        return {
            "filename": candidate.name,
            "size_bytes": candidate.stat().st_size,
            "sha256": IncidentResolutionService._sha256(candidate),
        }

    @staticmethod
    def _verify_artifact_record(
        record: Any,
        directory: Path,
    ) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Incident resolution artifact record is missing."
        filename = str(record.get("filename") or "")
        if not filename or Path(filename).name != filename:
            return False, "Incident resolution artifact filename is unsafe."
        path = Path(directory) / filename
        if not path.is_file():
            return False, f"Incident resolution artifact is missing: {filename}."
        try:
            expected_size = int(record.get("size_bytes"))
        except (TypeError, ValueError):
            return False, f"Incident resolution artifact size is invalid: {filename}."
        if expected_size != path.stat().st_size:
            return False, f"Incident resolution artifact size does not match: {filename}."
        if str(record.get("sha256") or "") != IncidentResolutionService._sha256(path):
            return False, f"Incident resolution artifact SHA-256 does not match: {filename}."
        return True, f"Incident resolution artifact verified: {filename}."

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_detail(exc: BaseException) -> str:
        return re.sub(r"\s+", " ", str(exc)).strip()[:240] or type(exc).__name__

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
