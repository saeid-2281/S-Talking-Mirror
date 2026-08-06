from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.prevention_effectiveness import (
    PreventionEffectivenessGate,
    PreventionEffectivenessPattern,
    PreventionEffectivenessRecord,
    PreventionEffectivenessSnapshot,
    PreventiveActionState,
)
from app.services.incident_prevention_service import IncidentPreventionService


class PreventionEffectivenessService:
    """Review preventive actions and residual recurrence without automatic changes.

    Phase 67 preserves every Phase 66 source record. It records human action
    attestations and produces local, tamper-evident effectiveness reviews. The
    service never completes work on behalf of an owner, edits a Phase 66 action
    register, accepts risk automatically, deploys, rolls back, restarts, creates
    tickets, schedules work or publishes records.
    """

    SCHEMA_VERSION = 1
    DEFAULT_OBSERVATION_DAYS = 30
    MIN_OBSERVATION_DAYS = 7
    MAX_OBSERVATION_DAYS = 3650
    ACTION_STATUSES = ("completed", "deferred", "risk_accepted")
    REVIEW_DECISIONS = (
        "continue_monitoring",
        "escalate_prevention",
        "accept_residual_risk",
        "close_effective",
    )
    _SAFE_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,127}$")
    _FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        incident_prevention_service: IncidentPreventionService | None = None,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.incident_prevention_service = (
            incident_prevention_service or IncidentPreventionService(runtime)
        )
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "prevention-effectiveness"
        self.attestations_dir = self.root / "attestations"
        self.reviews_dir = self.root / "reviews"
        self.decisions_dir = self.root / "decisions"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.attestations_dir,
            self.reviews_dir,
            self.decisions_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_baseline_path(self) -> Path:
        candidates = sorted(
            self.incident_prevention_service.baselines_dir.glob("baseline-*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
        return self.incident_prevention_service.root / "latest-incident-prevention-baseline.json"

    def default_register_path(self, baseline_path: Path | None = None) -> Path:
        baseline = self._read_json(Path(baseline_path or self.default_baseline_path())) or {}
        record = baseline.get("action_register")
        if isinstance(record, Mapping):
            filename = str(record.get("filename") or "")
            if filename:
                return self.incident_prevention_service.registers_dir / filename
        candidates = sorted(
            self.incident_prevention_service.registers_dir.glob("*-action-register.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
        return self.incident_prevention_service.root / "latest-preventive-action-register.json"

    def default_closure_paths(self) -> tuple[Path, ...]:
        return self.incident_prevention_service.default_closure_paths()

    def create_action_attestation(
        self,
        *,
        baseline_path: Path,
        register_path: Path,
        action_code: str,
        status: str,
        owner: str,
        evidence_summary: str,
        evidence_reference: str = "",
        acknowledge: bool = False,
    ) -> Path | dict[str, object]:
        baseline, register, detail = self._verified_sources(baseline_path, register_path)
        if baseline is None or register is None:
            return {"status": "blocked", "detail": detail, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the action, evidence and ownership before attesting an outcome.",
                "path": "",
            }

        normalized_code = str(action_code or "").strip()
        normalized_status = str(status or "").strip().lower()
        normalized_owner = self._clean_text(owner, minimum=3, maximum=120)
        normalized_summary = self._clean_text(evidence_summary, minimum=12, maximum=800)
        normalized_reference = self._clean_text(
            evidence_reference,
            minimum=0,
            maximum=240,
            allow_empty=True,
        )
        if not self._SAFE_CODE_RE.fullmatch(normalized_code):
            return {"status": "blocked", "detail": "Action code is invalid.", "path": ""}
        if normalized_status not in self.ACTION_STATUSES:
            return {"status": "blocked", "detail": "Action outcome is unsupported.", "path": ""}
        if normalized_owner is None:
            return {"status": "blocked", "detail": "A privacy-safe human owner is required.", "path": ""}
        if normalized_summary is None:
            return {"status": "blocked", "detail": "Privacy-safe completion evidence is required.", "path": ""}
        if normalized_reference is None:
            return {
                "status": "blocked",
                "detail": "Evidence reference contains a secret or a local absolute path.",
                "path": "",
            }
        if normalized_status == "completed" and not normalized_reference:
            return {
                "status": "blocked",
                "detail": "Completed actions require a human-readable evidence reference.",
                "path": "",
            }

        action = self._register_action(register, normalized_code)
        if action is None:
            return {"status": "blocked", "detail": "Action is not present in the verified register.", "path": ""}

        baseline_id = str(baseline.get("baseline_id") or "")
        register_id = str(register.get("register_id") or "")
        created_at = self._now_iso()
        attestation_id = f"attestation-{uuid.uuid4().hex[:12]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "attestation_id": attestation_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "baseline_id": baseline_id,
            "register_id": register_id,
            "action_code": normalized_code,
            "action_label": str(action.get("label") or ""),
            "action_status": normalized_status,
            "owner": normalized_owner,
            "evidence_summary": normalized_summary,
            "evidence_reference": normalized_reference,
            "baseline": self._path_record(Path(baseline_path)),
            "register": self._path_record(Path(register_path)),
            "human_attestation": True,
            "human_approval_required": True,
            "automatic_completion": False,
            "automatic_risk_acceptance": False,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        payload["attestation_sha256"] = self._payload_digest(payload)
        path = self.attestations_dir / f"{baseline_id}-{normalized_code}-{attestation_id}.json"
        self._write_json(path, payload)
        ok, verified_detail = self.verify_attestation(path)
        if not ok:
            path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": verified_detail, "path": ""}
        self._write_json(self.root / "latest-action-attestation.json", payload)
        return path

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Preventive action attestation is unreadable."
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Preventive action attestation SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("human_attestation") is not True:
            return False, "Preventive action attestation lacks human acknowledgement."
        if str(payload.get("action_status") or "") not in self.ACTION_STATUSES:
            return False, "Preventive action attestation status is invalid."
        code = str(payload.get("action_code") or "")
        if not self._SAFE_CODE_RE.fullmatch(code):
            return False, "Preventive action attestation code is invalid."
        for field in ("owner", "evidence_summary", "evidence_reference"):
            value = str(payload.get(field) or "")
            if self._contains_private_material(value):
                return False, "Preventive action attestation contains private material."
        baseline_record = payload.get("baseline")
        register_record = payload.get("register")
        ok, detail = self._verify_artifact_record(
            baseline_record,
            self.incident_prevention_service.baselines_dir,
        )
        if not ok:
            return False, detail
        ok, detail = self._verify_artifact_record(
            register_record,
            self.incident_prevention_service.registers_dir,
        )
        if not ok:
            return False, detail
        baseline_path = self.incident_prevention_service.baselines_dir / str(
            baseline_record.get("filename") or ""
        )
        register_path = self.incident_prevention_service.registers_dir / str(
            register_record.get("filename") or ""
        )
        baseline, register, detail = self._verified_sources(baseline_path, register_path)
        if baseline is None or register is None:
            return False, detail
        if str(payload.get("baseline_id") or "") != str(baseline.get("baseline_id") or ""):
            return False, "Preventive action attestation baseline identity does not match."
        if str(payload.get("register_id") or "") != str(register.get("register_id") or ""):
            return False, "Preventive action attestation register identity does not match."
        if self._register_action(register, code) is None:
            return False, "Preventive action attestation references an unknown action."
        return True, "Preventive action attestation is intact and human controlled."

    def snapshot(
        self,
        *,
        baseline_path: Path | None = None,
        register_path: Path | None = None,
        closure_paths: Iterable[Path] = (),
        observation_days: int = DEFAULT_OBSERVATION_DAYS,
    ) -> PreventionEffectivenessSnapshot:
        baseline_path = Path(baseline_path or self.default_baseline_path())
        register_path = Path(register_path or self.default_register_path(baseline_path))
        selected = tuple(dict.fromkeys(Path(path) for path in closure_paths))
        if not selected:
            selected = self.default_closure_paths()
        generated_at = self._now_iso()
        snapshot_id = (
            f"effectiveness-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        gates: list[PreventionEffectivenessGate] = []

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
                    else "Prevention effectiveness review requires the current stable identity."
                ),
                "Run this workflow from the verified stable build.",
            )
        )

        observation_ok = self.MIN_OBSERVATION_DAYS <= int(observation_days) <= self.MAX_OBSERVATION_DAYS
        gates.append(
            self._gate(
                "observation_policy",
                "Observation policy",
                "pass" if observation_ok else "block",
                "blocker",
                (
                    f"Observation window is {observation_days} day(s)."
                    if observation_ok
                    else "Observation window is outside the supported 7-3650 day range."
                ),
                "Choose an observation window between 7 and 3650 days.",
            )
        )

        baseline, register, source_detail = self._verified_sources(baseline_path, register_path)
        sources_ok = baseline is not None and register is not None
        gates.append(
            self._gate(
                "phase66_custody",
                "Phase 66 baseline and register custody",
                "pass" if sources_ok else "block",
                "blocker",
                source_detail,
                "Select an intact Phase 66 baseline and its matching action register.",
            )
        )

        baseline_id = str((baseline or {}).get("baseline_id") or "")
        register_id = str((register or {}).get("register_id") or "")
        baseline_created_at = self._parse_datetime(str((baseline or {}).get("created_at") or ""))

        attestations, rejected_attestations = self._latest_attestations(
            baseline_id=baseline_id,
            register_id=register_id,
        )
        gates.append(
            self._gate(
                "attestation_integrity",
                "Preventive action attestations",
                "block" if rejected_attestations else "pass",
                "blocker",
                (
                    f"Rejected {rejected_attestations} invalid action attestation(s)."
                    if rejected_attestations
                    else f"Verified {len(attestations)} latest action attestation(s)."
                ),
                "Remove tampered attestations and recreate them after human review.",
            )
        )

        actions = self._action_states(
            baseline=baseline or {},
            register=register or {},
            attestations=attestations,
        )
        open_count = sum(action.status == "open" for action in actions)
        completed_count = sum(action.status == "completed" for action in actions)
        deferred_count = sum(action.status == "deferred" for action in actions)
        accepted_count = sum(action.status == "risk_accepted" for action in actions)
        overdue_count = sum(action.overdue for action in actions)
        gates.append(
            self._gate(
                "action_governance",
                "Preventive action governance",
                "warn" if overdue_count or deferred_count or accepted_count else "pass",
                "warning",
                (
                    f"Actions: {completed_count} completed, {open_count} open, "
                    f"{deferred_count} deferred, {accepted_count} risk accepted, "
                    f"{overdue_count} overdue."
                ),
                "Review overdue, deferred and risk-accepted actions with a human owner.",
            )
        )

        verified_sources = []
        rejected_closures = 0
        ignored_closures = 0
        if sources_ok and observation_ok and baseline_created_at is not None:
            for path in selected:
                inspected, detail = self.incident_prevention_service._inspect_closure(
                    path,
                    lookback_days=int(observation_days),
                )
                if inspected is None:
                    if detail == "ignored":
                        ignored_closures += 1
                    else:
                        rejected_closures += 1
                    continue
                closed_at = self._parse_datetime(inspected.closed_at)
                if closed_at is None or closed_at <= baseline_created_at:
                    ignored_closures += 1
                    continue
                verified_sources.append(inspected)

        gates.append(
            self._gate(
                "post_baseline_custody",
                "Post-baseline closure custody",
                "block" if rejected_closures else "pass",
                "blocker",
                (
                    f"Verified {len(verified_sources)} post-baseline closure(s); "
                    f"ignored {ignored_closures}; rejected {rejected_closures}."
                ),
                "Remove tampered closure evidence before completing the review.",
            )
        )

        patterns = self._effectiveness_patterns(
            baseline=baseline or {},
            sources=verified_sources,
            actions=actions,
            observation_days=int(observation_days),
        )
        recurrent_count = sum(pattern.new_recurrence for pattern in patterns)
        ineffective_count = sum(pattern.effectiveness == "ineffective" for pattern in patterns)
        gates.append(
            self._gate(
                "effectiveness_outcome",
                "Recurrence and residual effectiveness",
                "warn" if recurrent_count or ineffective_count else "pass",
                "warning",
                (
                    f"Found {recurrent_count} post-baseline recurrence pattern(s) and "
                    f"{ineffective_count} ineffective pattern(s)."
                    if recurrent_count or ineffective_count
                    else "No verified post-baseline recurrence crossed the reviewed patterns."
                ),
                "Escalate ineffective patterns before closing the prevention cycle.",
            )
        )

        gates.append(
            self._gate(
                "privacy_contract",
                "Privacy-safe effectiveness evidence",
                "pass",
                "blocker",
                "Reviews store identifiers, categorical outcomes, hashes and privacy-safe summaries only.",
            )
        )
        gates.append(
            self._gate(
                "manual_operations",
                "Human-controlled decisions",
                "pass",
                "blocker",
                "No action completion, risk acceptance, ticket, schedule, patch, deploy, rollback, restart or publication is automatic.",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            status_summary = f"Effectiveness review is blocked by {blocker_count} gate(s)."
        elif warning_count:
            status = "ready_with_warnings"
            status_summary = (
                f"Effectiveness review is ready with {warning_count} warning(s) for human decision."
            )
        else:
            status = "ready"
            status_summary = "Preventive actions and recurrence evidence are ready for review."

        return PreventionEffectivenessSnapshot(
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            version=self.version,
            channel=self.channel,
            baseline_path=baseline_path,
            register_path=register_path,
            baseline_id=baseline_id,
            register_id=register_id,
            observation_days=int(observation_days),
            status=status,
            status_summary=status_summary,
            review_allowed=blocker_count == 0,
            selected_closure_count=len(selected),
            verified_closure_count=len(verified_sources),
            rejected_closure_count=rejected_closures,
            ignored_closure_count=ignored_closures,
            open_action_count=open_count,
            completed_action_count=completed_count,
            deferred_action_count=deferred_count,
            accepted_risk_action_count=accepted_count,
            overdue_action_count=overdue_count,
            recurrent_pattern_count=recurrent_count,
            ineffective_pattern_count=ineffective_count,
            actions=actions,
            patterns=patterns,
            gates=tuple(gates),
        )

    def create_review(
        self,
        snapshot: PreventionEffectivenessSnapshot,
        *,
        decision: str,
        rationale: str,
        acknowledge: bool = False,
    ) -> PreventionEffectivenessRecord | dict[str, object]:
        if snapshot.blocker_count:
            return {"status": "blocked", "detail": snapshot.status_summary, "path": ""}
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the action states, recurrence evidence and decision before creating records.",
                "path": "",
            }
        normalized_decision = str(decision or "").strip().lower()
        normalized_rationale = self._clean_text(rationale, minimum=20, maximum=1200)
        if normalized_decision not in self.REVIEW_DECISIONS:
            return {"status": "blocked", "detail": "Effectiveness decision is unsupported.", "path": ""}
        if normalized_rationale is None:
            return {
                "status": "blocked",
                "detail": "A privacy-safe decision rationale of at least 20 characters is required.",
                "path": "",
            }

        refreshed = self.snapshot(
            baseline_path=snapshot.baseline_path,
            register_path=snapshot.register_path,
            closure_paths=self.default_closure_paths(),
            observation_days=snapshot.observation_days,
        )
        if refreshed.blocker_count:
            return {"status": "blocked", "detail": refreshed.status_summary, "path": ""}
        if refreshed.baseline_id != snapshot.baseline_id or refreshed.register_id != snapshot.register_id:
            return {
                "status": "blocked",
                "detail": "Phase 66 source identity changed after the effectiveness snapshot.",
                "path": "",
            }
        decision_detail = self._decision_gate(refreshed, normalized_decision)
        if decision_detail:
            return {"status": "blocked", "detail": decision_detail, "path": ""}

        review_id = f"review-{uuid.uuid4().hex[:12]}"
        created_at = self._now_iso()
        attestation_records = []
        for action in refreshed.actions:
            if not action.attestation_id:
                continue
            path = self._attestation_path(action.attestation_id)
            if path is not None:
                attestation_records.append(self._path_record(path))

        closure_records = []
        baseline_created_at = self._parse_datetime(
            str((self._read_json(refreshed.baseline_path) or {}).get("created_at") or "")
        )
        for path in self.default_closure_paths():
            inspected, _detail = self.incident_prevention_service._inspect_closure(
                path,
                lookback_days=refreshed.observation_days,
            )
            if inspected is None:
                continue
            closed_at = self._parse_datetime(inspected.closed_at)
            if baseline_created_at is not None and closed_at is not None and closed_at > baseline_created_at:
                closure_records.append(self._path_record(path))

        review_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "review_id": review_id,
            "snapshot_id": refreshed.snapshot_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "baseline_id": refreshed.baseline_id,
            "register_id": refreshed.register_id,
            "observation_days": refreshed.observation_days,
            "baseline": self._path_record(refreshed.baseline_path),
            "register": self._path_record(refreshed.register_path),
            "attestations": attestation_records,
            "post_baseline_closures": closure_records,
            "metrics": {
                "open_action_count": refreshed.open_action_count,
                "completed_action_count": refreshed.completed_action_count,
                "deferred_action_count": refreshed.deferred_action_count,
                "accepted_risk_action_count": refreshed.accepted_risk_action_count,
                "overdue_action_count": refreshed.overdue_action_count,
                "recurrent_pattern_count": refreshed.recurrent_pattern_count,
                "ineffective_pattern_count": refreshed.ineffective_pattern_count,
            },
            "actions": [action.to_dict() for action in refreshed.actions],
            "patterns": [pattern.to_dict() for pattern in refreshed.patterns],
            "human_review_completed": True,
            "automatic_completion": False,
            "automatic_risk_acceptance": False,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        review_payload["review_sha256"] = self._payload_digest(review_payload)
        review_path = self.reviews_dir / f"{review_id}.json"
        self._write_json(review_path, review_payload)

        decision_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "decision_id": f"decision-{uuid.uuid4().hex[:12]}",
            "review_id": review_id,
            "created_at": created_at,
            "version": self.version,
            "channel": self.channel,
            "baseline_id": refreshed.baseline_id,
            "decision": normalized_decision,
            "rationale": normalized_rationale,
            "status": "recorded",
            "review": self._path_record(review_path),
            "human_decision": True,
            "external_ticket_updated": False,
            "schedule_updated": False,
            "risk_register_updated": False,
            "automatic_completion": False,
            "automatic_risk_acceptance": False,
            "automatic_ticket_creation": False,
            "automatic_scheduling": False,
            "automatic_patch": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
        decision_payload["decision_sha256"] = self._payload_digest(decision_payload)
        decision_path = self.decisions_dir / f"{review_id}-decision.json"
        self._write_json(decision_path, decision_payload)

        review_ok, review_detail = self.verify_review(review_path)
        decision_ok, decision_detail = self.verify_decision(decision_path)
        if not review_ok or not decision_ok:
            review_path.unlink(missing_ok=True)
            decision_path.unlink(missing_ok=True)
            return {
                "status": "blocked",
                "detail": review_detail if not review_ok else decision_detail,
                "path": "",
            }

        self._write_json(self.root / "latest-effectiveness-review.json", review_payload)
        self._write_json(self.root / "latest-effectiveness-decision.json", decision_payload)
        return PreventionEffectivenessRecord(
            review_id=review_id,
            created_at=created_at,
            review_path=review_path,
            decision_path=decision_path,
            baseline_id=refreshed.baseline_id,
            decision=normalized_decision,
            action_count=len(refreshed.actions),
            pattern_count=len(refreshed.patterns),
        )

    def verify_review(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Prevention effectiveness review is unreadable."
        expected = str(payload.get("review_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("review_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Prevention effectiveness review SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get("human_review_completed") is not True:
            return False, "Prevention effectiveness review lacks human review."
        baseline_record = payload.get("baseline")
        register_record = payload.get("register")
        ok, detail = self._verify_artifact_record(
            baseline_record,
            self.incident_prevention_service.baselines_dir,
        )
        if not ok:
            return False, detail
        ok, detail = self._verify_artifact_record(
            register_record,
            self.incident_prevention_service.registers_dir,
        )
        if not ok:
            return False, detail
        baseline_path = self.incident_prevention_service.baselines_dir / str(
            baseline_record.get("filename") or ""
        )
        register_path = self.incident_prevention_service.registers_dir / str(
            register_record.get("filename") or ""
        )
        baseline, register, detail = self._verified_sources(baseline_path, register_path)
        if baseline is None or register is None:
            return False, detail
        if str(payload.get("baseline_id") or "") != str(baseline.get("baseline_id") or ""):
            return False, "Prevention effectiveness review baseline identity does not match."
        attestations = payload.get("attestations")
        if not isinstance(attestations, list):
            return False, "Prevention effectiveness review attestations are invalid."
        for record in attestations:
            ok, detail = self._verify_artifact_record(record, self.attestations_dir)
            if not ok:
                return False, detail
            attestation_path = self.attestations_dir / str(record.get("filename") or "")
            ok, detail = self.verify_attestation(attestation_path)
            if not ok:
                return False, detail
        closures = payload.get("post_baseline_closures")
        if not isinstance(closures, list):
            return False, "Prevention effectiveness review closure evidence is invalid."
        closure_root = self.incident_prevention_service.incident_resolution_service.closures_dir
        for record in closures:
            ok, detail = self._verify_artifact_record(record, closure_root)
            if not ok:
                return False, detail
            closure_path = closure_root / str(record.get("filename") or "")
            ok, detail = (
                self.incident_prevention_service.incident_resolution_service.verify_closure(
                    closure_path
                )
            )
            if not ok:
                return False, detail
        return True, "Prevention effectiveness review is intact and source verified."

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Prevention effectiveness decision is unreadable."
        expected = str(payload.get("decision_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("decision_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Prevention effectiveness decision SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("human_decision") is not True:
            return False, "Prevention effectiveness decision lacks human acknowledgement."
        decision = str(payload.get("decision") or "")
        if decision not in self.REVIEW_DECISIONS:
            return False, "Prevention effectiveness decision value is invalid."
        rationale = str(payload.get("rationale") or "")
        if len(rationale) < 20 or self._contains_private_material(rationale):
            return False, "Prevention effectiveness decision rationale is invalid."
        review_record = payload.get("review")
        ok, detail = self._verify_artifact_record(review_record, self.reviews_dir)
        if not ok:
            return False, detail
        review_path = self.reviews_dir / str(review_record.get("filename") or "")
        ok, detail = self.verify_review(review_path)
        if not ok:
            return False, detail
        review = self._read_json(review_path) or {}
        if str(payload.get("review_id") or "") != str(review.get("review_id") or ""):
            return False, "Prevention effectiveness decision review identity does not match."
        return True, "Prevention effectiveness decision is intact and human controlled."

    def export_snapshot(self, snapshot: PreventionEffectivenessSnapshot) -> Path:
        path = self.root / f"{snapshot.snapshot_id}-snapshot.json"
        payload = snapshot.to_dict()
        payload.update(
            {
                "schema_version": self.SCHEMA_VERSION,
                "automatic_completion": False,
                "automatic_risk_acceptance": False,
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

    def _verified_sources(
        self,
        baseline_path: Path,
        register_path: Path,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
        baseline_path = Path(baseline_path)
        register_path = Path(register_path)
        baseline_ok, baseline_detail = self.incident_prevention_service.verify_baseline(
            baseline_path
        )
        if not baseline_ok:
            return None, None, baseline_detail
        register_ok, register_detail = self.incident_prevention_service.verify_register(
            register_path
        )
        if not register_ok:
            return None, None, register_detail
        baseline = self._read_json(baseline_path)
        register = self._read_json(register_path)
        if not isinstance(baseline, dict) or not isinstance(register, dict):
            return None, None, "Phase 66 prevention records are unreadable."
        if str(baseline.get("baseline_id") or "") != str(register.get("baseline_id") or ""):
            return None, None, "Phase 66 baseline and register identities do not match."
        register_record = baseline.get("action_register")
        if not isinstance(register_record, Mapping):
            return None, None, "Phase 66 baseline is missing its action register."
        if str(register_record.get("filename") or "") != register_path.name:
            return None, None, "Selected action register does not belong to the baseline."
        if str(register_record.get("sha256") or "") != self._sha256(register_path):
            return None, None, "Selected action register changed after baseline creation."
        return baseline, register, "Phase 66 baseline and action register are intact."

    def _latest_attestations(
        self,
        *,
        baseline_id: str,
        register_id: str,
    ) -> tuple[dict[str, dict[str, Any]], int]:
        latest: dict[str, dict[str, Any]] = {}
        rejected = 0
        if not baseline_id or not register_id:
            return latest, rejected
        candidates = sorted(
            self.attestations_dir.glob(f"{baseline_id}-*.json"),
            key=lambda path: path.stat().st_mtime,
        )
        for path in candidates:
            ok, _detail = self.verify_attestation(path)
            if not ok:
                rejected += 1
                continue
            payload = self._read_json(path) or {}
            if str(payload.get("register_id") or "") != register_id:
                continue
            code = str(payload.get("action_code") or "")
            previous = latest.get(code)
            if previous is None or str(payload.get("created_at") or "") >= str(
                previous.get("created_at") or ""
            ):
                payload["_path"] = str(path)
                latest[code] = payload
        return latest, rejected

    def _action_states(
        self,
        *,
        baseline: Mapping[str, Any],
        register: Mapping[str, Any],
        attestations: Mapping[str, Mapping[str, Any]],
    ) -> tuple[PreventiveActionState, ...]:
        created = self._parse_datetime(str(register.get("created_at") or "")) or self._now()
        states: list[PreventiveActionState] = []
        actions = register.get("actions")
        if not isinstance(actions, list):
            return tuple()
        for item in actions:
            if not isinstance(item, Mapping):
                continue
            code = str(item.get("code") or "")
            target_days = self._safe_int(item.get("target_days"), 0)
            due = created + timedelta(days=max(0, target_days))
            attestation = attestations.get(code)
            status = str((attestation or {}).get("action_status") or item.get("status") or "open")
            overdue = status == "open" and self._now() > due
            states.append(
                PreventiveActionState(
                    code=code,
                    label=str(item.get("label") or ""),
                    owner=str((attestation or {}).get("owner") or item.get("owner") or ""),
                    target_days=target_days,
                    pattern_fingerprint=str(item.get("pattern_fingerprint") or ""),
                    due_at=due.isoformat(),
                    status=status,
                    attestation_id=str((attestation or {}).get("attestation_id") or ""),
                    attested_at=str((attestation or {}).get("created_at") or ""),
                    evidence_summary=str((attestation or {}).get("evidence_summary") or ""),
                    overdue=overdue,
                    automatic=False,
                )
            )
        return tuple(states)

    def _effectiveness_patterns(
        self,
        *,
        baseline: Mapping[str, Any],
        sources: Iterable[Any],
        actions: Iterable[PreventiveActionState],
        observation_days: int,
    ) -> tuple[PreventionEffectivenessPattern, ...]:
        source_groups: dict[str, list[Any]] = {}
        for source in sources:
            source_groups.setdefault(str(source.fingerprint), []).append(source)
        action_list = tuple(actions)
        results: list[PreventionEffectivenessPattern] = []
        patterns = baseline.get("patterns")
        if not isinstance(patterns, list):
            return tuple()
        for item in patterns:
            if not isinstance(item, Mapping):
                continue
            fingerprint = str(item.get("fingerprint") or "")
            if not self._FINGERPRINT_RE.fullmatch(fingerprint):
                continue
            post = source_groups.get(fingerprint, [])
            post_count = len(post)
            baseline_count = self._safe_int(item.get("occurrence_count"), 0)
            baseline_risk = self._safe_int(item.get("risk_score"), 0)
            relevant_actions = tuple(
                action
                for action in action_list
                if not action.pattern_fingerprint or action.pattern_fingerprint == fingerprint
            )
            completed = bool(relevant_actions) and all(
                action.status in {"completed", "risk_accepted"} for action in relevant_actions
            )
            if post_count:
                effectiveness = "ineffective"
                residual_risk = min(100, baseline_risk + min(20, post_count * 10))
            elif observation_days >= self.DEFAULT_OBSERVATION_DAYS and completed:
                effectiveness = "effective"
                residual_risk = max(0, baseline_risk - 25)
            else:
                effectiveness = "monitoring"
                residual_risk = baseline_risk
            latest = max((str(source.closed_at) for source in post), default="")
            results.append(
                PreventionEffectivenessPattern(
                    fingerprint=fingerprint,
                    component=str(item.get("component") or "general"),
                    baseline_occurrence_count=baseline_count,
                    post_baseline_occurrence_count=post_count,
                    baseline_risk_score=baseline_risk,
                    residual_risk_score=residual_risk,
                    new_recurrence=post_count > 0,
                    effectiveness=effectiveness,
                    latest_closed_at=latest,
                )
            )
        return tuple(
            sorted(
                results,
                key=lambda item: (
                    item.effectiveness != "ineffective",
                    -item.residual_risk_score,
                    item.fingerprint,
                ),
            )
        )

    def _decision_gate(
        self,
        snapshot: PreventionEffectivenessSnapshot,
        decision: str,
    ) -> str:
        if decision == "close_effective":
            if snapshot.observation_days < self.DEFAULT_OBSERVATION_DAYS:
                return "Closing the cycle requires at least 30 days of observation."
            if snapshot.recurrent_pattern_count or snapshot.ineffective_pattern_count:
                return "Closing the cycle is blocked while recurrence remains ineffective."
            if snapshot.open_action_count or snapshot.deferred_action_count or snapshot.overdue_action_count:
                return "Closing the cycle requires every preventive action to be resolved."
            if snapshot.accepted_risk_action_count:
                return "Use residual-risk acceptance instead of effective closure."
        if decision == "accept_residual_risk":
            if not snapshot.accepted_risk_action_count:
                return "Residual-risk acceptance requires at least one human risk attestation."
            if any(pattern.residual_risk_score >= 90 for pattern in snapshot.patterns):
                return "Residual risk at or above 90 requires escalation, not acceptance."
        if decision == "escalate_prevention" and not (
            snapshot.recurrent_pattern_count
            or snapshot.ineffective_pattern_count
            or snapshot.overdue_action_count
        ):
            return "Escalation requires recurrence, ineffectiveness or overdue preventive work."
        return ""

    def _register_action(
        self,
        register: Mapping[str, Any],
        action_code: str,
    ) -> Mapping[str, Any] | None:
        actions = register.get("actions")
        if not isinstance(actions, list):
            return None
        for action in actions:
            if isinstance(action, Mapping) and str(action.get("code") or "") == action_code:
                return action
        return None

    def _attestation_path(self, attestation_id: str) -> Path | None:
        candidates = tuple(self.attestations_dir.glob(f"*-{attestation_id}.json"))
        return candidates[0] if len(candidates) == 1 else None

    def _verify_common_contract(self, payload: Mapping[str, object]) -> tuple[bool, str]:
        if str(payload.get("version") or "") != self.version:
            return False, "Prevention effectiveness identity does not match the application."
        if str(payload.get("channel") or "") != "stable":
            return False, "Prevention effectiveness channel is not stable."
        if payload.get("private_data_included") is not False:
            return False, "Prevention effectiveness record includes private data."
        automatic_flags = (
            "automatic_completion",
            "automatic_risk_acceptance",
            "automatic_ticket_creation",
            "automatic_scheduling",
            "automatic_patch",
            "automatic_deploy",
            "automatic_rollback",
            "automatic_restart",
            "automatic_publish",
        )
        if any(payload.get(flag) is not False for flag in automatic_flags):
            return False, "Prevention effectiveness record enables an automatic operation."
        return True, "Prevention effectiveness safety contract is valid."

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> PreventionEffectivenessGate:
        return PreventionEffectivenessGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _path_record(path: Path) -> dict[str, object]:
        return {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": PreventionEffectivenessService._sha256(path),
        }

    def _verify_artifact_record(
        self,
        record: object,
        root: Path,
    ) -> tuple[bool, str]:
        if not isinstance(record, Mapping):
            return False, "Prevention effectiveness artifact record is invalid."
        filename = str(record.get("filename") or "")
        if not filename or Path(filename).name != filename:
            return False, "Prevention effectiveness artifact filename is unsafe."
        path = root / filename
        if not path.is_file():
            return False, f"Prevention effectiveness artifact is missing: {filename}"
        if self._safe_int(record.get("size_bytes"), -1) != path.stat().st_size:
            return False, f"Prevention effectiveness artifact size changed: {filename}"
        if str(record.get("sha256") or "") != self._sha256(path):
            return False, f"Prevention effectiveness artifact SHA-256 changed: {filename}"
        return True, f"Prevention effectiveness artifact is intact: {filename}"

    def _clean_text(
        self,
        value: str,
        *,
        minimum: int,
        maximum: int,
        allow_empty: bool = False,
    ) -> str | None:
        normalized = " ".join(str(value or "").split())
        if allow_empty and not normalized:
            return ""
        if not minimum <= len(normalized) <= maximum:
            return None
        if self._contains_private_material(normalized):
            return None
        return normalized

    def _contains_private_material(self, value: str) -> bool:
        return bool(self._SECRET_RE.search(value) or self._WINDOWS_PATH_RE.search(value))

    @staticmethod
    def _payload_digest(payload: Mapping[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
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
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _now(self) -> datetime:
        current = self._now_provider()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()
