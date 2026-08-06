from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.incident_triage import (
    IncidentTriageAction,
    IncidentTriageCase,
    IncidentTriageGate,
    IncidentTriageSnapshot,
)
from app.services.incident_support_service import IncidentSupportService


class IncidentTriageService:
    """Validate support bundles and prepare human-controlled triage records.

    This service never uploads a support bundle, opens an external ticket,
    changes runtime configuration, applies a patch, performs a rollback,
    restarts the application or publishes a release. It creates local,
    privacy-safe, tamper-evident case and remediation-plan records only after
    explicit acknowledgement.
    """

    SCHEMA_VERSION = 1
    MAX_JSON_MEMBER_BYTES = 2 * 1024 * 1024
    _SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    _SLA = {
        "critical": ("P0", 15, 240),
        "high": ("P1", 60, 1_440),
        "medium": ("P2", 240, 4_320),
        "low": ("P3", 1_440, 7_200),
    }
    _COMPONENT_PATTERNS = (
        ("security", re.compile(r"(?i)\b(secret|credential|security|signature|tamper|supply[- ]chain)\b")),
        ("update", re.compile(r"(?i)\b(update|upgrade|rollback|installer|release|channel|feed)\b")),
        ("provider", re.compile(r"(?i)\b(provider|elevenlabs|openai|piper|voice account|api)\b")),
        ("queue", re.compile(r"(?i)\b(queue|job|resume|pending|scheduler|orchestration)\b")),
        ("audio", re.compile(r"(?i)\b(audio|playback|waveform|export|mp3|wav|speech)\b")),
        ("performance", re.compile(r"(?i)\b(slow|hang|freeze|memory|cpu|gpu|latency|performance)\b")),
        ("data", re.compile(r"(?i)\b(database|migration|csv|project|source|manifest|receipt)\b")),
        ("interface", re.compile(r"(?i)\b(ui|dialog|window|theme|layout|button|screen|accessibility)\b")),
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        incident_support_service: IncidentSupportService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.incident_support_service = incident_support_service or IncidentSupportService(runtime)
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "incident-triage"
        self.cases_dir = self.root / "cases"
        self.plans_dir = self.root / "plans"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self.root.mkdir(parents=True, exist_ok=True)
        self.cases_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def default_bundle_path(self) -> Path:
        candidates = sorted(
            self.incident_support_service.bundles_dir.glob("S-Talking-incident-support-*.zip"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else self.incident_support_service.bundles_dir / ""

    def default_receipt_path(self, bundle_path: Path | None = None) -> Path | None:
        bundle = Path(bundle_path or self.default_bundle_path())
        if not bundle.name:
            return None
        for path in sorted(
            self.incident_support_service.receipts_dir.glob("incident-support-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        ):
            payload = self._read_json(path)
            record = payload.get("bundle") if isinstance(payload, Mapping) else None
            if isinstance(record, Mapping) and str(record.get("filename") or "") == bundle.name:
                return path
        return None

    def snapshot(
        self,
        *,
        bundle_path: Path,
        receipt_path: Path | None = None,
    ) -> IncidentTriageSnapshot:
        bundle = Path(bundle_path)
        receipt = Path(receipt_path) if receipt_path else self.default_receipt_path(bundle)
        generated_at = self._now_iso()
        case_id = f"triage-{self._now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        gates: list[IncidentTriageGate] = []

        bundle_ok, bundle_detail = self.incident_support_service.verify_bundle(bundle)
        gates.append(
            self._gate(
                "support_bundle",
                "Support bundle integrity",
                "pass" if bundle_ok else "block",
                "blocker",
                bundle_detail,
                "Select an untampered privacy-safe support bundle created by Phase 63.",
            )
        )

        summary_payload: dict[str, Any] = {}
        manifest_payload: dict[str, Any] = {}
        crash_payload: dict[str, Any] = {}
        environment_payload: dict[str, Any] = {}
        archive_names: tuple[str, ...] = ()
        archive_detail = "Structured incident evidence could not be inspected."
        archive_ok = False
        if bundle_ok:
            try:
                (
                    summary_payload,
                    manifest_payload,
                    crash_payload,
                    environment_payload,
                    archive_names,
                ) = self._read_bundle_evidence(bundle)
                archive_ok = True
                archive_detail = "Structured incident summary, manifest and diagnostics are readable."
            except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                archive_detail = f"Structured incident evidence is invalid: {self._safe_detail(exc)}"
        gates.append(
            self._gate(
                "structured_evidence",
                "Structured incident evidence",
                "pass" if archive_ok else "block",
                "blocker",
                archive_detail,
                "Regenerate the support bundle after preserving the original evidence.",
            )
        )

        reported_severity = str(summary_payload.get("severity") or manifest_payload.get("severity") or "medium").casefold()
        if reported_severity not in self._SEVERITY_ORDER:
            reported_severity = "medium"
        incident_id = str(summary_payload.get("incident_id") or manifest_payload.get("incident_id") or "")
        summary = str(summary_payload.get("summary") or "").strip()

        identity_ok = bool(
            archive_ok
            and str(summary_payload.get("version") or "") == self.version
            and str(summary_payload.get("channel") or "") == "stable"
            and str(manifest_payload.get("version") or "") == self.version
            and str(manifest_payload.get("channel") or "") == "stable"
        )
        gates.append(
            self._gate(
                "stable_identity",
                "Stable application identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Bundle identity matches {self.version}/stable."
                    if identity_ok
                    else "Bundle version or channel does not match the running stable application."
                ),
                "Triage the bundle with the matching stable application version.",
            )
        )

        consistency_ok = bool(
            archive_ok
            and incident_id
            and incident_id == str(manifest_payload.get("incident_id") or "")
            and reported_severity == str(manifest_payload.get("severity") or "").casefold()
            and summary_payload.get("manual_review_required") is True
            and manifest_payload.get("manual_review_required") is True
            and all(
                payload.get(name) is False
                for payload in (summary_payload, manifest_payload)
                for name in ("automatic_upload", "automatic_send", "automatic_publish")
            )
            and summary_payload.get("private_data_included") is False
            and manifest_payload.get("private_data_included") is False
        )
        gates.append(
            self._gate(
                "incident_consistency",
                "Incident metadata consistency",
                "pass" if consistency_ok else "block",
                "blocker",
                (
                    f"Incident {incident_id} has consistent severity and manual-handling metadata."
                    if consistency_ok
                    else "Incident summary and manifest metadata are inconsistent or violate manual handling."
                ),
                "Regenerate the support bundle and do not edit its contents manually.",
            )
        )

        receipt_ok = False
        if receipt and receipt.is_file():
            receipt_ok, receipt_detail = self._verify_receipt_for_bundle(receipt, bundle)
            receipt_status = "pass" if receipt_ok else "block"
            receipt_severity = "blocker"
            receipt_remediation = "Restore the matching untampered receipt or leave the receipt field empty for bundle-only triage."
        else:
            receipt_detail = "No matching support receipt was supplied; bundle integrity remains independently verified."
            receipt_status = "warn"
            receipt_severity = "warning"
            receipt_remediation = "Keep the Phase 63 receipt with the bundle for a complete custody chain."
            receipt = None
        gates.append(
            self._gate(
                "support_receipt",
                "Support receipt custody",
                receipt_status,
                receipt_severity,
                receipt_detail,
                receipt_remediation,
            )
        )

        report_count = sum(name.startswith("diagnostics/crash-reports/") for name in archive_names)
        log_count = sum(name.startswith("diagnostics/logs/") for name in archive_names)
        crash_count = self._safe_int(crash_payload.get("crash_count"))
        unacknowledged_count = self._safe_int(crash_payload.get("unacknowledged_count"))
        integrity_failure_count = self._safe_int(crash_payload.get("integrity_failure_count"))
        evidence_count = report_count + log_count
        if integrity_failure_count:
            evidence_status = "block"
            evidence_detail = f"Crash snapshot reports {integrity_failure_count} integrity failure(s)."
            evidence_severity = "blocker"
        elif evidence_count:
            evidence_status = "pass"
            evidence_detail = f"Bundle contains {report_count} crash report(s) and {log_count} redacted log(s)."
            evidence_severity = "warning"
        else:
            evidence_status = "warn"
            evidence_detail = "Bundle contains no optional crash report or redacted log evidence."
            evidence_severity = "warning"
        gates.append(
            self._gate(
                "diagnostic_evidence",
                "Diagnostic evidence coverage",
                evidence_status,
                evidence_severity,
                evidence_detail,
                "Reproduce the incident once and create a fresh bundle if additional evidence is required.",
            )
        )

        component = self._classify_component(summary)
        effective_severity = self._effective_severity(
            reported_severity,
            report_count=max(report_count, crash_count),
            unacknowledged_count=unacknowledged_count,
            safe_mode=bool(environment_payload.get("safe_mode")),
            component=component,
        )
        priority, acknowledgement_target, remediation_target = self._SLA[effective_severity]
        escalation = effective_severity != reported_severity
        gates.append(
            self._gate(
                "severity_policy",
                "Severity and SLA policy",
                "warn" if escalation else "pass",
                "warning",
                (
                    f"Reported {reported_severity} was escalated to {effective_severity}/{priority} by deterministic evidence policy."
                    if escalation
                    else f"Incident maps to {effective_severity}/{priority} with a {acknowledgement_target}-minute acknowledgement target."
                ),
                "A human incident owner must confirm or override severity outside this application.",
            )
        )

        fingerprint = self._fingerprint(summary, component, self.version)
        duplicate_count = self._duplicate_count(fingerprint)
        gates.append(
            self._gate(
                "duplicate_detection",
                "Related incident detection",
                "warn" if duplicate_count else "pass",
                "warning",
                (
                    f"Found {duplicate_count} existing verified triage case(s) with the same fingerprint."
                    if duplicate_count
                    else "No existing verified triage case has the same fingerprint."
                ),
                "Review related cases before opening a separate external support ticket.",
            )
        )

        privacy_ok = bool(bundle_ok and not self.incident_support_service._contains_secret_text(summary))
        gates.append(
            self._gate(
                "privacy_contract",
                "Privacy-safe intake",
                "pass" if privacy_ok else "block",
                "blocker",
                (
                    "Only the verified redacted support bundle is referenced; private source files are not copied."
                    if privacy_ok
                    else "Incident summary contains secret-like content or the bundle privacy check failed."
                ),
                "Create a new redacted Phase 63 bundle and never add private source files manually.",
            )
        )
        gates.append(
            self._gate(
                "manual_remediation",
                "Manual remediation control",
                "pass",
                "blocker",
                "Triage creates local records only. Ticket creation, patching, rollback, restart and publication remain manual.",
                "Review and approve every external or operational action separately.",
            )
        )

        actions = self._actions(component, acknowledgement_target, remediation_target)
        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            status_summary = f"Incident triage is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_warnings"
            status_summary = f"Incident triage is ready with {warning_count} warning(s)."
        else:
            status = "ready"
            status_summary = "Incident triage evidence is verified and ready for acknowledged case creation."

        return IncidentTriageSnapshot(
            case_id=case_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            incident_id=incident_id,
            source_bundle=bundle,
            source_receipt=receipt if receipt_ok else None,
            reported_severity=reported_severity,
            effective_severity=effective_severity,
            priority=priority,
            component=component,
            status=status,
            status_summary=status_summary,
            summary=summary,
            triage_allowed=blocker_count == 0,
            duplicate_count=duplicate_count,
            report_count=report_count,
            log_count=log_count,
            acknowledgement_target_minutes=acknowledgement_target,
            remediation_target_minutes=remediation_target,
            fingerprint=fingerprint,
            gates=tuple(gates),
            actions=tuple(actions),
        )

    def create_case(
        self,
        snapshot: IncidentTriageSnapshot,
        *,
        acknowledge: bool = False,
    ) -> IncidentTriageCase | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review and acknowledge the triage gates before creating local case records.",
                "path": "",
            }

        bundle_ok, bundle_detail = self.incident_support_service.verify_bundle(snapshot.source_bundle)
        if not bundle_ok:
            return {"status": "blocked", "detail": bundle_detail, "path": ""}
        if snapshot.source_receipt:
            receipt_ok, receipt_detail = self._verify_receipt_for_bundle(
                snapshot.source_receipt, snapshot.source_bundle
            )
            if not receipt_ok:
                return {"status": "blocked", "detail": receipt_detail, "path": ""}

        created_at = self._now_iso()
        source_bundle = self._path_record(snapshot.source_bundle)
        source_receipt = (
            self._path_record(snapshot.source_receipt) if snapshot.source_receipt else None
        )
        case_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "case_id": snapshot.case_id,
            "incident_id": snapshot.incident_id,
            "created_at": created_at,
            "version": snapshot.version,
            "channel": snapshot.channel,
            "reported_severity": snapshot.reported_severity,
            "effective_severity": snapshot.effective_severity,
            "priority": snapshot.priority,
            "component": snapshot.component,
            "summary": snapshot.summary,
            "fingerprint": snapshot.fingerprint,
            "duplicate_count_at_creation": snapshot.duplicate_count,
            "report_count": snapshot.report_count,
            "log_count": snapshot.log_count,
            "acknowledgement_target_minutes": snapshot.acknowledgement_target_minutes,
            "remediation_target_minutes": snapshot.remediation_target_minutes,
            "source_bundle": source_bundle,
            "source_receipt": source_receipt,
            "status": "open",
            "human_owner_required": True,
            "manual_review_required": True,
            "automatic_ticket_creation": False,
            "automatic_patch": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        case_payload["case_sha256"] = self._payload_digest(case_payload)
        case_path = self.cases_dir / f"{snapshot.case_id}.json"
        self._write_json(case_path, case_payload)

        plan_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": f"plan-{uuid.uuid4().hex[:12]}",
            "case_id": snapshot.case_id,
            "created_at": created_at,
            "version": snapshot.version,
            "channel": snapshot.channel,
            "priority": snapshot.priority,
            "component": snapshot.component,
            "case": self._path_record(case_path),
            "actions": [action.to_dict() for action in snapshot.actions],
            "human_approval_required": True,
            "automatic_ticket_creation": False,
            "automatic_patch": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        plan_payload["plan_sha256"] = self._payload_digest(plan_payload)
        plan_path = self.plans_dir / f"{snapshot.case_id}-remediation-plan.json"
        self._write_json(plan_path, plan_payload)

        case_ok, case_detail = self.verify_case(case_path)
        plan_ok, plan_detail = self.verify_plan(plan_path)
        if not case_ok or not plan_ok:
            case_path.unlink(missing_ok=True)
            plan_path.unlink(missing_ok=True)
            return {
                "status": "blocked",
                "detail": case_detail if not case_ok else plan_detail,
                "path": "",
            }

        self._write_json(self.root / "latest-incident-triage-case.json", case_payload)
        self._write_json(self.root / "latest-incident-remediation-plan.json", plan_payload)
        return IncidentTriageCase(
            case_id=snapshot.case_id,
            incident_id=snapshot.incident_id,
            created_at=created_at,
            case_path=case_path,
            plan_path=plan_path,
            source_bundle=snapshot.source_bundle,
            priority=snapshot.priority,
            component=snapshot.component,
            effective_severity=snapshot.effective_severity,
            fingerprint=snapshot.fingerprint,
        )

    def verify_case(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident triage case is unreadable."
        expected = str(payload.get("case_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("case_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident triage case SHA-256 does not match."
        if str(payload.get("version") or "") != self.version or str(payload.get("channel") or "") != "stable":
            return False, "Incident triage case identity does not match the application."
        if payload.get("private_data_included") is not False:
            return False, "Incident triage case violates the privacy contract."
        for name in (
            "automatic_ticket_creation",
            "automatic_patch",
            "automatic_rollback",
            "automatic_restart",
            "automatic_publish",
        ):
            if payload.get(name) is not False:
                return False, "Incident triage case violates the manual-operation contract."
        if payload.get("human_owner_required") is not True or payload.get("manual_review_required") is not True:
            return False, "Incident triage case is missing human-control requirements."
        bundle = payload.get("source_bundle")
        ok, detail = self._verify_support_artifact(bundle, self.incident_support_service.bundles_dir)
        if not ok:
            return False, detail
        receipt = payload.get("source_receipt")
        if receipt is not None:
            ok, detail = self._verify_artifact_record(receipt, self.incident_support_service.receipts_dir)
            if not ok:
                return False, detail
        return True, "Incident triage case is privacy-safe and integrity verified."

    def verify_plan(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident remediation plan is unreadable."
        expected = str(payload.get("plan_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("plan_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident remediation plan SHA-256 does not match."
        if str(payload.get("version") or "") != self.version or str(payload.get("channel") or "") != "stable":
            return False, "Incident remediation plan identity does not match the application."
        if payload.get("private_data_included") is not False or payload.get("human_approval_required") is not True:
            return False, "Incident remediation plan violates the human-control contract."
        for name in (
            "automatic_ticket_creation",
            "automatic_patch",
            "automatic_rollback",
            "automatic_restart",
            "automatic_publish",
        ):
            if payload.get(name) is not False:
                return False, "Incident remediation plan contains an automatic operation."
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) < 6:
            return False, "Incident remediation plan is missing required manual actions."
        for action in actions:
            if not isinstance(action, Mapping) or action.get("automatic") is not False:
                return False, "Incident remediation plan contains an automatic action."
        case_record = payload.get("case")
        ok, detail = self._verify_artifact_record(case_record, self.cases_dir)
        if not ok:
            return False, detail
        candidate = self.cases_dir / str(case_record.get("filename") or "")
        case_ok, case_detail = self.verify_case(candidate)
        if not case_ok:
            return False, case_detail
        return True, f"Incident remediation plan verified with {len(actions)} manual action(s)."

    def export_snapshot(self, snapshot: IncidentTriageSnapshot) -> Path:
        path = self.root / "incident-triage-summary.json"
        payload = snapshot.to_dict()
        payload.update(
            {
                "private_data_included": False,
                "automatic_ticket_creation": False,
                "automatic_patch": False,
                "automatic_rollback": False,
                "automatic_restart": False,
                "automatic_publish": False,
            }
        )
        self._write_json(path, payload)
        return path

    def _read_bundle_evidence(
        self, path: Path
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], tuple[str, ...]]:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("duplicate archive member names are not allowed")
            required = (
                "incident/summary.json",
                "incident/manifest.json",
                "diagnostics/crash-recovery-snapshot.json",
                "diagnostics/environment.json",
            )
            for name in required:
                if name not in names:
                    raise KeyError(name)
            return (
                self._read_json_member(archive, required[0]),
                self._read_json_member(archive, required[1]),
                self._read_json_member(archive, required[2]),
                self._read_json_member(archive, required[3]),
                tuple(names),
            )

    def _read_json_member(self, archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
        info = archive.getinfo(name)
        if info.file_size > self.MAX_JSON_MEMBER_BYTES:
            raise ValueError(f"archive member exceeds the JSON intake limit: {name}")
        payload = json.loads(archive.read(name).decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise TypeError(f"archive member is not a JSON object: {name}")
        return payload

    def _verify_receipt_for_bundle(self, receipt_path: Path, bundle_path: Path) -> tuple[bool, str]:
        payload = self._read_json(receipt_path)
        if not isinstance(payload, dict):
            return False, "Incident support receipt is unreadable."
        expected = str(payload.get("receipt_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident support receipt SHA-256 does not match."
        record = payload.get("bundle")
        if not isinstance(record, Mapping):
            return False, "Incident support receipt is missing bundle evidence."
        if str(record.get("filename") or "") != bundle_path.name:
            return False, "Incident support receipt references a different bundle."
        if self._safe_int(record.get("size_bytes"), default=-1) != bundle_path.stat().st_size:
            return False, "Incident support receipt bundle size does not match."
        if str(record.get("sha256") or "") != self._sha256(bundle_path):
            return False, "Incident support receipt bundle SHA-256 does not match."
        return True, "Incident support receipt matches the selected verified bundle."

    def _verify_support_artifact(
        self, record: Any, directory: Path
    ) -> tuple[bool, str]:
        ok, detail = self._verify_artifact_record(record, directory)
        if not ok:
            return False, detail
        candidate = directory / str(record.get("filename") or "")
        return self.incident_support_service.verify_bundle(candidate)

    def _verify_artifact_record(self, record: Any, directory: Path) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Incident triage evidence record is invalid."
        filename = str(record.get("filename") or "")
        if not filename or Path(filename).name != filename:
            return False, "Incident triage evidence filename is unsafe."
        candidate = Path(directory) / filename
        if not candidate.is_file():
            return False, f"Incident triage evidence is missing: {filename}"
        if candidate.stat().st_size != self._safe_int(record.get("size_bytes"), default=-1):
            return False, f"Incident triage evidence size mismatch: {filename}"
        if self._sha256(candidate) != str(record.get("sha256") or ""):
            return False, f"Incident triage evidence SHA-256 mismatch: {filename}"
        return True, f"Incident triage evidence verified: {filename}"

    def _duplicate_count(self, fingerprint: str) -> int:
        count = 0
        for path in self.cases_dir.glob("triage-*.json"):
            payload = self._read_json(path)
            if not isinstance(payload, dict) or str(payload.get("fingerprint") or "") != fingerprint:
                continue
            ok, _detail = self.verify_case(path)
            if ok:
                count += 1
        return count

    def _effective_severity(
        self,
        reported: str,
        *,
        report_count: int,
        unacknowledged_count: int,
        safe_mode: bool,
        component: str,
    ) -> str:
        level = self._SEVERITY_ORDER.get(reported, 1)
        if report_count >= 5 or unacknowledged_count >= 3 or safe_mode:
            level = max(level, self._SEVERITY_ORDER["high"])
        if component == "security":
            level = max(level, self._SEVERITY_ORDER["high"])
        return ("low", "medium", "high", "critical")[level]

    def _classify_component(self, summary: str) -> str:
        for component, pattern in self._COMPONENT_PATTERNS:
            if pattern.search(summary):
                return component
        return "general"

    def _actions(
        self, component: str, acknowledgement_target: int, remediation_target: int
    ) -> tuple[IncidentTriageAction, ...]:
        component_action = {
            "security": "Isolate the affected trust boundary and refresh security evidence",
            "update": "Compare stable feed, installer, rollback and promotion receipts",
            "provider": "Reproduce against a non-secret test provider profile and inspect health evidence",
            "queue": "Reproduce with a bounded queue and capture scheduler state transitions",
            "audio": "Reproduce with a small fixture and compare generation, playback and export evidence",
            "performance": "Capture bounded performance samples and compare against certified budgets",
            "data": "Verify backup, schema, migration and artifact integrity before any data change",
            "interface": "Reproduce across certified themes and display profiles with accessibility checks",
            "general": "Reproduce the incident with the smallest safe deterministic fixture",
        }[component]
        return (
            IncidentTriageAction(1, "acknowledge", "Assign a human incident owner", "incident_commander", acknowledgement_target),
            IncidentTriageAction(2, "preserve", "Preserve the verified bundle, receipt and case fingerprint", "support_engineer", acknowledgement_target),
            IncidentTriageAction(3, "isolate", component_action, "component_owner", remediation_target),
            IncidentTriageAction(4, "baseline_compare", "Compare findings with the verified post-GA maintenance baseline", "release_engineer", remediation_target),
            IncidentTriageAction(5, "quality_gate", "Run dedicated regression tests and the full Quality Gate after a candidate fix", "quality_owner", remediation_target),
            IncidentTriageAction(6, "human_approval", "Review rollback, patch and publication decisions outside automatic execution", "release_approver", remediation_target),
        )

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> IncidentTriageGate:
        return IncidentTriageGate(code, label, status, severity, detail, remediation)

    @staticmethod
    def _path_record(path: Path) -> dict[str, object]:
        candidate = Path(path)
        return {
            "filename": candidate.name,
            "size_bytes": candidate.stat().st_size,
            "sha256": IncidentTriageService._sha256(candidate),
        }

    @staticmethod
    def _fingerprint(summary: str, component: str, version: str) -> str:
        normalized = re.sub(r"\s+", " ", summary.casefold()).strip()
        raw = f"{version}|{component}|{normalized}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

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
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _safe_detail(exc: BaseException) -> str:
        return re.sub(r"[\r\n\t]+", " ", str(exc)).strip()[:240]

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat().replace("+00:00", "Z")
