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
from app.models.service_level_objectives import (
    ServiceLevelContinuitySource,
    ServiceLevelDecisionRecord,
    ServiceLevelGate,
    ServiceLevelObservationSource,
    ServiceLevelObjectivesSnapshot,
)
from app.services.service_continuity_service import ServiceContinuityService


class ServiceLevelObjectivesService:
    """Create privacy-safe SLO, error-budget and release-safety evidence.

    Phase 71 consumes human-reviewed operational observations and intact Phase 70
    continuity evidence. It calculates availability, success rate, latency and
    error-budget burn, then records a human release-safety decision. It never
    deploys, rolls back, restarts, publishes or changes production automatically.
    """

    SCHEMA_VERSION = 1
    DEFAULT_WINDOW_DAYS = 30
    MIN_WINDOW_DAYS = 1
    MAX_WINDOW_DAYS = 365
    DEFAULT_AVAILABILITY_TARGET = 99.9
    MIN_PERCENT_TARGET = 90.0
    MAX_PERCENT_TARGET = 100.0
    DEFAULT_SUCCESS_TARGET = 99.0
    DEFAULT_P95_LATENCY_TARGET_MS = 2000
    MIN_LATENCY_TARGET_MS = 1
    MAX_LATENCY_TARGET_MS = 600000
    ERROR_BUDGET_WARNING_RATE = 0.8
    DECISIONS = ("allow", "manual_review", "hold")
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        service_continuity_service: ServiceContinuityService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.service_continuity_service = service_continuity_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "service-level-objectives"
        self.observations_dir = self.root / "observations"
        self.snapshots_dir = self.root / "snapshots"
        self.decisions_dir = self.root / "decisions"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        for path in (
            self.root,
            self.observations_dir,
            self.snapshots_dir,
            self.decisions_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def default_observation_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.observations_dir.glob("slo-observation-*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_continuity_result_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_continuity_service.results_dir.glob("*-result.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_continuity_attestation_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_continuity_service.attestations_dir.glob(
                    "*-attestation.json"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_continuity_pack_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_continuity_service.audit_packs_dir.glob(
                    "*-audit-pack.zip"
                ),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_continuity_receipt_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_continuity_service.receipts_dir.glob("*-receipt.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def create_observation(
        self,
        *,
        window_start: str,
        window_end: str,
        total_operations: int,
        successful_operations: int,
        failed_operations: int,
        unavailable_minutes: int,
        p95_latency_ms: int,
        owner: str,
        notes: str = "",
        acknowledge: bool = False,
    ) -> ServiceLevelObservationSource | dict[str, str]:
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Explicit human acknowledgement is required.",
                "path": "",
            }
        owner_text = self._clean_text(owner, required=True, limit=120)
        notes_text = self._clean_text(notes, required=False, limit=2000)
        if not owner_text:
            return self._blocked("A human observation owner is required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            notes_text
        ):
            return self._blocked(
                "Observation text contains a credential or local absolute path."
            )
        start = self._parse_datetime(window_start)
        end = self._parse_datetime(window_end)
        if start is None or end is None or end <= start:
            return self._blocked("Observation window must contain valid ordered timestamps.")
        window_minutes = max(1, int((end - start).total_seconds() // 60))
        total = self._safe_int(total_operations, -1)
        successful = self._safe_int(successful_operations, -1)
        failed = self._safe_int(failed_operations, -1)
        unavailable = self._safe_int(unavailable_minutes, -1)
        latency = self._safe_int(p95_latency_ms, -1)
        if min(total, successful, failed, unavailable, latency) < 0:
            return self._blocked("Observation metrics cannot be negative.")
        if successful + failed != total:
            return self._blocked(
                "Successful and failed operations must equal total operations."
            )
        if unavailable > window_minutes:
            return self._blocked(
                "Unavailable minutes cannot exceed the observation window."
            )
        observation_id = (
            f"slo-observation-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "observation_id": observation_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "window_minutes": window_minutes,
            "total_operations": total,
            "successful_operations": successful,
            "failed_operations": failed,
            "unavailable_minutes": unavailable,
            "p95_latency_ms": latency,
            "owner": owner_text,
            "notes": notes_text,
            "human_observation_reviewed": True,
            **self._safety_contract(),
        }
        payload["observation_sha256"] = self._payload_digest(payload)
        path = self.observations_dir / f"{observation_id}.json"
        self._write_json(path, payload)
        ok, detail = self.verify_observation(path)
        if not ok:
            path.unlink(missing_ok=True)
            return self._blocked(detail)
        return ServiceLevelObservationSource(
            observation_id=observation_id,
            window_start=start.isoformat(),
            window_end=end.isoformat(),
            window_minutes=window_minutes,
            total_operations=total,
            successful_operations=successful,
            failed_operations=failed,
            unavailable_minutes=unavailable,
            p95_latency_ms=latency,
            observation_path=path,
            observation_sha256=self._sha256(path),
        )

    def snapshot(
        self,
        *,
        observation_paths: Iterable[Path] = (),
        continuity_result_paths: Iterable[Path] = (),
        continuity_attestation_paths: Iterable[Path] = (),
        continuity_pack_paths: Iterable[Path] = (),
        continuity_receipt_paths: Iterable[Path] = (),
        window_days: int = DEFAULT_WINDOW_DAYS,
        availability_target_percent: float = DEFAULT_AVAILABILITY_TARGET,
        success_target_percent: float = DEFAULT_SUCCESS_TARGET,
        p95_latency_target_ms: int = DEFAULT_P95_LATENCY_TARGET_MS,
    ) -> ServiceLevelObjectivesSnapshot:
        observations = tuple(dict.fromkeys(Path(path) for path in observation_paths))
        results = tuple(
            dict.fromkeys(Path(path) for path in continuity_result_paths)
        )
        attestations = tuple(
            dict.fromkeys(Path(path) for path in continuity_attestation_paths)
        )
        packs = tuple(dict.fromkeys(Path(path) for path in continuity_pack_paths))
        receipts = tuple(
            dict.fromkeys(Path(path) for path in continuity_receipt_paths)
        )
        if not observations:
            observations = self.default_observation_paths()
        if not results:
            results = self.default_continuity_result_paths()
        if not attestations:
            attestations = self.default_continuity_attestation_paths()
        if not packs:
            packs = self.default_continuity_pack_paths()
        if not receipts:
            receipts = self.default_continuity_receipt_paths()

        days = self._bounded_int(
            window_days,
            self.MIN_WINDOW_DAYS,
            self.MAX_WINDOW_DAYS,
            self.DEFAULT_WINDOW_DAYS,
        )
        availability_target = self._bounded_float(
            availability_target_percent,
            self.MIN_PERCENT_TARGET,
            self.MAX_PERCENT_TARGET,
            self.DEFAULT_AVAILABILITY_TARGET,
        )
        success_target = self._bounded_float(
            success_target_percent,
            self.MIN_PERCENT_TARGET,
            self.MAX_PERCENT_TARGET,
            self.DEFAULT_SUCCESS_TARGET,
        )
        latency_target = self._bounded_int(
            p95_latency_target_ms,
            self.MIN_LATENCY_TARGET_MS,
            self.MAX_LATENCY_TARGET_MS,
            self.DEFAULT_P95_LATENCY_TARGET_MS,
        )
        gates: list[ServiceLevelGate] = []

        identity_ok = self.version == app.__version__ and self.channel == "stable"
        gates.append(
            self._gate(
                "stable_identity",
                "Stable application identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Stable identity verified: {self.version} ({self.channel})."
                    if identity_ok
                    else "SLO governance must run from the certified stable build."
                ),
                "Run the workflow from the certified stable application.",
            )
        )

        policy_ok = (
            self.MIN_WINDOW_DAYS <= int(window_days) <= self.MAX_WINDOW_DAYS
            and self.MIN_PERCENT_TARGET
            <= float(availability_target_percent)
            <= self.MAX_PERCENT_TARGET
            and self.MIN_PERCENT_TARGET
            <= float(success_target_percent)
            <= self.MAX_PERCENT_TARGET
            and self.MIN_LATENCY_TARGET_MS
            <= int(p95_latency_target_ms)
            <= self.MAX_LATENCY_TARGET_MS
        )
        gates.append(
            self._gate(
                "slo_policy",
                "Service-level objective policy",
                "pass" if policy_ok else "block",
                "blocker",
                (
                    f"Window {days} day(s), availability {availability_target:.3f}%, "
                    f"success {success_target:.3f}%, p95 latency {latency_target} ms."
                ),
                "Use supported SLO policy values.",
            )
        )

        observation_sources, observation_rejected, overlap_count = (
            self._observation_sources(observations)
        )
        observation_ok = bool(observation_sources) and observation_rejected == 0
        if overlap_count:
            observation_ok = False
        gates.append(
            self._gate(
                "operational_observations",
                "Operational observation custody",
                "pass" if observation_ok else "block",
                "blocker",
                (
                    f"Verified {len(observation_sources)} non-overlapping observation(s)."
                    if observation_ok
                    else (
                        "At least one intact, non-overlapping observation is required; "
                        f"rejected {observation_rejected}, overlaps {overlap_count}."
                    )
                ),
                "Create or select intact human-reviewed operational observations.",
            )
        )

        continuity_sources, continuity_rejected = self._continuity_sources(
            results,
            attestations,
            packs,
            receipts,
        )
        continuity_counts_match = (
            len(results) == len(attestations) == len(packs) == len(receipts)
        )
        continuity_ok = (
            bool(continuity_sources)
            and continuity_rejected == 0
            and continuity_counts_match
        )
        gates.append(
            self._gate(
                "continuity_evidence",
                "Phase 70 continuity evidence",
                "pass" if continuity_ok else "block",
                "blocker",
                (
                    f"Verified {len(continuity_sources)} passed continuity drill(s)."
                    if continuity_ok
                    else (
                        "A one-to-one intact result, attestation, audit pack and receipt "
                        f"set is required; selected {len(results)}/{len(attestations)}/"
                        f"{len(packs)}/{len(receipts)}, rejected {continuity_rejected}."
                    )
                ),
                "Select matching passed Phase 70 continuity artifacts.",
            )
        )

        observed_minutes = sum(source.window_minutes for source in observation_sources)
        expected_minutes = days * 1440
        total_operations = sum(source.total_operations for source in observation_sources)
        successful_operations = sum(
            source.successful_operations for source in observation_sources
        )
        failed_operations = sum(
            source.failed_operations for source in observation_sources
        )
        unavailable_minutes = sum(
            source.unavailable_minutes for source in observation_sources
        )
        p95_latency = max(
            (source.p95_latency_ms for source in observation_sources),
            default=0,
        )
        availability = (
            max(0.0, 100.0 * (observed_minutes - unavailable_minutes) / observed_minutes)
            if observed_minutes
            else 0.0
        )
        success = (
            100.0 * successful_operations / total_operations
            if total_operations
            else 0.0
        )
        error_budget = observed_minutes * (100.0 - availability_target) / 100.0
        consumed = float(unavailable_minutes)
        remaining = error_budget - consumed
        if error_budget > 0:
            burn_rate = consumed / error_budget
        else:
            burn_rate = 0.0 if consumed == 0 else float("inf")

        coverage_ok = observed_minutes >= expected_minutes
        gates.append(
            self._gate(
                "window_coverage",
                "SLO window coverage",
                "pass" if coverage_ok else "warn",
                "warning",
                f"Observed {observed_minutes} of {expected_minutes} required minute(s).",
                "Add verified observations covering the complete SLO window.",
            )
        )
        gates.append(
            self._metric_gate(
                "availability_objective",
                "Availability objective",
                availability >= availability_target,
                f"Measured {availability:.4f}% against {availability_target:.4f}%.",
                "Hold release decisions until availability recovers.",
            )
        )
        gates.append(
            self._metric_gate(
                "success_objective",
                "Operation success objective",
                success >= success_target,
                f"Measured {success:.4f}% against {success_target:.4f}%.",
                "Investigate failed operations before release approval.",
            )
        )
        gates.append(
            self._metric_gate(
                "latency_objective",
                "P95 latency objective",
                p95_latency <= latency_target,
                f"Measured {p95_latency} ms against {latency_target} ms.",
                "Resolve latency regressions before release approval.",
            )
        )
        if burn_rate > 1.0:
            budget_status = "block"
        elif burn_rate >= self.ERROR_BUDGET_WARNING_RATE:
            budget_status = "warn"
        else:
            budget_status = "pass"
        gates.append(
            self._gate(
                "error_budget",
                "Availability error budget",
                budget_status,
                "blocker" if budget_status == "block" else "warning",
                (
                    f"Consumed {consumed:.2f} of {error_budget:.2f} minute(s); "
                    f"burn rate {self._display_rate(burn_rate)}."
                ),
                "Pause risky changes when the error budget is exhausted or nearly spent.",
            )
        )

        blocker_count = sum(gate.status == "block" for gate in gates)
        warning_count = sum(gate.status == "warn" for gate in gates)
        if blocker_count:
            status = "blocked"
            release_gate = "hold"
        elif warning_count:
            status = "ready_with_warnings"
            release_gate = "manual_review"
        else:
            status = "ready"
            release_gate = "allow"
        snapshot_id = (
            f"slo-{self._now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        )
        return ServiceLevelObjectivesSnapshot(
            snapshot_id=snapshot_id,
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            window_days=days,
            availability_target_percent=round(availability_target, 4),
            success_target_percent=round(success_target, 4),
            p95_latency_target_ms=latency_target,
            status=status,
            status_summary=self._summary(status, burn_rate),
            release_gate=release_gate,
            observed_window_minutes=observed_minutes,
            expected_window_minutes=expected_minutes,
            total_operations=total_operations,
            successful_operations=successful_operations,
            failed_operations=failed_operations,
            unavailable_minutes=unavailable_minutes,
            availability_percent=round(availability, 6),
            success_percent=round(success, 6),
            p95_latency_ms=p95_latency,
            error_budget_minutes=round(error_budget, 6),
            error_budget_consumed_minutes=round(consumed, 6),
            error_budget_remaining_minutes=round(remaining, 6),
            error_budget_burn_rate=round(burn_rate, 6),
            selected_observation_count=len(observations),
            verified_observation_count=len(observation_sources),
            selected_continuity_count=max(
                len(results), len(attestations), len(packs), len(receipts)
            ),
            verified_continuity_count=len(continuity_sources),
            rejected_source_count=observation_rejected + continuity_rejected,
            observations=observation_sources,
            continuity_sources=continuity_sources,
            gates=tuple(gates),
        )

    def create_release_decision(
        self,
        snapshot: ServiceLevelObjectivesSnapshot,
        *,
        decision: str,
        owner: str,
        statement: str,
        acknowledge: bool = False,
    ) -> ServiceLevelDecisionRecord | dict[str, str]:
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Explicit human acknowledgement is required.",
                "path": "",
            }
        normalized_decision = str(decision or "").strip().lower()
        if normalized_decision not in self.DECISIONS:
            return self._blocked("Release-safety decision is invalid.")
        if normalized_decision == "allow" and snapshot.release_gate != "allow":
            return self._blocked("Unqualified allow is not permitted by the SLO gates.")
        if normalized_decision == "manual_review" and snapshot.blocker_count:
            return self._blocked("Manual review cannot override blocking SLO evidence.")
        owner_text = self._clean_text(owner, required=True, limit=120)
        statement_text = self._clean_text(statement, required=True, limit=2000)
        if not owner_text or not statement_text:
            return self._blocked("A human owner and decision statement are required.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked(
                "Decision text contains a credential or local absolute path."
            )
        decision_id = (
            f"slo-decision-{self._now().strftime('%Y%m%d-%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )
        snapshot_payload = snapshot.to_dict()
        snapshot_payload["schema_version"] = self.SCHEMA_VERSION
        snapshot_payload.update(self._safety_contract())
        snapshot_payload["snapshot_sha256"] = self._payload_digest(snapshot_payload)
        snapshot_path = self.snapshots_dir / f"{decision_id}-snapshot.json"
        self._write_json(snapshot_path, snapshot_payload)
        decision_payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "decision_id": decision_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "status": "verified",
            "decision": normalized_decision,
            "calculated_release_gate": snapshot.release_gate,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "owner": owner_text,
            "statement": statement_text,
            "human_decision_completed": True,
            **self._safety_contract(),
        }
        decision_payload["decision_sha256"] = self._payload_digest(decision_payload)
        decision_path = self.decisions_dir / f"{decision_id}.json"
        self._write_json(decision_path, decision_payload)
        pack_path, receipt_path = self._create_audit_pack(
            decision_id=decision_id,
            snapshot_path=snapshot_path,
            decision_path=decision_path,
            snapshot=snapshot,
        )
        decision_ok, decision_detail = self.verify_decision(decision_path)
        pack_ok, pack_detail = self.verify_audit_pack(pack_path, receipt_path)
        if not decision_ok or not pack_ok:
            for path in (snapshot_path, decision_path, pack_path, receipt_path):
                path.unlink(missing_ok=True)
            return self._blocked(decision_detail if not decision_ok else pack_detail)
        return ServiceLevelDecisionRecord(
            decision_id=decision_id,
            created_at=str(decision_payload["created_at"]),
            decision=normalized_decision,
            snapshot_path=snapshot_path,
            decision_path=decision_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_observation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "SLO observation is unreadable."
        expected = str(payload.get("observation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("observation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "SLO observation SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get(
            "human_observation_reviewed"
        ) is not True:
            return False, "SLO observation lacks human review."
        start = self._parse_datetime(str(payload.get("window_start") or ""))
        end = self._parse_datetime(str(payload.get("window_end") or ""))
        if start is None or end is None or end <= start:
            return False, "SLO observation window is invalid."
        window_minutes = max(1, int((end - start).total_seconds() // 60))
        if self._safe_int(payload.get("window_minutes"), -1) != window_minutes:
            return False, "SLO observation window duration changed."
        total = self._safe_int(payload.get("total_operations"), -1)
        successful = self._safe_int(payload.get("successful_operations"), -1)
        failed = self._safe_int(payload.get("failed_operations"), -1)
        unavailable = self._safe_int(payload.get("unavailable_minutes"), -1)
        latency = self._safe_int(payload.get("p95_latency_ms"), -1)
        if min(total, successful, failed, unavailable, latency) < 0:
            return False, "SLO observation metrics are invalid."
        if successful + failed != total or unavailable > window_minutes:
            return False, "SLO observation metrics are inconsistent."
        for field in ("owner", "notes"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "SLO observation contains private material."
        return True, "SLO observation is intact and human reviewed."

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "SLO snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "SLO snapshot SHA-256 does not match."
        return self._verify_common_contract(payload)

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "SLO decision is unreadable."
        expected = str(payload.get("decision_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("decision_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "SLO decision SHA-256 does not match."
        ok, detail = self._verify_common_contract(payload)
        if not ok:
            return False, detail
        if payload.get("status") != "verified" or payload.get(
            "human_decision_completed"
        ) is not True:
            return False, "SLO decision lacks human review."
        decision = str(payload.get("decision") or "")
        calculated = str(payload.get("calculated_release_gate") or "")
        if decision not in self.DECISIONS or calculated not in self.DECISIONS:
            return False, "SLO decision value is invalid."
        if decision == "allow" and calculated != "allow":
            return False, "SLO decision improperly overrides the calculated gate."
        if decision == "manual_review" and calculated == "hold":
            return False, "SLO decision improperly overrides a hold gate."
        for field in ("owner", "statement"):
            if self._contains_private_material(str(payload.get(field) or "")):
                return False, "SLO decision contains private material."
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != str(
            payload.get("snapshot_sha256") or ""
        ):
            return False, "SLO snapshot custody changed."
        snapshot_ok, snapshot_detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return False, snapshot_detail
        snapshot = self._read_json(snapshot_path) or {}
        if str(snapshot.get("release_gate") or "") != calculated:
            return False, "SLO calculated gate changed."
        return True, "SLO decision is intact and snapshot verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "SLO audit-pack receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "SLO receipt SHA-256 does not match."
        if not pack_path.is_file():
            return False, "SLO audit pack is missing."
        if str(receipt.get("pack_filename") or "") != pack_path.name:
            return False, "SLO audit-pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "SLO audit-pack size changed."
        if str(receipt.get("pack_sha256") or "") != self._sha256(pack_path):
            return False, "SLO audit-pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path) as archive:
                names = archive.namelist()
                if "manifest.json" not in names:
                    return False, "SLO audit pack has no manifest."
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    return False, "SLO audit-pack manifest is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "SLO audit-pack manifest SHA-256 does not match."
                entries = manifest.get("entries")
                if not isinstance(entries, list) or not entries:
                    return False, "SLO audit-pack manifest has no entries."
                for item in entries:
                    if not isinstance(item, Mapping):
                        return False, "SLO audit-pack entry is invalid."
                    name = str(item.get("path") or "")
                    if not self._safe_archive_name(name) or name not in names:
                        return False, "SLO audit-pack entry path is unsafe or missing."
                    data = archive.read(name)
                    if len(data) != self._safe_int(item.get("size_bytes"), -1):
                        return False, "SLO audit-pack entry size changed."
                    if hashlib.sha256(data).hexdigest() != str(item.get("sha256") or ""):
                        return False, "SLO audit-pack entry SHA-256 changed."
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
            return False, "SLO audit pack is unreadable."
        return True, "SLO audit pack and receipt are intact."

    def export_snapshot(self, snapshot: ServiceLevelObjectivesSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        return path

    def _observation_sources(
        self,
        paths: Iterable[Path],
    ) -> tuple[tuple[ServiceLevelObservationSource, ...], int, int]:
        sources: list[ServiceLevelObservationSource] = []
        rejected = 0
        seen_ids: set[str] = set()
        for path in paths:
            ok, _detail = self.verify_observation(path)
            payload = self._read_json(path)
            if not ok or not isinstance(payload, dict):
                rejected += 1
                continue
            observation_id = str(payload.get("observation_id") or "")
            if not observation_id or observation_id in seen_ids:
                rejected += 1
                continue
            seen_ids.add(observation_id)
            sources.append(
                ServiceLevelObservationSource(
                    observation_id=observation_id,
                    window_start=str(payload.get("window_start") or ""),
                    window_end=str(payload.get("window_end") or ""),
                    window_minutes=self._safe_int(payload.get("window_minutes")),
                    total_operations=self._safe_int(payload.get("total_operations")),
                    successful_operations=self._safe_int(
                        payload.get("successful_operations")
                    ),
                    failed_operations=self._safe_int(payload.get("failed_operations")),
                    unavailable_minutes=self._safe_int(
                        payload.get("unavailable_minutes")
                    ),
                    p95_latency_ms=self._safe_int(payload.get("p95_latency_ms")),
                    observation_path=Path(path),
                    observation_sha256=self._sha256(Path(path)),
                )
            )
        sources.sort(key=lambda source: source.window_start)
        overlaps = 0
        for previous, current in zip(sources, sources[1:]):
            previous_end = self._parse_datetime(previous.window_end)
            current_start = self._parse_datetime(current.window_start)
            if previous_end is not None and current_start is not None:
                overlaps += current_start < previous_end
        return tuple(sources), rejected, overlaps

    def _continuity_sources(
        self,
        result_paths: Iterable[Path],
        attestation_paths: Iterable[Path],
        pack_paths: Iterable[Path],
        receipt_paths: Iterable[Path],
    ) -> tuple[tuple[ServiceLevelContinuitySource, ...], int]:
        results = self._index_json(result_paths, "drill_id")
        attestations = self._index_json(attestation_paths, "drill_id")
        packs = {self._pack_drill_id(path): Path(path) for path in pack_paths}
        receipts = self._index_json(receipt_paths, "drill_id")
        all_ids = set(results) | set(attestations) | set(packs) | set(receipts)
        sources: list[ServiceLevelContinuitySource] = []
        rejected = 0
        for drill_id in sorted(all_ids):
            result_path = results.get(drill_id)
            attestation_path = attestations.get(drill_id)
            pack_path = packs.get(drill_id)
            receipt_path = receipts.get(drill_id)
            if None in (result_path, attestation_path, pack_path, receipt_path):
                rejected += 1
                continue
            assert result_path is not None
            assert attestation_path is not None
            assert pack_path is not None
            assert receipt_path is not None
            result_ok, _ = self.service_continuity_service.verify_result(result_path)
            attestation_ok, _ = self.service_continuity_service.verify_attestation(
                attestation_path
            )
            pack_ok, _ = self.service_continuity_service.verify_audit_pack(
                pack_path,
                receipt_path,
            )
            result_payload = self._read_json(result_path) or {}
            attestation_payload = self._read_json(attestation_path) or {}
            outcome = str(result_payload.get("outcome") or "")
            attestation_status = str(attestation_payload.get("status") or "")
            if (
                not result_ok
                or not attestation_ok
                or not pack_ok
                or outcome != "passed"
                or attestation_status != "verified"
            ):
                rejected += 1
                continue
            sources.append(
                ServiceLevelContinuitySource(
                    drill_id=drill_id,
                    outcome=outcome,
                    attestation_status=attestation_status,
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
        decision_id: str,
        snapshot_path: Path,
        decision_path: Path,
        snapshot: ServiceLevelObjectivesSnapshot,
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "slo/snapshot.json": snapshot_path.read_bytes(),
            "slo/decision.json": decision_path.read_bytes(),
        }
        for source in snapshot.observations:
            entries[f"observations/{source.observation_path.name}"] = (
                source.observation_path.read_bytes()
            )
        for source in snapshot.continuity_sources:
            entries[f"continuity/{source.result_path.name}"] = (
                source.result_path.read_bytes()
            )
            entries[f"continuity/{source.attestation_path.name}"] = (
                source.attestation_path.read_bytes()
            )
            entries[f"continuity/{source.audit_pack_path.name}"] = (
                source.audit_pack_path.read_bytes()
            )
            entries[f"continuity/{source.receipt_path.name}"] = (
                source.receipt_path.read_bytes()
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
            "decision_id": decision_id,
            "created_at": self._now_iso(),
            "entry_count": len(manifest_entries),
            "entries": manifest_entries,
            **self._safety_contract(),
        }
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        entries["manifest.json"] = self._json_bytes(manifest)
        pack_path = self.audit_packs_dir / f"{decision_id}-audit-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "decision_id": decision_id,
            "created_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
            "entry_count": len(entries),
            **self._safety_contract(),
        }
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{decision_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    def _verify_common_contract(
        self,
        payload: Mapping[str, object],
    ) -> tuple[bool, str]:
        if self._safe_int(payload.get("schema_version"), -1) != self.SCHEMA_VERSION:
            return False, "SLO evidence schema is unsupported."
        if str(payload.get("version") or "") != self.version:
            return False, "SLO evidence version changed."
        if str(payload.get("channel") or "") != self.channel:
            return False, "SLO evidence channel changed."
        contract = self._safety_contract()
        for key, expected in contract.items():
            if payload.get(key) != expected:
                return False, "SLO safety contract changed."
        return True, "SLO safety contract is intact."

    @staticmethod
    def _safety_contract() -> dict[str, object]:
        return {
            "private_data_included": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_publish": False,
            "automatic_release_decision": False,
        }

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> ServiceLevelGate:
        return ServiceLevelGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    def _metric_gate(
        self,
        code: str,
        label: str,
        passed: bool,
        detail: str,
        remediation: str,
    ) -> ServiceLevelGate:
        return self._gate(
            code,
            label,
            "pass" if passed else "block",
            "blocker",
            detail,
            remediation,
        )

    @staticmethod
    def _summary(status: str, burn_rate: float) -> str:
        rate = ServiceLevelObjectivesService._display_rate(burn_rate)
        if status == "ready":
            return f"SLO objectives and continuity evidence are ready; burn rate {rate}."
        if status == "ready_with_warnings":
            return f"SLO evidence requires human review; burn rate {rate}."
        return f"SLO release safety is blocked; burn rate {rate}."

    @staticmethod
    def _display_rate(value: float) -> str:
        return "infinite" if value == float("inf") else f"{value:.3f}"

    def _index_json(
        self,
        paths: Iterable[Path],
        key: str,
    ) -> dict[str, Path]:
        indexed: dict[str, Path] = {}
        duplicates: set[str] = set()
        for path in paths:
            payload = self._read_json(Path(path))
            identifier = str((payload or {}).get(key) or "")
            if not identifier:
                continue
            if identifier in indexed:
                duplicates.add(identifier)
            indexed[identifier] = Path(path)
        for identifier in duplicates:
            indexed.pop(identifier, None)
        return indexed

    @staticmethod
    def _pack_drill_id(path: Path) -> str:
        name = Path(path).name
        suffix = "-audit-pack.zip"
        return name[: -len(suffix)] if name.endswith(suffix) else ""

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        path = PurePosixPath(name)
        return bool(name) and not path.is_absolute() and ".." not in path.parts

    def _clean_text(self, value: str, *, required: bool, limit: int) -> str:
        text = " ".join(str(value or "").replace("\x00", " ").split()).strip()
        if not text and required:
            return ""
        return text[:limit]

    def _contains_private_material(self, value: str) -> bool:
        return bool(self._SECRET_RE.search(value) or self._WINDOWS_PATH_RE.search(value))

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
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
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
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
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
    def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        number = ServiceLevelObjectivesService._safe_int(value, default)
        return min(max(number, minimum), maximum)

    @staticmethod
    def _bounded_float(
        value: Any,
        minimum: float,
        maximum: float,
        default: float,
    ) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return min(max(number, minimum), maximum)

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

    @staticmethod
    def _blocked(detail: str) -> dict[str, str]:
        return {"status": "blocked", "detail": detail, "path": ""}
