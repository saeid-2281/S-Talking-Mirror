from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.incident_prevention import (
    IncidentPreventionAction,
    IncidentPreventionGate,
    IncidentPreventionPattern,
    IncidentPreventionRecord,
    IncidentPreventionSnapshot,
    IncidentPreventionSource,
)
from app.services.incident_resolution_service import IncidentResolutionService


class IncidentPreventionService:
    """Aggregate verified closures into privacy-safe preventive-action records.

    Phase 66 is deliberately analytical and human controlled. The service never
    edits a closed incident, deploys a change, creates an external ticket,
    schedules work, publishes knowledge, restarts the application or executes a
    preventive action. It creates local tamper-evident baselines and an open
    action register only after explicit acknowledgement.
    """

    SCHEMA_VERSION = 1
    DEFAULT_LOOKBACK_DAYS = 90
    DEFAULT_RECURRENCE_THRESHOLD = 2
    DEFAULT_HIGH_RISK_THRESHOLD = 70
    MIN_LOOKBACK_DAYS = 7
    MAX_LOOKBACK_DAYS = 3650
    MIN_RECURRENCE_THRESHOLD = 2
    MAX_RECURRENCE_THRESHOLD = 20
    MIN_HIGH_RISK_THRESHOLD = 50
    MAX_HIGH_RISK_THRESHOLD = 100
    _PRIORITY_WEIGHT = {"P0": 90, "P1": 75, "P2": 50, "P3": 25}
    _FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

    def __init__(
        self,
        runtime: RuntimeConfig,
        incident_resolution_service: IncidentResolutionService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.incident_resolution_service = (
            incident_resolution_service or IncidentResolutionService(runtime)
        )
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "incident-prevention"
        self.baselines_dir = self.root / "baselines"
        self.registers_dir = self.root / "registers"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (self.root, self.baselines_dir, self.registers_dir):
            path.mkdir(parents=True, exist_ok=True)

    def default_closure_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.incident_resolution_service.closures_dir.glob("*-closure.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        )

    def snapshot(
        self,
        *,
        closure_paths: Iterable[Path] = (),
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        recurrence_threshold: int = DEFAULT_RECURRENCE_THRESHOLD,
        high_risk_threshold: int = DEFAULT_HIGH_RISK_THRESHOLD,
    ) -> IncidentPreventionSnapshot:
        selected = tuple(dict.fromkeys(Path(path) for path in closure_paths))
        if not selected:
            selected = self.default_closure_paths()
        generated_at = self._now_iso()
        snapshot_id = (
            f"prevention-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        gates: list[IncidentPreventionGate] = []

        identity_ok = self.version == app.__version__ and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Stable application identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Running identity is {self.version}/{self.channel}."
                    if identity_ok
                    else "Incident prevention requires the current stable application identity."
                ),
                "Run this workflow from the verified stable build.",
            )
        )

        parameters_ok = (
            self.MIN_LOOKBACK_DAYS <= int(lookback_days) <= self.MAX_LOOKBACK_DAYS
            and self.MIN_RECURRENCE_THRESHOLD
            <= int(recurrence_threshold)
            <= self.MAX_RECURRENCE_THRESHOLD
            and self.MIN_HIGH_RISK_THRESHOLD
            <= int(high_risk_threshold)
            <= self.MAX_HIGH_RISK_THRESHOLD
        )
        gates.append(
            self._gate(
                "analysis_policy",
                "Trend-analysis policy",
                "pass" if parameters_ok else "block",
                "blocker",
                (
                    f"Policy uses {lookback_days} days, recurrence threshold {recurrence_threshold}, "
                    f"and high-risk threshold {high_risk_threshold}."
                    if parameters_ok
                    else "Trend-analysis parameters are outside the supported safety range."
                ),
                "Use a 7-3650 day lookback, recurrence threshold 2-20 and risk threshold 50-100.",
            )
        )

        gates.append(
            self._gate(
                "closure_selection",
                "Incident closure selection",
                "pass" if selected else "block",
                "blocker",
                (
                    f"Selected {len(selected)} incident closure certificate(s)."
                    if selected
                    else "No incident closure certificates are available."
                ),
                "Create a verified Phase 65 closure or select existing closure files.",
            )
        )

        verified: list[IncidentPreventionSource] = []
        rejected_count = 0
        ignored_count = 0
        if parameters_ok:
            for path in selected:
                source, state = self._inspect_closure(
                    path,
                    lookback_days=int(lookback_days),
                )
                if state == "ignored":
                    ignored_count += 1
                elif source is None:
                    rejected_count += 1
                else:
                    verified.append(source)

        if verified:
            integrity_status = "warn" if rejected_count else "pass"
            integrity_detail = (
                f"Verified {len(verified)} closure(s); rejected {rejected_count} invalid closure(s)."
                if rejected_count
                else f"Verified all {len(verified)} in-scope closure certificate(s)."
            )
        else:
            integrity_status = "block"
            integrity_detail = "No in-scope closure certificate passed the complete integrity chain."
        gates.append(
            self._gate(
                "closure_integrity",
                "Closure, resolution and case integrity",
                integrity_status,
                "blocker" if integrity_status == "block" else "warning",
                integrity_detail,
                "Remove tampered records and select verified Phase 65 closure certificates.",
            )
        )

        gates.append(
            self._gate(
                "lookback_scope",
                "Lookback scope",
                "warn" if ignored_count else "pass",
                "warning",
                (
                    f"Ignored {ignored_count} verified closure(s) older than {lookback_days} days."
                    if ignored_count
                    else "All verified closure certificates are inside the selected lookback window."
                ),
                "Increase the lookback window only after human review of the analysis scope.",
            )
        )

        patterns = self._patterns(
            verified,
            recurrence_threshold=int(recurrence_threshold),
            high_risk_threshold=int(high_risk_threshold),
        )
        recurring_count = sum(pattern.recurring for pattern in patterns)
        high_risk_count = sum(pattern.high_risk for pattern in patterns)
        trend_status = "warn" if recurring_count or high_risk_count else "pass"
        gates.append(
            self._gate(
                "recurrence_risk",
                "Recurrence and preventive risk",
                trend_status,
                "warning",
                (
                    f"Found {recurring_count} recurring and {high_risk_count} high-risk pattern(s)."
                    if trend_status == "warn"
                    else "No recurring or high-risk pattern crossed the configured thresholds."
                ),
                "Review the manual preventive-action register before scheduling any work.",
            )
        )

        gates.append(
            self._gate(
                "privacy_contract",
                "Privacy-safe aggregation",
                "pass",
                "blocker",
                "The analysis stores only verified identifiers, hashes, timestamps and categorical metadata; incident narratives are not copied.",
            )
        )
        gates.append(
            self._gate(
                "manual_operations",
                "Human-controlled preventive operations",
                "pass",
                "blocker",
                "All proposed actions remain open, local and automatic=false until separately approved and executed by a human.",
            )
        )

        actions = self._actions(patterns)
        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            status_summary = f"Incident prevention baseline is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_warnings"
            status_summary = (
                f"Incident prevention baseline is ready with {warning_count} warning(s) for human review."
            )
        else:
            status = "ready"
            status_summary = "Verified incident history is ready for an acknowledged prevention baseline."

        return IncidentPreventionSnapshot(
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            lookback_days=int(lookback_days),
            recurrence_threshold=int(recurrence_threshold),
            high_risk_threshold=int(high_risk_threshold),
            status=status,
            status_summary=status_summary,
            baseline_allowed=blocker_count == 0,
            selected_count=len(selected),
            verified_count=len(verified),
            rejected_count=rejected_count,
            ignored_count=ignored_count,
            recurring_pattern_count=recurring_count,
            high_risk_pattern_count=high_risk_count,
            sources=tuple(verified),
            patterns=patterns,
            gates=tuple(gates),
            actions=actions,
        )

    def create_baseline(
        self,
        snapshot: IncidentPreventionSnapshot,
        *,
        acknowledge: bool = False,
    ) -> IncidentPreventionRecord | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review and acknowledge every prevention gate before creating local records.",
                "path": "",
            }

        refreshed = self.snapshot(
            closure_paths=tuple(source.path for source in snapshot.sources),
            lookback_days=snapshot.lookback_days,
            recurrence_threshold=snapshot.recurrence_threshold,
            high_risk_threshold=snapshot.high_risk_threshold,
        )
        if refreshed.blocker_count:
            return {"status": "blocked", "detail": refreshed.status_summary, "path": ""}
        expected_sources = {(item.path.name, item.sha256) for item in snapshot.sources}
        actual_sources = {(item.path.name, item.sha256) for item in refreshed.sources}
        if expected_sources != actual_sources:
            return {
                "status": "blocked",
                "detail": "Incident closure evidence changed after the prevention snapshot was reviewed.",
                "path": "",
            }

        baseline_id = (
            f"baseline-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        created_at = self._now_iso()
        register_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "register_id": f"register-{uuid.uuid4().hex[:12]}",
            "baseline_id": baseline_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "open",
            "actions": [
                {
                    **action.to_dict(),
                    "status": "open",
                    "completed_at": "",
                    "completion_evidence": "",
                }
                for action in refreshed.actions
            ],
            "human_owner_required": True,
            "human_approval_required": True,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        register_payload["register_sha256"] = self._payload_digest(register_payload)
        register_path = self.registers_dir / f"{baseline_id}-action-register.json"
        self._write_json(register_path, register_payload)

        baseline_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "baseline_id": baseline_id,
            "snapshot_id": refreshed.snapshot_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "lookback_days": refreshed.lookback_days,
            "recurrence_threshold": refreshed.recurrence_threshold,
            "high_risk_threshold": refreshed.high_risk_threshold,
            "source_closures": [self._path_record(source.path) for source in refreshed.sources],
            "patterns": [pattern.to_dict() for pattern in refreshed.patterns],
            "metrics": {
                "source_closure_count": refreshed.verified_count,
                "pattern_count": len(refreshed.patterns),
                "recurring_pattern_count": refreshed.recurring_pattern_count,
                "high_risk_pattern_count": refreshed.high_risk_pattern_count,
                "open_action_count": len(refreshed.actions),
            },
            "action_register": self._path_record(register_path),
            "human_review_completed": True,
            "human_owner_required": True,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        baseline_payload["baseline_sha256"] = self._payload_digest(baseline_payload)
        baseline_path = self.baselines_dir / f"{baseline_id}.json"
        self._write_json(baseline_path, baseline_payload)

        baseline_ok, baseline_detail = self.verify_baseline(baseline_path)
        register_ok, register_detail = self.verify_register(register_path)
        if not baseline_ok or not register_ok:
            baseline_path.unlink(missing_ok=True)
            register_path.unlink(missing_ok=True)
            return {
                "status": "blocked",
                "detail": baseline_detail if not baseline_ok else register_detail,
                "path": "",
            }

        self._write_json(self.root / "latest-incident-prevention-baseline.json", baseline_payload)
        self._write_json(self.root / "latest-preventive-action-register.json", register_payload)
        return IncidentPreventionRecord(
            baseline_id=baseline_id,
            created_at=created_at,
            baseline_path=baseline_path,
            register_path=register_path,
            source_closure_count=refreshed.verified_count,
            pattern_count=len(refreshed.patterns),
            recurring_pattern_count=refreshed.recurring_pattern_count,
            high_risk_pattern_count=refreshed.high_risk_pattern_count,
        )

    def verify_baseline(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Incident prevention baseline is unreadable."
        expected = str(payload.get("baseline_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("baseline_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Incident prevention baseline SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get("human_review_completed") is not True:
            return False, "Incident prevention baseline is missing human review."
        sources = payload.get("source_closures")
        if not isinstance(sources, list) or not sources:
            return False, "Incident prevention baseline has no source closure evidence."
        for record in sources:
            ok, detail = self._verify_artifact_record(
                record,
                self.incident_resolution_service.closures_dir,
            )
            if not ok:
                return False, detail
            closure_path = self.incident_resolution_service.closures_dir / str(
                record.get("filename") or ""
            )
            ok, detail = self.incident_resolution_service.verify_closure(closure_path)
            if not ok:
                return False, detail
        patterns = payload.get("patterns")
        if not isinstance(patterns, list) or not patterns:
            return False, "Incident prevention baseline has no trend patterns."
        for pattern in patterns:
            if not isinstance(pattern, Mapping):
                return False, "Incident prevention baseline contains an invalid pattern."
            fingerprint = str(pattern.get("fingerprint") or "")
            if not self._FINGERPRINT_RE.fullmatch(fingerprint):
                return False, "Incident prevention baseline contains an invalid fingerprint."
            if self._safe_int(pattern.get("occurrence_count")) < 1:
                return False, "Incident prevention baseline contains an empty pattern."
        register_record = payload.get("action_register")
        ok, detail = self._verify_artifact_record(register_record, self.registers_dir)
        if not ok:
            return False, detail
        register_path = self.registers_dir / str(register_record.get("filename") or "")
        ok, detail = self.verify_register(register_path)
        if not ok:
            return False, detail
        register_payload = self._read_json(register_path) or {}
        if str(register_payload.get("baseline_id") or "") != str(payload.get("baseline_id") or ""):
            return False, "Preventive action register belongs to another baseline."
        return True, "Incident prevention baseline and source closure chain are intact."

    def verify_register(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Preventive action register is unreadable."
        expected = str(payload.get("register_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("register_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Preventive action register SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "open":
            return False, "Preventive action register is not in the open state."
        if payload.get("human_owner_required") is not True or payload.get("human_approval_required") is not True:
            return False, "Preventive action register is missing human-control requirements."
        actions = payload.get("actions")
        if not isinstance(actions, list) or len(actions) < 6:
            return False, "Preventive action register is missing required actions."
        for action in actions:
            if not isinstance(action, Mapping):
                return False, "Preventive action register contains an invalid action."
            if action.get("automatic") is not False or action.get("status") != "open":
                return False, "Preventive action register contains an automatic or pre-completed action."
            if str(action.get("completed_at") or "") or str(action.get("completion_evidence") or ""):
                return False, "Preventive action register incorrectly claims completion evidence."
        return True, f"Preventive action register verified with {len(actions)} open manual action(s)."

    def export_snapshot(self, snapshot: IncidentPreventionSnapshot) -> Path:
        path = self.root / "incident-prevention-summary.json"
        payload = snapshot.to_dict()
        payload.update(
            {
                "human_review_required": True,
                "automatic_ticket_creation": False,
                "automatic_scheduling": False,
                "automatic_patch": False,
                "automatic_deploy": False,
                "automatic_rollback": False,
                "automatic_restart": False,
                "automatic_publish": False,
                "private_data_included": False,
            }
        )
        self._write_json(path, payload)
        return path

    def _inspect_closure(
        self,
        path: Path,
        *,
        lookback_days: int,
    ) -> tuple[IncidentPreventionSource | None, str]:
        candidate = Path(path)
        ok, detail = self.incident_resolution_service.verify_closure(candidate)
        if not ok:
            return None, detail
        closure = self._read_json(candidate) or {}
        closed_at = str(closure.get("created_at") or "")
        closed_dt = self._parse_datetime(closed_at)
        if closed_dt is None:
            return None, "Incident closure contains an invalid timestamp."
        age_days = max(0, int((self._now() - closed_dt).total_seconds() // 86400))
        if age_days > lookback_days:
            return None, "ignored"

        resolution_record = closure.get("resolution")
        if not isinstance(resolution_record, Mapping):
            return None, "Incident closure is missing its resolution record."
        resolution_path = self.incident_resolution_service.records_dir / str(
            resolution_record.get("filename") or ""
        )
        resolution = self._read_json(resolution_path) or {}
        case_record = resolution.get("case")
        if not isinstance(case_record, Mapping):
            return None, "Incident resolution is missing its triage case record."
        triage = self.incident_resolution_service.incident_triage_service
        case_path = triage.cases_dir / str(case_record.get("filename") or "")
        case_ok, case_detail = triage.verify_case(case_path)
        if not case_ok:
            return None, case_detail
        case = self._read_json(case_path) or {}
        fingerprint = str(case.get("fingerprint") or "")
        if not self._FINGERPRINT_RE.fullmatch(fingerprint):
            return None, "Incident triage fingerprint is invalid."
        return (
            IncidentPreventionSource(
                path=candidate,
                closure_id=str(closure.get("closure_id") or ""),
                resolution_id=str(closure.get("resolution_id") or ""),
                case_id=str(closure.get("case_id") or ""),
                fingerprint=fingerprint,
                priority=str(closure.get("priority") or case.get("priority") or "P3"),
                component=str(closure.get("component") or case.get("component") or "general"),
                resolution_type=str(resolution.get("resolution_type") or "unknown"),
                closed_at=closed_at,
                age_days=age_days,
                sha256=self._sha256(candidate),
            ),
            detail,
        )

    def _patterns(
        self,
        sources: Iterable[IncidentPreventionSource],
        *,
        recurrence_threshold: int,
        high_risk_threshold: int,
    ) -> tuple[IncidentPreventionPattern, ...]:
        groups: dict[str, list[IncidentPreventionSource]] = defaultdict(list)
        for source in sources:
            groups[source.fingerprint].append(source)
        patterns: list[IncidentPreventionPattern] = []
        for fingerprint, items in groups.items():
            ordered = sorted(items, key=lambda item: item.closed_at)
            occurrence_count = len(ordered)
            max_priority = max(
                (self._PRIORITY_WEIGHT.get(item.priority, 25) for item in ordered),
                default=25,
            )
            recurrence_bonus = min(20, max(0, occurrence_count - 1) * 10)
            newest_age = min(item.age_days for item in ordered)
            recency_bonus = 10 if newest_age <= 14 else 5 if newest_age <= 30 else 0
            risk_score = min(100, max_priority + recurrence_bonus + recency_bonus)
            patterns.append(
                IncidentPreventionPattern(
                    fingerprint=fingerprint,
                    component=ordered[-1].component,
                    resolution_type=ordered[-1].resolution_type,
                    occurrence_count=occurrence_count,
                    priorities=tuple(sorted({item.priority for item in ordered})),
                    case_ids=tuple(item.case_id for item in ordered),
                    first_closed_at=ordered[0].closed_at,
                    last_closed_at=ordered[-1].closed_at,
                    risk_score=risk_score,
                    recurring=occurrence_count >= recurrence_threshold,
                    high_risk=risk_score >= high_risk_threshold,
                )
            )
        return tuple(
            sorted(
                patterns,
                key=lambda item: (-item.risk_score, -item.occurrence_count, item.fingerprint),
            )
        )

    @staticmethod
    def _actions(
        patterns: Iterable[IncidentPreventionPattern],
    ) -> tuple[IncidentPreventionAction, ...]:
        pattern_list = tuple(patterns)
        actions = [
            IncidentPreventionAction(1, "assign_owner", "Assign a human problem-management owner", "reliability_lead", 2),
            IncidentPreventionAction(2, "review_chain", "Review verified closure and case custody", "incident_manager", 3),
            IncidentPreventionAction(3, "root_cause", "Perform a documented root-cause review", "component_owner", 7),
            IncidentPreventionAction(4, "regression_guard", "Define regression and observability guardrails", "quality_owner", 14),
            IncidentPreventionAction(5, "change_review", "Review any proposed preventive change separately", "change_approver", 21),
            IncidentPreventionAction(6, "baseline_review", "Approve or reject the local prevention baseline", "release_owner", 30),
        ]
        order = len(actions) + 1
        for pattern in pattern_list:
            if not (pattern.recurring or pattern.high_risk):
                continue
            target_days = 7 if pattern.high_risk else 14
            actions.append(
                IncidentPreventionAction(
                    order,
                    f"pattern_{pattern.fingerprint[:12]}",
                    f"Review {pattern.component} recurrence pattern {pattern.fingerprint[:12]}",
                    "component_owner",
                    target_days,
                    pattern_fingerprint=pattern.fingerprint,
                )
            )
            order += 1
        return tuple(actions)

    def _verify_common_contract(self, payload: Mapping[str, object]) -> tuple[bool, str]:
        if str(payload.get("version") or "") != self.version:
            return False, "Incident prevention identity does not match the application."
        if str(payload.get("channel") or "") != "stable":
            return False, "Incident prevention channel is not stable."
        if payload.get("private_data_included") is not False:
            return False, "Incident prevention record violates the privacy contract."
        for name in (
            "automatic_ticket_creation",
            "automatic_scheduling",
            "automatic_patch",
            "automatic_deploy",
            "automatic_rollback",
            "automatic_restart",
            "automatic_publish",
        ):
            if payload.get(name) is not False:
                return False, "Incident prevention record contains an automatic operation."
        return True, "Incident prevention manual-operation contract is intact."

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> IncidentPreventionGate:
        return IncidentPreventionGate(code, label, status, severity, detail, remediation)

    @staticmethod
    def _path_record(path: Path) -> dict[str, object]:
        candidate = Path(path)
        return {
            "filename": candidate.name,
            "size_bytes": candidate.stat().st_size,
            "sha256": IncidentPreventionService._sha256(candidate),
        }

    @staticmethod
    def _verify_artifact_record(
        record: object,
        root: Path,
    ) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Incident prevention record is missing artifact evidence."
        filename = str(record.get("filename") or "")
        if not filename or Path(filename).name != filename:
            return False, "Incident prevention artifact filename is invalid."
        candidate = root / filename
        if not candidate.is_file():
            return False, f"Incident prevention artifact is missing: {filename}."
        if IncidentPreventionService._safe_int(record.get("size_bytes"), -1) != candidate.stat().st_size:
            return False, f"Incident prevention artifact size does not match: {filename}."
        if str(record.get("sha256") or "") != IncidentPreventionService._sha256(candidate):
            return False, f"Incident prevention artifact SHA-256 does not match: {filename}."
        return True, f"Incident prevention artifact verified: {filename}."

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
        path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
