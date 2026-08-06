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
from app.models.recovery_replay import (
    RecoveryReplayDegradationSource,
    RecoveryReplayGate,
    RecoveryReplayPlanSource,
    RecoveryReplayRecord,
    RecoveryReplaySnapshot,
)
from app.services.degradation_readiness_service import DegradationReadinessService


class RecoveryReplayService:
    """Build reviewed queue replay and duplicate-prevention evidence.

    Phase 74 consumes verified Phase 73 degradation drill evidence and records
    human-observed recovery replay results. It never resumes queues, retries
    jobs, changes provider routing, deletes artifacts or performs billing work.
    """

    SCHEMA_VERSION = 1
    MAX_JOB_COUNT = 1_000_000
    MAX_DUPLICATE_LIMIT = 100_000
    MAX_ARTIFACT_LIMIT = 100_000
    MAX_RECOVERY_MINUTES = 24 * 60
    MAX_COST_VARIANCE_PERCENT = 100.0
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        degradation_readiness_service: DegradationReadinessService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.degradation_readiness_service = degradation_readiness_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "recovery-replay"
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
        return self._sorted_files(self.plans_dir, "recovery-replay-plan-*.json")

    def default_degradation_result_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.degradation_readiness_service.results_dir,
            "*-result.json",
        )

    def default_degradation_attestation_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.degradation_readiness_service.attestations_dir,
            "*-attestation.json",
        )

    def default_degradation_pack_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.degradation_readiness_service.audit_packs_dir,
            "*-audit-pack.zip",
        )

    def default_degradation_receipt_paths(self) -> tuple[Path, ...]:
        return self._sorted_files(
            self.degradation_readiness_service.receipts_dir,
            "*-receipt.json",
        )

    def create_plan(
        self,
        *,
        expected_job_count: int,
        recovery_target_minutes: int,
        max_duplicate_requests: int,
        max_duplicate_outputs: int,
        max_orphan_artifacts: int,
        max_manifest_mismatches: int,
        max_cost_variance_percent: float,
        owner: str,
        notes: str = "",
        acknowledge: bool = False,
    ) -> RecoveryReplayPlanSource | dict[str, str]:
        expected = self._safe_int(expected_job_count, -1)
        recovery = self._safe_int(recovery_target_minutes, -1)
        duplicate_requests = self._safe_int(max_duplicate_requests, -1)
        duplicate_outputs = self._safe_int(max_duplicate_outputs, -1)
        orphan_artifacts = self._safe_int(max_orphan_artifacts, -1)
        manifest_mismatches = self._safe_int(max_manifest_mismatches, -1)
        cost_variance = self._safe_float(max_cost_variance_percent, -1.0)
        owner_text = self._clean_text(owner, required=True, limit=160)
        notes_text = self._clean_text(notes, required=False, limit=1200)

        if not 1 <= expected <= self.MAX_JOB_COUNT:
            return self._blocked("Expected job count is outside the supported range.")
        if not 1 <= recovery <= self.MAX_RECOVERY_MINUTES:
            return self._blocked("Recovery target is outside the supported range.")
        for label, value, maximum in (
            ("duplicate-request", duplicate_requests, self.MAX_DUPLICATE_LIMIT),
            ("duplicate-output", duplicate_outputs, self.MAX_DUPLICATE_LIMIT),
            ("orphan-artifact", orphan_artifacts, self.MAX_ARTIFACT_LIMIT),
            ("manifest-mismatch", manifest_mismatches, self.MAX_ARTIFACT_LIMIT),
        ):
            if not 0 <= value <= maximum:
                return self._blocked(f"The {label} limit is invalid.")
        if not 0.0 <= cost_variance <= self.MAX_COST_VARIANCE_PERCENT:
            return self._blocked("Cost-variance limit is invalid.")
        if not owner_text:
            return self._blocked("Plan owner is required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            notes_text
        ):
            return self._blocked("Recovery replay plan contains private material.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the replay limits and acknowledge local recording.",
            }

        plan_id = f"recovery-replay-plan-{uuid.uuid4().hex[:12]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": plan_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "expected_job_count": expected,
            "recovery_target_minutes": recovery,
            "max_duplicate_requests": duplicate_requests,
            "max_duplicate_outputs": duplicate_outputs,
            "max_orphan_artifacts": orphan_artifacts,
            "max_manifest_mismatches": manifest_mismatches,
            "max_cost_variance_percent": round(cost_variance, 4),
            "owner": owner_text,
            "notes": notes_text,
            "human_reviewed": True,
            "required_checks": self._required_checks(),
        }
        payload.update(self._safety_contract())
        payload["plan_sha256"] = self._payload_digest(payload)
        path = self.plans_dir / f"{plan_id}.json"
        self._write_json(path, payload)
        return self._plan_source(path, payload)

    def verify_plan(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Recovery replay plan is unreadable."
        expected = str(payload.pop("plan_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Recovery replay plan SHA-256 changed."
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            return False, "Recovery replay plan schema is unsupported."
        if payload.get("human_reviewed") is not True:
            return False, "Recovery replay plan is not human reviewed."
        if not self._verify_common_contract(payload):
            return False, "Recovery replay plan safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Recovery replay plan contains private material."
        return True, "Recovery replay plan verified."

    def snapshot(
        self,
        *,
        plan_paths: Iterable[Path] | None = None,
        degradation_result_paths: Iterable[Path] | None = None,
        degradation_attestation_paths: Iterable[Path] | None = None,
        degradation_pack_paths: Iterable[Path] | None = None,
        degradation_receipt_paths: Iterable[Path] | None = None,
    ) -> RecoveryReplaySnapshot:
        plans_selected = tuple(Path(path) for path in (plan_paths or self.default_plan_paths()))
        results_selected = tuple(
            Path(path)
            for path in (
                degradation_result_paths or self.default_degradation_result_paths()
            )
        )
        attestations_selected = tuple(
            Path(path)
            for path in (
                degradation_attestation_paths
                or self.default_degradation_attestation_paths()
            )
        )
        packs_selected = tuple(
            Path(path)
            for path in (degradation_pack_paths or self.default_degradation_pack_paths())
        )
        receipts_selected = tuple(
            Path(path)
            for path in (
                degradation_receipt_paths or self.default_degradation_receipt_paths()
            )
        )

        plans: list[RecoveryReplayPlanSource] = []
        plan_rejected = 0
        for path in plans_selected:
            ok, _detail = self.verify_plan(path)
            payload = self._read_json(path)
            if not ok or payload is None:
                plan_rejected += 1
                continue
            plans.append(self._plan_source(path, payload))

        degradation_sources, degradation_rejected = self._collect_degradation_sources(
            results_selected,
            attestations_selected,
            packs_selected,
            receipts_selected,
        )
        gates: list[RecoveryReplayGate] = []
        plan_ok = bool(plans) and len(plans) == len(plans_selected)
        gates.append(
            self._gate(
                "reviewed_plan",
                "Reviewed recovery replay plan",
                "pass" if plan_ok else "block",
                "blocker",
                (
                    f"Verified {len(plans)} reviewed replay plan(s)."
                    if plan_ok
                    else "At least one intact reviewed replay plan is required."
                ),
                "Create or select an intact human-reviewed replay plan.",
            )
        )

        source_counts_match = (
            len(results_selected)
            == len(attestations_selected)
            == len(packs_selected)
            == len(receipts_selected)
        )
        source_ok = (
            bool(degradation_sources)
            and source_counts_match
            and degradation_rejected == 0
            and len(degradation_sources) == len(results_selected)
        )
        gates.append(
            self._gate(
                "degradation_evidence",
                "Phase 73 degradation evidence",
                "pass" if source_ok else "block",
                "blocker",
                (
                    f"Verified {len(degradation_sources)} degradation drill set(s)."
                    if source_ok
                    else "A one-to-one intact Phase 73 result, attestation, pack and receipt set is required."
                ),
                "Select matching intact Phase 73 artifacts.",
            )
        )

        verified_only = bool(degradation_sources) and all(
            source.outcome_status == "verified" for source in degradation_sources
        )
        gates.append(
            self._gate(
                "verified_recovery_source",
                "Verified degradation recovery",
                "pass" if verified_only else "block",
                "blocker",
                (
                    "Every selected degradation drill completed as verified."
                    if verified_only
                    else "Withheld or incomplete degradation drills cannot authorize replay evidence."
                ),
                "Complete remediation and record a verified Phase 73 drill.",
            )
        )

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        if blockers:
            status = "blocked"
            release_gate = "hold"
            recommended_decision = "hold_recovery_replay"
        elif warnings:
            status = "ready_with_warnings"
            release_gate = "manual_review"
            recommended_decision = "review_recovery_replay"
        else:
            status = "ready"
            release_gate = "allow"
            recommended_decision = "approve_recovery_replay"

        return RecoveryReplaySnapshot(
            snapshot_id=f"recovery-replay-snapshot-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            status=status,
            status_summary=self._summary(status),
            release_gate=release_gate,
            recommended_decision=recommended_decision,
            selected_plan_count=len(plans_selected),
            verified_plan_count=len(plans),
            selected_degradation_count=max(
                len(results_selected),
                len(attestations_selected),
                len(packs_selected),
                len(receipts_selected),
            ),
            verified_degradation_count=len(degradation_sources),
            rejected_source_count=plan_rejected + degradation_rejected,
            plans=tuple(plans),
            degradation_sources=degradation_sources,
            gates=tuple(gates),
        )

    def export_snapshot(self, snapshot: RecoveryReplaySnapshot) -> Path:
        payload = snapshot.to_dict()
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        return path

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Recovery replay snapshot is unreadable."
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Recovery replay snapshot SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Recovery replay snapshot safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Recovery replay snapshot contains private material."
        return True, "Recovery replay snapshot verified."

    def create_replay_result(
        self,
        snapshot: RecoveryReplaySnapshot,
        *,
        plan_path: Path,
        attempted_jobs: int,
        resumed_jobs: int,
        completed_jobs: int,
        duplicate_api_requests: int,
        duplicate_outputs: int,
        orphan_artifacts: int,
        manifest_mismatches: int,
        cost_variance_percent: float,
        recovery_minutes: int,
        receipt_chain_verified: bool,
        output_checksums_verified: bool,
        dedicated_tests_passed: bool,
        owner: str,
        statement: str,
        acknowledge: bool = False,
    ) -> RecoveryReplayRecord | dict[str, str]:
        if snapshot.blocker_count:
            return self._blocked("Blocked replay snapshots cannot produce evidence.")
        plan_path = Path(plan_path)
        plan_ok, plan_detail = self.verify_plan(plan_path)
        plan_payload = self._read_json(plan_path)
        if not plan_ok or plan_payload is None:
            return self._blocked(plan_detail)
        selected = any(
            source.plan_path.resolve() == plan_path.resolve()
            and source.plan_sha256 == self._sha256(plan_path)
            for source in snapshot.plans
        )
        if not selected:
            return self._blocked("The replay plan is not part of the reviewed snapshot.")

        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1200)
        if not owner_text or not statement_text:
            return self._blocked("Replay reviewer and statement are required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked("Recovery replay result contains private material.")

        measurements = {
            "attempted_jobs": self._safe_int(attempted_jobs, -1),
            "resumed_jobs": self._safe_int(resumed_jobs, -1),
            "completed_jobs": self._safe_int(completed_jobs, -1),
            "duplicate_api_requests": self._safe_int(duplicate_api_requests, -1),
            "duplicate_outputs": self._safe_int(duplicate_outputs, -1),
            "orphan_artifacts": self._safe_int(orphan_artifacts, -1),
            "manifest_mismatches": self._safe_int(manifest_mismatches, -1),
            "recovery_minutes": self._safe_int(recovery_minutes, -1),
        }
        cost_variance = self._safe_float(cost_variance_percent, -1.0)
        if any(value < 0 for value in measurements.values()) or cost_variance < 0:
            return self._blocked("Recovery replay measurements are invalid.")
        if measurements["resumed_jobs"] > measurements["attempted_jobs"]:
            return self._blocked("Resumed jobs cannot exceed attempted jobs.")
        if measurements["completed_jobs"] > measurements["attempted_jobs"]:
            return self._blocked("Completed jobs cannot exceed attempted jobs.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review observed replay measurements and acknowledge local recording.",
            }

        expected_jobs = self._safe_int(plan_payload.get("expected_job_count"))
        checks = {
            "expected_job_count_met": measurements["attempted_jobs"] == expected_jobs,
            "resume_count_valid": measurements["resumed_jobs"]
            <= measurements["attempted_jobs"],
            "all_jobs_completed": measurements["completed_jobs"]
            == measurements["attempted_jobs"],
            "duplicate_request_limit_met": measurements["duplicate_api_requests"]
            <= self._safe_int(plan_payload.get("max_duplicate_requests")),
            "duplicate_output_limit_met": measurements["duplicate_outputs"]
            <= self._safe_int(plan_payload.get("max_duplicate_outputs")),
            "orphan_artifact_limit_met": measurements["orphan_artifacts"]
            <= self._safe_int(plan_payload.get("max_orphan_artifacts")),
            "manifest_mismatch_limit_met": measurements["manifest_mismatches"]
            <= self._safe_int(plan_payload.get("max_manifest_mismatches")),
            "cost_variance_limit_met": cost_variance
            <= self._safe_float(plan_payload.get("max_cost_variance_percent")),
            "recovery_target_met": measurements["recovery_minutes"]
            <= self._safe_int(plan_payload.get("recovery_target_minutes")),
            "receipt_chain_verified": bool(receipt_chain_verified),
            "output_checksums_verified": bool(output_checksums_verified),
            "dedicated_tests_passed": bool(dedicated_tests_passed),
        }
        outcome_status = "verified" if all(checks.values()) else "withheld"
        decision = (
            "approve_recovery_replay"
            if outcome_status == "verified"
            else "require_replay_remediation"
        )

        snapshot_path = self.export_snapshot(snapshot)
        replay_id = f"recovery-replay-{uuid.uuid4().hex[:12]}"
        result_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "replay_id": replay_id,
            "created_at": self._now_iso(),
            "outcome_status": outcome_status,
            "decision": decision,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "plan_filename": plan_path.name,
            "plan_sha256": self._sha256(plan_path),
            **measurements,
            "cost_variance_percent": round(cost_variance, 4),
            "checks": checks,
            "owner": owner_text,
            "statement": statement_text,
            "human_reviewed": True,
        }
        result_payload.update(self._safety_contract())
        result_payload["result_sha256"] = self._payload_digest(result_payload)
        result_path = self.results_dir / f"{replay_id}-result.json"
        self._write_json(result_path, result_payload)

        attestation_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "replay_id": replay_id,
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
        attestation_path = self.attestations_dir / f"{replay_id}-attestation.json"
        self._write_json(attestation_path, attestation_payload)

        pack_path, receipt_path = self._create_audit_pack(
            replay_id=replay_id,
            snapshot=snapshot,
            snapshot_path=snapshot_path,
            plan_path=plan_path,
            result_path=result_path,
            attestation_path=attestation_path,
        )
        return RecoveryReplayRecord(
            replay_id=replay_id,
            created_at=str(result_payload["created_at"]),
            outcome_status=outcome_status,
            snapshot_path=snapshot_path,
            plan_path=plan_path,
            result_path=result_path,
            attestation_path=attestation_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_result(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Recovery replay result is unreadable."
        expected = str(payload.pop("result_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Recovery replay result SHA-256 changed."
        if payload.get("outcome_status") not in {"verified", "withheld"}:
            return False, "Recovery replay outcome is invalid."
        if payload.get("human_reviewed") is not True:
            return False, "Recovery replay result is not human reviewed."
        if not self._verify_common_contract(payload):
            return False, "Recovery replay result safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Recovery replay result contains private material."
        return True, "Recovery replay result verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(path)
        if payload is None:
            return False, "Recovery replay attestation is unreadable."
        expected = str(payload.pop("attestation_sha256", ""))
        if not expected or expected != self._payload_digest(payload):
            return False, "Recovery replay attestation SHA-256 changed."
        if not self._verify_common_contract(payload):
            return False, "Recovery replay attestation safety contract changed."
        result_path = self.results_dir / str(payload.get("result_filename") or "")
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        plan_path = self.plans_dir / str(payload.get("plan_filename") or "")
        for label, source_path, expected_hash in (
            ("result", result_path, payload.get("result_sha256")),
            ("snapshot", snapshot_path, payload.get("snapshot_sha256")),
            ("plan", plan_path, payload.get("plan_sha256")),
        ):
            if not source_path.is_file() or self._sha256(source_path) != expected_hash:
                return False, f"Recovery replay {label} evidence changed."
        result_payload = self._read_json(result_path) or {}
        if result_payload.get("replay_id") != payload.get("replay_id"):
            return False, "Recovery replay attestation identifier changed."
        return True, "Recovery replay attestation verified."

    def verify_audit_pack(
        self, pack_path: Path, receipt_path: Path
    ) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt_path = Path(receipt_path)
        receipt = self._read_json(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Recovery replay audit pack or receipt is missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if not expected or expected != self._payload_digest(receipt):
            return False, "Recovery replay receipt SHA-256 changed."
        if not self._verify_common_contract(receipt):
            return False, "Recovery replay receipt safety contract changed."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Recovery replay pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "Recovery replay pack size changed."
        if receipt.get("pack_sha256") != self._sha256(pack_path):
            return False, "Recovery replay pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path) as archive:
                names = archive.namelist()
                if not names or any(not self._safe_archive_name(name) for name in names):
                    return False, "Recovery replay pack contains an unsafe path."
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    return False, "Recovery replay manifest is invalid."
                manifest_digest = str(manifest.pop("manifest_sha256", ""))
                if manifest_digest != self._payload_digest(manifest):
                    return False, "Recovery replay manifest SHA-256 changed."
                if not self._verify_common_contract(manifest):
                    return False, "Recovery replay manifest safety contract changed."
                for entry in manifest.get("entries", []):
                    if not isinstance(entry, dict):
                        return False, "Recovery replay manifest entry is invalid."
                    name = str(entry.get("path") or "")
                    data = archive.read(name)
                    if len(data) != self._safe_int(entry.get("size_bytes"), -1):
                        return False, "Recovery replay manifest size changed."
                    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                        return False, "Recovery replay manifest entry SHA-256 changed."
        except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
            return False, "Recovery replay audit pack is unreadable."
        return True, "Recovery replay audit pack verified."

    def _collect_degradation_sources(
        self,
        result_paths: tuple[Path, ...],
        attestation_paths: tuple[Path, ...],
        pack_paths: tuple[Path, ...],
        receipt_paths: tuple[Path, ...],
    ) -> tuple[tuple[RecoveryReplayDegradationSource, ...], int]:
        results = self._index_json(result_paths, "drill_id")
        attestations = self._index_json(attestation_paths, "drill_id")
        receipts = self._index_json(receipt_paths, "drill_id")
        packs = {self._pack_drill_id(path): path for path in pack_paths}
        all_ids = set(results) | set(attestations) | set(receipts) | set(packs)
        rejected = 0
        sources: list[RecoveryReplayDegradationSource] = []
        for drill_id in sorted(all_ids):
            result_path = results.get(drill_id)
            attestation_path = attestations.get(drill_id)
            pack_path = packs.get(drill_id)
            receipt_path = receipts.get(drill_id)
            if not all((result_path, attestation_path, pack_path, receipt_path)):
                rejected += 1
                continue
            assert result_path is not None
            assert attestation_path is not None
            assert pack_path is not None
            assert receipt_path is not None
            checks = (
                self.degradation_readiness_service.verify_result(result_path)[0],
                self.degradation_readiness_service.verify_attestation(
                    attestation_path
                )[0],
                self.degradation_readiness_service.verify_audit_pack(
                    pack_path, receipt_path
                )[0],
            )
            result_payload = self._read_json(result_path) or {}
            attestation_payload = self._read_json(attestation_path) or {}
            if not all(checks):
                rejected += 1
                continue
            if attestation_payload.get("drill_id") != drill_id:
                rejected += 1
                continue
            sources.append(
                RecoveryReplayDegradationSource(
                    drill_id=drill_id,
                    scenario=str(result_payload.get("scenario") or ""),
                    outcome_status=str(result_payload.get("outcome_status") or ""),
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

    def _create_audit_pack(
        self,
        *,
        replay_id: str,
        snapshot: RecoveryReplaySnapshot,
        snapshot_path: Path,
        plan_path: Path,
        result_path: Path,
        attestation_path: Path,
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "recovery-replay/snapshot.json": snapshot_path.read_bytes(),
            "recovery-replay/plan.json": plan_path.read_bytes(),
            "recovery-replay/result.json": result_path.read_bytes(),
            "recovery-replay/attestation.json": attestation_path.read_bytes(),
        }
        for source in snapshot.degradation_sources:
            entries[f"degradation/{source.result_path.name}"] = source.result_path.read_bytes()
            entries[
                f"degradation/{source.attestation_path.name}"
            ] = source.attestation_path.read_bytes()
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
            "replay_id": replay_id,
            "created_at": self._now_iso(),
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        pack_path = self.audit_packs_dir / f"{replay_id}-audit-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "replay_id": replay_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{replay_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _plan_source(
        self, path: Path, payload: Mapping[str, object]
    ) -> RecoveryReplayPlanSource:
        return RecoveryReplayPlanSource(
            plan_id=str(payload.get("plan_id") or ""),
            expected_job_count=self._safe_int(payload.get("expected_job_count")),
            recovery_target_minutes=self._safe_int(
                payload.get("recovery_target_minutes")
            ),
            max_duplicate_requests=self._safe_int(
                payload.get("max_duplicate_requests")
            ),
            max_duplicate_outputs=self._safe_int(
                payload.get("max_duplicate_outputs")
            ),
            max_orphan_artifacts=self._safe_int(payload.get("max_orphan_artifacts")),
            max_manifest_mismatches=self._safe_int(
                payload.get("max_manifest_mismatches")
            ),
            max_cost_variance_percent=self._safe_float(
                payload.get("max_cost_variance_percent")
            ),
            plan_path=path,
            plan_sha256=self._sha256(path),
        )

    @classmethod
    def _required_checks(cls) -> list[str]:
        return [
            "Every expected job is represented in the replay attempt.",
            "All attempted jobs complete within the reviewed target.",
            "Duplicate API requests and outputs remain within reviewed limits.",
            "Output manifests and artifact custody remain intact.",
            "Billing variance remains within the reviewed limit.",
            "Execution receipt continuity and output checksums are verified.",
            "Dedicated recovery regression tests pass.",
        ]

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "automatic_queue_resume": False,
            "automatic_job_retry": False,
            "automatic_provider_switch": False,
            "automatic_artifact_delete": False,
            "automatic_audio_regeneration": False,
            "automatic_billing_action": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "automatic_release_decision": False,
        }

    @classmethod
    def _verify_common_contract(cls, payload: Mapping[str, object]) -> bool:
        return all(payload.get(key) is False for key in cls._safety_contract())

    @staticmethod
    def _summary(status: str) -> str:
        if status == "blocked":
            return "Recovery replay readiness is blocked by missing or invalid evidence."
        if status == "ready_with_warnings":
            return "Recovery replay requires additional human review."
        return "Verified degradation recovery and replay limits are ready for observation."

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> RecoveryReplayGate:
        return RecoveryReplayGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _pack_drill_id(path: Path) -> str:
        suffix = "-audit-pack.zip"
        return path.name[: -len(suffix)] if path.name.endswith(suffix) else path.stem

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        pure = PurePosixPath(name)
        return bool(name) and not pure.is_absolute() and ".." not in pure.parts

    @staticmethod
    def _sorted_files(directory: Path, pattern: str) -> tuple[Path, ...]:
        return tuple(sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime))

    def _index_json(self, paths: Iterable[Path], key_name: str) -> dict[str, Path]:
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

    def _contains_private_payload(self, payload: Mapping[str, object]) -> bool:
        return self._contains_private_material(json.dumps(payload, ensure_ascii=False))

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
            return float(value)
        except (TypeError, ValueError):
            return default

    def _now_iso(self) -> str:
        return self._now_provider().astimezone(timezone.utc).isoformat()

    @staticmethod
    def _blocked(detail: str) -> dict[str, str]:
        return {"status": "blocked", "detail": detail}
