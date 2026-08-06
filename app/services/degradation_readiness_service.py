from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.degradation_readiness import (
    DegradationCapacitySource,
    DegradationDrillRecord,
    DegradationPlanSource,
    DegradationReadinessGate,
    DegradationReadinessSnapshot,
)
from app.services.capacity_readiness_service import CapacityReadinessService


class DegradationReadinessService:
    """Build human-controlled degradation drill and recovery evidence.

    Phase 73 consumes intact Phase 72 capacity decisions, creates reviewed drill
    plans and records observed drill results. It never sheds load, pauses queues,
    changes provider routing, scales workers, deploys, rolls back or restarts.
    """

    SCHEMA_VERSION = 1
    SCENARIOS = (
        "provider_throttle",
        "queue_backlog",
        "worker_saturation",
        "memory_pressure",
    )
    DECISIONS = (
        "approve_readiness",
        "require_remediation",
        "hold_release",
    )
    MIN_REDUCTION_PERCENT = 5.0
    MAX_REDUCTION_PERCENT = 90.0
    MIN_RECOVERY_MINUTES = 1
    MAX_RECOVERY_MINUTES = 240
    MAX_QUEUE_LIMIT = 100000
    MAX_FAILED_REQUEST_LIMIT = 100000
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        capacity_readiness_service: CapacityReadinessService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.capacity_readiness_service = capacity_readiness_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "degradation-readiness"
        self.plans_dir = self.root / "plans"
        self.snapshots_dir = self.root / "snapshots"
        self.results_dir = self.root / "results"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.plans_dir,
            self.snapshots_dir,
            self.results_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_plan_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(self.plans_dir, "degradation-plan-*.json")

    def default_capacity_snapshot_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.capacity_readiness_service.snapshots_dir, "*.json"
        )

    def default_capacity_decision_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.capacity_readiness_service.decisions_dir, "*.json"
        )

    def default_capacity_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.capacity_readiness_service.audit_packs_dir, "*.zip"
        )

    def default_capacity_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.capacity_readiness_service.receipts_dir, "*.json"
        )

    def create_plan(
        self,
        *,
        scenario: str,
        target_load_reduction_percent: float,
        max_queue_depth: int,
        recovery_target_minutes: int,
        max_failed_requests: int,
        owner: str,
        notes: str = "",
        acknowledge: bool = False,
    ) -> DegradationPlanSource | dict[str, str]:
        scenario_value = str(scenario or "").strip().lower()
        owner_text = self._clean_text(owner, required=True, limit=160)
        notes_text = self._clean_text(notes, required=False, limit=1200)
        reduction = self._safe_float(target_load_reduction_percent)
        queue_limit = self._safe_int(max_queue_depth, -1)
        recovery_target = self._safe_int(recovery_target_minutes, -1)
        failed_limit = self._safe_int(max_failed_requests, -1)

        if scenario_value not in self.SCENARIOS:
            return self._blocked("Degradation scenario is unsupported.")
        if not self.MIN_REDUCTION_PERCENT <= reduction <= self.MAX_REDUCTION_PERCENT:
            return self._blocked("Target load reduction is outside the supported range.")
        if not 0 <= queue_limit <= self.MAX_QUEUE_LIMIT:
            return self._blocked("Queue-depth limit is invalid.")
        if not self.MIN_RECOVERY_MINUTES <= recovery_target <= self.MAX_RECOVERY_MINUTES:
            return self._blocked("Recovery target is invalid.")
        if not 0 <= failed_limit <= self.MAX_FAILED_REQUEST_LIMIT:
            return self._blocked("Failed-request limit is invalid.")
        if not owner_text:
            return self._blocked("Plan owner is required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            notes_text
        ):
            return self._blocked("Degradation plan contains private material.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the degradation plan and acknowledge local recording.",
            }

        plan_id = f"degradation-plan-{uuid.uuid4().hex[:12]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": plan_id,
            "created_at": self._now_iso(),
            "scenario": scenario_value,
            "target_load_reduction_percent": round(reduction, 4),
            "max_queue_depth": queue_limit,
            "recovery_target_minutes": recovery_target,
            "max_failed_requests": failed_limit,
            "owner": owner_text,
            "notes": notes_text,
            "human_reviewed": True,
            "steps": self._scenario_steps(scenario_value),
            "recovery_checks": self._recovery_checks(),
        }
        payload.update(self._safety_contract())
        payload["plan_sha256"] = self._payload_digest(payload)
        plan_path = self.plans_dir / f"{plan_id}.json"
        self._write_json(plan_path, payload)
        return self._plan_source(plan_path, payload)

    def snapshot(
        self,
        *,
        plan_paths: Iterable[Path] | None = None,
        capacity_snapshot_paths: Iterable[Path] | None = None,
        capacity_decision_paths: Iterable[Path] | None = None,
        capacity_pack_paths: Iterable[Path] | None = None,
        capacity_receipt_paths: Iterable[Path] | None = None,
    ) -> DegradationReadinessSnapshot:
        plans_selected = tuple(Path(path) for path in (plan_paths or ()))
        snapshots_selected = tuple(
            Path(path) for path in (capacity_snapshot_paths or ())
        )
        decisions_selected = tuple(
            Path(path) for path in (capacity_decision_paths or ())
        )
        packs_selected = tuple(Path(path) for path in (capacity_pack_paths or ()))
        receipts_selected = tuple(
            Path(path) for path in (capacity_receipt_paths or ())
        )

        gates: list[DegradationReadinessGate] = []
        runtime_ok = self.version == "1.0.0" and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_runtime",
                "Stable runtime",
                "pass" if runtime_ok else "block",
                "blocker",
                f"Runtime is {self.version} on {self.channel or 'unknown'} channel.",
                "Run this workflow from certified stable version 1.0.0.",
            )
        )

        plans, plan_rejected = self._plan_sources(plans_selected)
        plans_ok = bool(plans) and plan_rejected == 0
        gates.append(
            self._gate(
                "drill_plans",
                "Reviewed degradation plans",
                "pass" if plans_ok else "block",
                "blocker",
                (
                    f"Verified {len(plans)} reviewed plan(s)."
                    if plans_ok
                    else "At least one intact human-reviewed degradation plan is required."
                ),
                "Create or select intact Phase 73 degradation plans.",
            )
        )

        capacity_sources, capacity_rejected = self._capacity_sources(
            snapshots_selected,
            decisions_selected,
            packs_selected,
            receipts_selected,
        )
        capacity_counts_match = (
            len(snapshots_selected)
            == len(decisions_selected)
            == len(packs_selected)
            == len(receipts_selected)
        )
        capacity_ok = (
            bool(capacity_sources)
            and capacity_rejected == 0
            and capacity_counts_match
        )
        gates.append(
            self._gate(
                "capacity_evidence",
                "Phase 72 capacity evidence",
                "pass" if capacity_ok else "block",
                "blocker",
                (
                    f"Verified {len(capacity_sources)} capacity decision set(s)."
                    if capacity_ok
                    else "A one-to-one intact Phase 72 snapshot, decision, pack and receipt set is required."
                ),
                "Select matching intact Phase 72 artifacts.",
            )
        )

        required_scenarios = self._required_scenarios(capacity_sources)
        verified_scenarios = tuple(sorted({source.scenario for source in plans}))
        missing_scenarios = tuple(
            scenario
            for scenario in required_scenarios
            if scenario not in verified_scenarios
        )
        gates.append(
            self._gate(
                "scenario_coverage",
                "Degradation scenario coverage",
                "pass" if not missing_scenarios else "block",
                "blocker",
                (
                    "All capacity-derived scenarios have reviewed plans."
                    if not missing_scenarios
                    else "Missing reviewed plan(s): " + ", ".join(missing_scenarios)
                ),
                "Create reviewed plans for every required degradation scenario.",
            )
        )

        inherited_hold = any(
            source.release_gate == "hold" or source.decision == "hold_release"
            for source in capacity_sources
        )
        inherited_review = any(
            source.release_gate == "manual_review"
            or source.decision in {"scale_before_release", "prepare_degraded_mode"}
            for source in capacity_sources
        )
        gates.append(
            self._gate(
                "capacity_release_gate",
                "Inherited capacity release gate",
                "block" if inherited_hold else ("warn" if inherited_review else "pass"),
                "blocker" if inherited_hold else "warning",
                (
                    "Phase 72 requires release hold."
                    if inherited_hold
                    else (
                        "Phase 72 requires a reviewed capacity or degraded-mode action."
                        if inherited_review
                        else "Phase 72 permits release consideration."
                    )
                ),
                "Resolve the inherited Phase 72 release gate.",
            )
        )

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        if blockers:
            status = "blocked"
            release_gate = "hold"
            recommended_decision = "hold_release"
        elif warnings:
            status = "ready_with_warnings"
            release_gate = "manual_review"
            recommended_decision = "require_remediation"
        else:
            status = "ready"
            release_gate = "allow"
            recommended_decision = "approve_readiness"

        return DegradationReadinessSnapshot(
            snapshot_id=f"degradation-readiness-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            status=status,
            status_summary=self._summary(status, required_scenarios, missing_scenarios),
            release_gate=release_gate,
            recommended_decision=recommended_decision,
            selected_plan_count=len(plans_selected),
            verified_plan_count=len(plans),
            selected_capacity_count=max(
                len(snapshots_selected),
                len(decisions_selected),
                len(packs_selected),
                len(receipts_selected),
            ),
            verified_capacity_count=len(capacity_sources),
            rejected_source_count=plan_rejected + capacity_rejected,
            required_scenarios=required_scenarios,
            verified_scenarios=verified_scenarios,
            plans=plans,
            capacity_sources=capacity_sources,
            gates=tuple(gates),
        )

    def create_drill_result(
        self,
        snapshot: DegradationReadinessSnapshot,
        *,
        plan_path: Path,
        achieved_load_reduction_percent: float,
        observed_max_queue_depth: int,
        recovery_minutes: int,
        failed_requests: int,
        data_loss_count: int,
        health_checks_passed: bool,
        dedicated_tests_passed: bool,
        owner: str,
        statement: str,
        acknowledge: bool = False,
    ) -> DegradationDrillRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Blocked readiness snapshots cannot produce drill evidence.")
        plan_path = Path(plan_path)
        plan_ok, plan_detail = self.verify_plan(plan_path)
        plan_payload = self._read_json(plan_path)
        if not plan_ok or not isinstance(plan_payload, dict):
            return self._blocked(plan_detail)
        selected_plan = any(
            source.plan_path.resolve() == plan_path.resolve()
            and source.plan_sha256 == self._sha256(plan_path)
            for source in snapshot.plans
        )
        if not selected_plan:
            return self._blocked("The drill plan is not part of the reviewed snapshot.")
        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1200)
        if not owner_text or not statement_text:
            return self._blocked("Drill owner and statement are required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked("Drill result contains private material.")

        achieved = self._safe_float(achieved_load_reduction_percent, -1.0)
        queue_depth = self._safe_int(observed_max_queue_depth, -1)
        recovery = self._safe_int(recovery_minutes, -1)
        failed = self._safe_int(failed_requests, -1)
        data_loss = self._safe_int(data_loss_count, -1)
        if min(achieved, queue_depth, recovery, failed, data_loss) < 0:
            return self._blocked("Drill measurements are invalid.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review observed drill measurements and acknowledge local recording.",
            }

        target_reduction = self._safe_float(
            plan_payload.get("target_load_reduction_percent")
        )
        queue_limit = self._safe_int(plan_payload.get("max_queue_depth"))
        recovery_target = self._safe_int(plan_payload.get("recovery_target_minutes"))
        failed_limit = self._safe_int(plan_payload.get("max_failed_requests"))
        checks = {
            "load_reduction_met": achieved >= target_reduction,
            "queue_limit_met": queue_depth <= queue_limit,
            "recovery_target_met": recovery <= recovery_target,
            "failed_request_limit_met": failed <= failed_limit,
            "no_data_loss": data_loss == 0,
            "health_checks_passed": bool(health_checks_passed),
            "dedicated_tests_passed": bool(dedicated_tests_passed),
        }
        outcome_status = "verified" if all(checks.values()) else "withheld"
        decision = (
            "approve_readiness" if outcome_status == "verified" else "require_remediation"
        )

        snapshot_path = self.export_snapshot(snapshot)
        drill_id = f"degradation-drill-{uuid.uuid4().hex[:12]}"
        result_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "created_at": self._now_iso(),
            "scenario": str(plan_payload.get("scenario") or ""),
            "outcome_status": outcome_status,
            "decision": decision,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "plan_filename": plan_path.name,
            "plan_sha256": self._sha256(plan_path),
            "achieved_load_reduction_percent": round(achieved, 4),
            "observed_max_queue_depth": queue_depth,
            "recovery_minutes": recovery,
            "failed_requests": failed,
            "data_loss_count": data_loss,
            "checks": checks,
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
        }
        result_payload.update(self._safety_contract())
        result_payload["result_sha256"] = self._payload_digest(result_payload)
        result_path = self.results_dir / f"{drill_id}-result.json"
        self._write_json(result_path, result_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "created_at": self._now_iso(),
            "status": outcome_status,
            "decision": decision,
            "result_filename": result_path.name,
            "result_sha256": self._sha256(result_path),
            "plan_filename": plan_path.name,
            "plan_sha256": self._sha256(plan_path),
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "human_decision_required": True,
        }
        attestation_payload.update(self._safety_contract())
        attestation_payload["attestation_sha256"] = self._payload_digest(
            attestation_payload
        )
        attestation_path = self.attestations_dir / f"{drill_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)
        audit_pack_path, receipt_path = self._create_audit_pack(
            drill_id=drill_id,
            snapshot=snapshot,
            snapshot_path=snapshot_path,
            plan_path=plan_path,
            result_path=result_path,
            attestation_path=attestation_path,
        )
        return DegradationDrillRecord(
            drill_id=drill_id,
            created_at=str(result_payload["created_at"]),
            scenario=str(result_payload["scenario"]),
            outcome_status=outcome_status,
            snapshot_path=snapshot_path,
            plan_path=plan_path,
            result_path=result_path,
            attestation_path=attestation_path,
            audit_pack_path=audit_pack_path,
            receipt_path=receipt_path,
        )

    def verify_plan(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Degradation plan is unreadable."
        expected = str(payload.get("plan_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("plan_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Degradation plan SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Degradation plan safety contract changed."
        if not payload.get("human_reviewed"):
            return False, "Degradation plan was not human reviewed."
        if str(payload.get("scenario") or "") not in self.SCENARIOS:
            return False, "Degradation scenario is unsupported."
        for field_name in ("owner", "notes"):
            if self._contains_private_material(str(payload.get(field_name) or "")):
                return False, "Degradation plan contains private material."
        return True, "Degradation plan is intact and privacy-safe."

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Degradation snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Degradation snapshot SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Degradation snapshot safety contract changed."
        return True, "Degradation snapshot is intact."

    def verify_result(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Degradation result is unreadable."
        expected = str(payload.get("result_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("result_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Degradation result SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Degradation result safety contract changed."
        for field_name in ("owner", "statement"):
            if self._contains_private_material(str(payload.get(field_name) or "")):
                return False, "Degradation result contains private material."
        plan_path = self.plans_dir / str(payload.get("plan_filename") or "")
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not plan_path.is_file() or self._sha256(plan_path) != str(
            payload.get("plan_sha256") or ""
        ):
            return False, "Degradation plan custody changed."
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != str(
            payload.get("snapshot_sha256") or ""
        ):
            return False, "Degradation snapshot custody changed."
        plan_ok, detail = self.verify_plan(plan_path)
        if not plan_ok:
            return False, detail
        snapshot_ok, detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return False, detail
        checks = payload.get("checks")
        if not isinstance(checks, dict) or not checks:
            return False, "Degradation result has no measured checks."
        expected_status = "verified" if all(bool(value) for value in checks.values()) else "withheld"
        if payload.get("outcome_status") != expected_status:
            return False, "Degradation outcome conflicts with measured checks."
        return True, "Degradation result is intact and source custody verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Degradation attestation is unreadable."
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Degradation attestation SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Degradation attestation safety contract changed."
        result_path = self.results_dir / str(payload.get("result_filename") or "")
        if not result_path.is_file() or self._sha256(result_path) != str(
            payload.get("result_sha256") or ""
        ):
            return False, "Degradation result custody changed."
        result_ok, detail = self.verify_result(result_path)
        if not result_ok:
            return False, detail
        result_payload = self._read_json(result_path) or {}
        if payload.get("status") != result_payload.get("outcome_status"):
            return False, "Degradation attestation status conflicts with result."
        return True, "Degradation attestation is intact and result verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Degradation audit-pack receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Degradation receipt SHA-256 does not match."
        if not self._verify_common_contract(receipt):
            return False, "Degradation receipt safety contract changed."
        if not pack_path.is_file():
            return False, "Degradation audit pack is missing."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Degradation audit-pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "Degradation audit-pack size changed."
        if receipt.get("pack_sha256") != self._sha256(pack_path):
            return False, "Degradation audit-pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path) as archive:
                names = archive.namelist()
                if "manifest.json" not in names:
                    return False, "Degradation audit pack has no manifest."
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Degradation audit pack contains an unsafe path."
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    return False, "Degradation audit-pack manifest is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "Degradation manifest SHA-256 does not match."
                if not self._verify_common_contract(manifest):
                    return False, "Degradation manifest safety contract changed."
                entries = manifest.get("entries")
                if not isinstance(entries, list) or not entries:
                    return False, "Degradation manifest has no entries."
                for entry in entries:
                    if not isinstance(entry, dict):
                        return False, "Degradation manifest entry is invalid."
                    name = str(entry.get("path") or "")
                    if name not in names:
                        return False, f"Degradation pack entry is missing: {name}"
                    data = archive.read(name)
                    if len(data) != self._safe_int(entry.get("size_bytes"), -1):
                        return False, f"Degradation pack entry size changed: {name}"
                    if hashlib.sha256(data).hexdigest() != str(entry.get("sha256") or ""):
                        return False, f"Degradation pack entry hash changed: {name}"
        except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            return False, f"Degradation audit pack is unreadable: {exc}"
        return True, "Degradation audit pack and receipt are intact."

    def export_snapshot(self, snapshot: DegradationReadinessSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        return path

    def _plan_sources(
        self, paths: Iterable[Path]
    ) -> tuple[tuple[DegradationPlanSource, ...], int]:
        sources: list[DegradationPlanSource] = []
        rejected = 0
        seen_ids: set[str] = set()
        for path in paths:
            path = Path(path)
            ok, _detail = self.verify_plan(path)
            payload = self._read_json(path)
            if not ok or not isinstance(payload, dict):
                rejected += 1
                continue
            plan_id = str(payload.get("plan_id") or "")
            if not plan_id or plan_id in seen_ids:
                rejected += 1
                continue
            seen_ids.add(plan_id)
            sources.append(self._plan_source(path, payload))
        sources.sort(key=lambda source: (source.scenario, source.plan_id))
        return tuple(sources), rejected

    def _plan_source(
        self, path: Path, payload: Mapping[str, object]
    ) -> DegradationPlanSource:
        return DegradationPlanSource(
            plan_id=str(payload.get("plan_id") or ""),
            scenario=str(payload.get("scenario") or ""),
            target_load_reduction_percent=self._safe_float(
                payload.get("target_load_reduction_percent")
            ),
            max_queue_depth=self._safe_int(payload.get("max_queue_depth")),
            recovery_target_minutes=self._safe_int(
                payload.get("recovery_target_minutes")
            ),
            max_failed_requests=self._safe_int(payload.get("max_failed_requests")),
            plan_path=Path(path),
            plan_sha256=self._sha256(Path(path)),
        )

    def _capacity_sources(
        self,
        snapshot_paths: Iterable[Path],
        decision_paths: Iterable[Path],
        pack_paths: Iterable[Path],
        receipt_paths: Iterable[Path],
    ) -> tuple[tuple[DegradationCapacitySource, ...], int]:
        snapshots = self._index_json(snapshot_paths, "snapshot_id")
        decisions = self._index_json(decision_paths, "decision_id")
        decision_payloads = {
            key: self._read_json(path) or {} for key, path in decisions.items()
        }
        decision_to_snapshot = {
            key: str(payload.get("snapshot_filename") or "")
            for key, payload in decision_payloads.items()
        }
        snapshots_by_name = {path.name: path for path in snapshots.values()}
        packs = {self._pack_decision_id(path): Path(path) for path in pack_paths}
        receipts = self._index_json(receipt_paths, "decision_id")
        all_ids = set(decisions) | set(packs) | set(receipts)
        sources: list[DegradationCapacitySource] = []
        rejected = 0
        for decision_id in sorted(all_ids):
            decision_path = decisions.get(decision_id)
            pack_path = packs.get(decision_id)
            receipt_path = receipts.get(decision_id)
            snapshot_path = snapshots_by_name.get(
                decision_to_snapshot.get(decision_id, "")
            )
            if None in (decision_path, pack_path, receipt_path, snapshot_path):
                rejected += 1
                continue
            assert decision_path is not None
            assert pack_path is not None
            assert receipt_path is not None
            assert snapshot_path is not None
            snapshot_ok, _ = self.capacity_readiness_service.verify_snapshot(
                snapshot_path
            )
            decision_ok, _ = self.capacity_readiness_service.verify_decision(
                decision_path
            )
            pack_ok, _ = self.capacity_readiness_service.verify_audit_pack(
                pack_path, receipt_path
            )
            if not snapshot_ok or not decision_ok or not pack_ok:
                rejected += 1
                continue
            snapshot_payload = self._read_json(snapshot_path) or {}
            decision_payload = self._read_json(decision_path) or {}
            sources.append(
                DegradationCapacitySource(
                    decision_id=decision_id,
                    decision=str(decision_payload.get("decision") or ""),
                    release_gate=str(
                        decision_payload.get("calculated_release_gate")
                        or snapshot_payload.get("release_gate")
                        or ""
                    ),
                    snapshot_status=str(snapshot_payload.get("status") or ""),
                    snapshot_path=snapshot_path,
                    decision_path=decision_path,
                    audit_pack_path=pack_path,
                    receipt_path=receipt_path,
                    snapshot_sha256=self._sha256(snapshot_path),
                    decision_sha256=self._sha256(decision_path),
                    audit_pack_sha256=self._sha256(pack_path),
                    receipt_sha256=self._sha256(receipt_path),
                )
            )
        return tuple(sources), rejected

    def _required_scenarios(
        self, sources: Iterable[DegradationCapacitySource]
    ) -> tuple[str, ...]:
        required: set[str] = set()
        for source in sources:
            payload = self._read_json(source.snapshot_path) or {}
            if self._safe_float(payload.get("max_provider_throttle_percent")) >= 5.0:
                required.add("provider_throttle")
            if self._safe_int(payload.get("max_queue_depth")) >= 100:
                required.add("queue_backlog")
            if self._safe_float(payload.get("max_worker_utilization_percent")) >= 80.0:
                required.add("worker_saturation")
            if self._safe_float(payload.get("max_memory_utilization_percent")) >= 80.0:
                required.add("memory_pressure")
            if source.decision == "prepare_degraded_mode":
                required.update(self.SCENARIOS)
        return tuple(sorted(required))

    def _create_audit_pack(
        self,
        *,
        drill_id: str,
        snapshot: DegradationReadinessSnapshot,
        snapshot_path: Path,
        plan_path: Path,
        result_path: Path,
        attestation_path: Path,
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "degradation/snapshot.json": snapshot_path.read_bytes(),
            "degradation/plan.json": plan_path.read_bytes(),
            "degradation/result.json": result_path.read_bytes(),
            "degradation/attestation.json": attestation_path.read_bytes(),
        }
        for source in snapshot.capacity_sources:
            entries[f"capacity/{source.snapshot_path.name}"] = source.snapshot_path.read_bytes()
            entries[f"capacity/{source.decision_path.name}"] = source.decision_path.read_bytes()
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
            "drill_id": drill_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        pack_path = self.audit_packs_dir / f"{drill_id}-audit-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "drill_id": drill_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{drill_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "automatic_load_shedding": False,
            "automatic_queue_pause": False,
            "automatic_provider_failover": False,
            "automatic_worker_scaling": False,
            "automatic_restart": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_publish": False,
            "automatic_release_decision": False,
        }

    @classmethod
    def _verify_common_contract(cls, payload: Mapping[str, object]) -> bool:
        return all(payload.get(key) is False for key in cls._safety_contract())

    @classmethod
    def _scenario_steps(cls, scenario: str) -> list[str]:
        shared = [
            "Confirm isolated or staging-only execution.",
            "Record the starting health and queue baseline.",
            "Apply the reviewed manual simulation step.",
            "Observe load, queue, errors and recovery metrics.",
            "Manually restore normal operation and verify health.",
        ]
        labels = {
            "provider_throttle": "Simulate reviewed provider throttling without changing production routing.",
            "queue_backlog": "Simulate a bounded queue backlog without pausing production queues.",
            "worker_saturation": "Simulate bounded worker saturation without automatic scaling.",
            "memory_pressure": "Simulate bounded memory pressure without restarting production.",
        }
        return [labels[scenario], *shared]

    @staticmethod
    def _recovery_checks() -> list[str]:
        return [
            "Queue returns below the reviewed limit.",
            "Provider and worker health checks pass.",
            "No data loss is observed.",
            "Dedicated regression tests pass.",
            "Recovery completes within the reviewed target.",
        ]

    @staticmethod
    def _summary(
        status: str,
        required_scenarios: tuple[str, ...],
        missing_scenarios: tuple[str, ...],
    ) -> str:
        if status == "blocked":
            if missing_scenarios:
                return "Degradation readiness is blocked by missing scenario coverage."
            return "Degradation readiness is blocked by invalid or held evidence."
        if status == "ready_with_warnings":
            return "Reviewed drill execution is required before release approval."
        if required_scenarios:
            return "All capacity-derived degradation scenarios are covered."
        return "Reviewed degradation evidence is ready for controlled validation."

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> DegradationReadinessGate:
        return DegradationReadinessGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _pack_decision_id(path: Path) -> str:
        suffix = "-audit-pack.zip"
        return path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        pure = PurePosixPath(name)
        return bool(name) and not pure.is_absolute() and ".." not in pure.parts

    @staticmethod
    def _sorted_files(directory: Path, pattern: str) -> tuple[Path, ...]:
        return tuple(sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime))

    def _index_json(
        self, paths: Iterable[Path], key_name: str
    ) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for path in paths:
            path = Path(path)
            payload = self._read_json(path)
            key = str((payload or {}).get(key_name) or "")
            if key and key not in result:
                result[key] = path
        return result

    def _clean_text(self, value: str, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").strip().split())[:limit]
        return text if text or not required else ""

    def _contains_private_material(self, value: str) -> bool:
        return bool(self._WINDOWS_PATH_RE.search(value) or self._SECRET_RE.search(value))

    @classmethod
    def _payload_digest(cls, payload: Mapping[str, object]) -> str:
        return hashlib.sha256(cls._json_bytes(payload)).hexdigest()

    @staticmethod
    def _json_bytes(payload: Mapping[str, object]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

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
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if number == number else default

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()

    @staticmethod
    def _blocked(detail: str) -> dict[str, str]:
        return {"status": "blocked", "detail": detail}
