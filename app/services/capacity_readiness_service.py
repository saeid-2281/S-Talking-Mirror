from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.capacity_readiness import (
    CapacityDecisionRecord,
    CapacityObservationSource,
    CapacityReadinessGate,
    CapacityReadinessSnapshot,
    CapacitySloSource,
)
from app.services.service_level_objectives_service import ServiceLevelObjectivesService


class CapacityReadinessService:
    """Create capacity forecasts and human-controlled degradation evidence.

    Phase 72 consumes aggregate capacity observations and intact Phase 71 SLO
    decisions. It calculates current and forecast headroom, saturation risk and
    release safety. It never scales infrastructure, sheds load, changes queues,
    deploys, rolls back, restarts or publishes automatically.
    """

    SCHEMA_VERSION = 1
    DEFAULT_FORECAST_DAYS = 30
    MIN_FORECAST_DAYS = 1
    MAX_FORECAST_DAYS = 365
    DEFAULT_MINIMUM_HEADROOM_PERCENT = 20.0
    MINIMUM_HEADROOM_LIMIT = 0.0
    MAXIMUM_HEADROOM_LIMIT = 90.0
    WORKER_WARNING_PERCENT = 80.0
    WORKER_BLOCK_PERCENT = 95.0
    MEMORY_WARNING_PERCENT = 80.0
    MEMORY_BLOCK_PERCENT = 95.0
    THROTTLE_WARNING_PERCENT = 5.0
    THROTTLE_BLOCK_PERCENT = 20.0
    QUEUE_WARNING_DEPTH = 100
    QUEUE_BLOCK_DEPTH = 1000
    DECISIONS = (
        "allow_release",
        "scale_before_release",
        "prepare_degraded_mode",
        "hold_release",
    )
    _WINDOWS_PATH_RE = re.compile(r"(?i)(?:[a-z]:\\|\\\\)[^\s]+")
    _SECRET_RE = re.compile(
        r"(?i)(?:api[_ -]?key|access[_ -]?token|secret|password|authorization)\s*[:=]"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        service_level_objectives_service: ServiceLevelObjectivesService,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.service_level_objectives_service = service_level_objectives_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "capacity-readiness"
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
                self.observations_dir.glob("capacity-observation-*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_slo_snapshot_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_level_objectives_service.snapshots_dir.glob("*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_slo_decision_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_level_objectives_service.decisions_dir.glob("*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_slo_pack_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_level_objectives_service.audit_packs_dir.glob("*.zip"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def default_slo_receipt_paths(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self.service_level_objectives_service.receipts_dir.glob("*.json"),
                key=lambda path: path.stat().st_mtime,
            )
        )

    def create_observation(
        self,
        *,
        captured_at: str,
        interval_minutes: int,
        current_load_per_minute: int,
        peak_load_per_minute: int,
        sustainable_capacity_per_minute: int,
        queue_depth: int,
        worker_utilization_percent: float,
        memory_utilization_percent: float,
        provider_throttle_percent: float,
        daily_growth_percent: float,
        owner: str,
        notes: str = "",
        acknowledge: bool = False,
    ) -> CapacityObservationSource | dict[str, str]:
        owner_text = self._clean_text(owner, required=True, limit=160)
        notes_text = self._clean_text(notes, required=False, limit=1000)
        captured = self._parse_datetime(captured_at)
        numeric_valid = (
            1 <= int(interval_minutes) <= 10080
            and 0 <= int(current_load_per_minute)
            and int(current_load_per_minute) <= int(peak_load_per_minute)
            and int(peak_load_per_minute) <= int(sustainable_capacity_per_minute)
            and int(sustainable_capacity_per_minute) > 0
            and 0 <= int(queue_depth) <= 100000000
            and 0.0 <= float(worker_utilization_percent) <= 100.0
            and 0.0 <= float(memory_utilization_percent) <= 100.0
            and 0.0 <= float(provider_throttle_percent) <= 100.0
            and -100.0 <= float(daily_growth_percent) <= 1000.0
        )
        if captured is None or not numeric_valid or not owner_text:
            return self._blocked("Capacity observation fields are invalid or inconsistent.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            notes_text
        ):
            return self._blocked("Capacity observation contains private material.")
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review aggregate capacity metrics and acknowledge local creation.",
            }

        observation_id = f"capacity-observation-{uuid.uuid4().hex[:12]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "observation_id": observation_id,
            "created_at": self._now_iso(),
            "captured_at": captured.isoformat(),
            "interval_minutes": int(interval_minutes),
            "current_load_per_minute": int(current_load_per_minute),
            "peak_load_per_minute": int(peak_load_per_minute),
            "sustainable_capacity_per_minute": int(
                sustainable_capacity_per_minute
            ),
            "queue_depth": int(queue_depth),
            "worker_utilization_percent": round(float(worker_utilization_percent), 4),
            "memory_utilization_percent": round(float(memory_utilization_percent), 4),
            "provider_throttle_percent": round(float(provider_throttle_percent), 4),
            "daily_growth_percent": round(float(daily_growth_percent), 6),
            "owner": owner_text,
            "notes": notes_text,
            "human_reviewed": True,
        }
        payload.update(self._safety_contract())
        payload["observation_sha256"] = self._payload_digest(payload)
        path = self.observations_dir / f"{observation_id}.json"
        self._write_json(path, payload)
        return self._observation_source(path, payload)

    def snapshot(
        self,
        *,
        observation_paths: Iterable[Path] = (),
        slo_snapshot_paths: Iterable[Path] = (),
        slo_decision_paths: Iterable[Path] = (),
        slo_pack_paths: Iterable[Path] = (),
        slo_receipt_paths: Iterable[Path] = (),
        forecast_days: int = DEFAULT_FORECAST_DAYS,
        minimum_headroom_percent: float = DEFAULT_MINIMUM_HEADROOM_PERCENT,
    ) -> CapacityReadinessSnapshot:
        observations = tuple(dict.fromkeys(Path(path) for path in observation_paths))
        slo_snapshots = tuple(dict.fromkeys(Path(path) for path in slo_snapshot_paths))
        slo_decisions = tuple(dict.fromkeys(Path(path) for path in slo_decision_paths))
        slo_packs = tuple(dict.fromkeys(Path(path) for path in slo_pack_paths))
        slo_receipts = tuple(dict.fromkeys(Path(path) for path in slo_receipt_paths))
        if not observations:
            observations = self.default_observation_paths()
        if not slo_snapshots:
            slo_snapshots = self.default_slo_snapshot_paths()
        if not slo_decisions:
            slo_decisions = self.default_slo_decision_paths()
        if not slo_packs:
            slo_packs = self.default_slo_pack_paths()
        if not slo_receipts:
            slo_receipts = self.default_slo_receipt_paths()

        days = self._bounded_int(
            forecast_days,
            self.MIN_FORECAST_DAYS,
            self.MAX_FORECAST_DAYS,
            self.DEFAULT_FORECAST_DAYS,
        )
        minimum_headroom = self._bounded_float(
            minimum_headroom_percent,
            self.MINIMUM_HEADROOM_LIMIT,
            self.MAXIMUM_HEADROOM_LIMIT,
            self.DEFAULT_MINIMUM_HEADROOM_PERCENT,
        )
        gates: list[CapacityReadinessGate] = []

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
                    else "Capacity governance must run from the certified stable build."
                ),
                "Run the workflow from the certified stable application.",
            )
        )
        policy_ok = (
            self.MIN_FORECAST_DAYS <= int(forecast_days) <= self.MAX_FORECAST_DAYS
            and self.MINIMUM_HEADROOM_LIMIT
            <= float(minimum_headroom_percent)
            <= self.MAXIMUM_HEADROOM_LIMIT
        )
        gates.append(
            self._gate(
                "capacity_policy",
                "Capacity forecast policy",
                "pass" if policy_ok else "block",
                "blocker",
                f"Forecast {days} day(s), minimum headroom {minimum_headroom:.2f}%.",
                "Use supported capacity policy values.",
            )
        )

        observation_sources, observation_rejected = self._observation_sources(
            observations
        )
        gates.append(
            self._gate(
                "capacity_observations",
                "Capacity observation custody",
                "pass"
                if observation_sources and observation_rejected == 0
                else "block",
                "blocker",
                (
                    f"Verified {len(observation_sources)} aggregate observation(s)."
                    if observation_sources and observation_rejected == 0
                    else "At least one intact aggregate capacity observation is required."
                ),
                "Create or select intact human-reviewed capacity observations.",
            )
        )

        slo_sources, slo_rejected = self._slo_sources(
            slo_snapshots,
            slo_decisions,
            slo_packs,
            slo_receipts,
        )
        slo_counts_match = (
            len(slo_snapshots)
            == len(slo_decisions)
            == len(slo_packs)
            == len(slo_receipts)
        )
        slo_ok = bool(slo_sources) and slo_rejected == 0 and slo_counts_match
        gates.append(
            self._gate(
                "slo_evidence",
                "Phase 71 SLO evidence",
                "pass" if slo_ok else "block",
                "blocker",
                (
                    f"Verified {len(slo_sources)} SLO decision set(s)."
                    if slo_ok
                    else "A one-to-one intact SLO snapshot, decision, pack and receipt set is required."
                ),
                "Select matching intact Phase 71 artifacts.",
            )
        )

        current_load = max(
            (source.current_load_per_minute for source in observation_sources),
            default=0,
        )
        peak_load = max(
            (source.peak_load_per_minute for source in observation_sources),
            default=0,
        )
        capacities = [
            source.sustainable_capacity_per_minute for source in observation_sources
        ]
        capacity = min(capacities) if capacities else 0
        queue_depth = max((source.queue_depth for source in observation_sources), default=0)
        worker = max(
            (source.worker_utilization_percent for source in observation_sources),
            default=0.0,
        )
        memory = max(
            (source.memory_utilization_percent for source in observation_sources),
            default=0.0,
        )
        throttle = max(
            (source.provider_throttle_percent for source in observation_sources),
            default=0.0,
        )
        growth = max(
            (source.daily_growth_percent for source in observation_sources),
            default=0.0,
        )
        headroom = (
            100.0 * max(0, capacity - peak_load) / capacity if capacity else 0.0
        )
        growth_factor = max(0.0, 1.0 + growth / 100.0)
        projected_peak = peak_load * (growth_factor**days)
        projected_headroom = (
            100.0 * (capacity - projected_peak) / capacity if capacity else -100.0
        )
        days_to_saturation = self._days_to_saturation(
            peak_load=peak_load,
            capacity=capacity,
            daily_growth_percent=growth,
        )

        gates.append(
            self._capacity_gate(
                "current_headroom",
                "Current capacity headroom",
                headroom,
                minimum_headroom,
                f"Current conservative headroom is {headroom:.2f}%.",
                "Scale or reduce planned demand before release.",
            )
        )
        projected_status = "pass"
        if projected_headroom < 0:
            projected_status = "block"
        elif projected_headroom < minimum_headroom:
            projected_status = "warn"
        gates.append(
            self._gate(
                "forecast_headroom",
                "Forecast capacity headroom",
                projected_status,
                "blocker" if projected_status == "block" else "warning",
                (
                    f"Projected peak {projected_peak:.2f}/min leaves "
                    f"{projected_headroom:.2f}% headroom after {days} day(s)."
                ),
                "Create a reviewed scale or degradation plan before release.",
            )
        )
        gates.append(
            self._threshold_gate(
                "worker_utilization",
                "Worker utilization",
                worker,
                self.WORKER_WARNING_PERCENT,
                self.WORKER_BLOCK_PERCENT,
                "%",
            )
        )
        gates.append(
            self._threshold_gate(
                "memory_utilization",
                "Memory utilization",
                memory,
                self.MEMORY_WARNING_PERCENT,
                self.MEMORY_BLOCK_PERCENT,
                "%",
            )
        )
        gates.append(
            self._threshold_gate(
                "provider_throttle",
                "Provider throttle pressure",
                throttle,
                self.THROTTLE_WARNING_PERCENT,
                self.THROTTLE_BLOCK_PERCENT,
                "%",
            )
        )
        queue_status = "pass"
        if queue_depth >= self.QUEUE_BLOCK_DEPTH:
            queue_status = "block"
        elif queue_depth >= self.QUEUE_WARNING_DEPTH:
            queue_status = "warn"
        gates.append(
            self._gate(
                "queue_depth",
                "Queue depth",
                queue_status,
                "blocker" if queue_status == "block" else "warning",
                f"Maximum observed queue depth is {queue_depth}.",
                "Review queue limits and degraded-mode controls.",
            )
        )

        slo_hold = any(
            source.release_gate == "hold" or source.decision == "hold"
            for source in slo_sources
        )
        slo_review = any(
            source.release_gate == "manual_review"
            or source.decision == "manual_review"
            for source in slo_sources
        )
        gates.append(
            self._gate(
                "slo_release_gate",
                "Inherited SLO release gate",
                "block" if slo_hold else ("warn" if slo_review else "pass"),
                "blocker" if slo_hold else "warning",
                (
                    "Phase 71 requires release hold."
                    if slo_hold
                    else (
                        "Phase 71 requires human review."
                        if slo_review
                        else "Phase 71 allows release consideration."
                    )
                ),
                "Resolve the inherited SLO gate before release approval.",
            )
        )

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        if blockers:
            status = "blocked"
            release_gate = "hold"
            recommendation = "hold_release"
        elif warnings:
            status = "ready_with_warnings"
            release_gate = "manual_review"
            recommendation = (
                "scale_before_release"
                if projected_headroom < minimum_headroom
                else "prepare_degraded_mode"
            )
        else:
            status = "ready"
            release_gate = "allow"
            recommendation = "allow_release"

        rejected = observation_rejected + slo_rejected
        return CapacityReadinessSnapshot(
            snapshot_id=f"capacity-readiness-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            forecast_days=days,
            minimum_headroom_percent=round(minimum_headroom, 4),
            status=status,
            status_summary=self._summary(status, headroom, projected_headroom),
            release_gate=release_gate,
            recommended_decision=recommendation,
            selected_observation_count=len(observations),
            verified_observation_count=len(observation_sources),
            selected_slo_count=max(
                len(slo_snapshots), len(slo_decisions), len(slo_packs), len(slo_receipts)
            ),
            verified_slo_count=len(slo_sources),
            rejected_source_count=rejected,
            current_load_per_minute=current_load,
            peak_load_per_minute=peak_load,
            sustainable_capacity_per_minute=capacity,
            current_headroom_percent=round(headroom, 4),
            projected_peak_load_per_minute=round(projected_peak, 4),
            projected_headroom_percent=round(projected_headroom, 4),
            days_to_saturation=(
                round(days_to_saturation, 4)
                if days_to_saturation is not None
                else None
            ),
            max_queue_depth=queue_depth,
            max_worker_utilization_percent=round(worker, 4),
            max_memory_utilization_percent=round(memory, 4),
            max_provider_throttle_percent=round(throttle, 4),
            max_daily_growth_percent=round(growth, 6),
            observations=observation_sources,
            slo_sources=slo_sources,
            gates=tuple(gates),
        )

    def create_decision(
        self,
        snapshot: CapacityReadinessSnapshot,
        *,
        decision: str,
        owner: str,
        statement: str,
        acknowledge: bool = False,
    ) -> CapacityDecisionRecord | dict[str, str]:
        decision_value = str(decision or "").strip().lower()
        owner_text = self._clean_text(owner, required=True, limit=160)
        statement_text = self._clean_text(statement, required=True, limit=1200)
        if decision_value not in self.DECISIONS or not owner_text or not statement_text:
            return self._blocked("Capacity decision fields are invalid.")
        if self._contains_private_material(owner_text) or self._contains_private_material(
            statement_text
        ):
            return self._blocked("Capacity decision contains private material.")
        if snapshot.release_gate == "hold" and decision_value != "hold_release":
            return self._blocked("A blocked capacity snapshot requires hold_release.")
        if snapshot.release_gate == "manual_review" and decision_value == "allow_release":
            return self._blocked(
                "Capacity warnings require scaling, degraded-mode preparation or hold."
            )
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Review the capacity gates and acknowledge local recording.",
            }

        snapshot_path = self.export_snapshot(snapshot)
        decision_id = f"capacity-decision-{uuid.uuid4().hex[:12]}"
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "decision_id": decision_id,
            "created_at": self._now_iso(),
            "decision": decision_value,
            "calculated_release_gate": snapshot.release_gate,
            "recommended_decision": snapshot.recommended_decision,
            "owner": owner_text,
            "statement": statement_text,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "human_decision": True,
        }
        payload.update(self._safety_contract())
        payload["decision_sha256"] = self._payload_digest(payload)
        decision_path = self.decisions_dir / f"{decision_id}.json"
        self._write_json(decision_path, payload)
        pack_path, receipt_path = self._create_audit_pack(
            decision_id=decision_id,
            snapshot_path=snapshot_path,
            decision_path=decision_path,
            snapshot=snapshot,
        )
        return CapacityDecisionRecord(
            decision_id=decision_id,
            created_at=str(payload["created_at"]),
            decision=decision_value,
            snapshot_path=snapshot_path,
            decision_path=decision_path,
            audit_pack_path=pack_path,
            receipt_path=receipt_path,
        )

    def verify_observation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Capacity observation is unreadable."
        expected = str(payload.get("observation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("observation_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Capacity observation SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Capacity observation safety contract changed."
        if not payload.get("human_reviewed"):
            return False, "Capacity observation was not human reviewed."
        for field_name in ("owner", "notes"):
            if self._contains_private_material(str(payload.get(field_name) or "")):
                return False, "Capacity observation contains private material."
        if self._safe_int(payload.get("sustainable_capacity_per_minute")) <= 0:
            return False, "Capacity observation has no sustainable capacity."
        if self._safe_int(payload.get("peak_load_per_minute")) > self._safe_int(
            payload.get("sustainable_capacity_per_minute")
        ):
            return False, "Capacity observation peak exceeds declared capacity."
        return True, "Capacity observation is intact and privacy-safe."

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Capacity snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Capacity snapshot SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Capacity snapshot safety contract changed."
        return True, "Capacity snapshot is intact."

    def verify_decision(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Capacity decision is unreadable."
        expected = str(payload.get("decision_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("decision_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Capacity decision SHA-256 does not match."
        if not self._verify_common_contract(payload):
            return False, "Capacity decision safety contract changed."
        decision = str(payload.get("decision") or "")
        gate = str(payload.get("calculated_release_gate") or "")
        if decision not in self.DECISIONS:
            return False, "Capacity decision value is unsupported."
        if gate == "hold" and decision != "hold_release":
            return False, "Capacity decision conflicts with a hold gate."
        if gate == "manual_review" and decision == "allow_release":
            return False, "Capacity decision bypasses a manual-review gate."
        for field_name in ("owner", "statement"):
            if self._contains_private_material(str(payload.get(field_name) or "")):
                return False, "Capacity decision contains private material."
        snapshot_path = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot_path.is_file() or self._sha256(snapshot_path) != str(
            payload.get("snapshot_sha256") or ""
        ):
            return False, "Capacity snapshot custody changed."
        snapshot_ok, detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return False, detail
        return True, "Capacity decision is intact and snapshot verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Capacity audit-pack receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if expected != self._payload_digest(unsigned):
            return False, "Capacity receipt SHA-256 does not match."
        if not pack_path.is_file():
            return False, "Capacity audit pack is missing."
        if str(receipt.get("pack_filename") or "") != pack_path.name:
            return False, "Capacity audit-pack filename changed."
        if self._safe_int(receipt.get("pack_size_bytes"), -1) != pack_path.stat().st_size:
            return False, "Capacity audit-pack size changed."
        if str(receipt.get("pack_sha256") or "") != self._sha256(pack_path):
            return False, "Capacity audit-pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path) as archive:
                names = archive.namelist()
                if "manifest.json" not in names:
                    return False, "Capacity audit pack has no manifest."
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    return False, "Capacity audit-pack manifest is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "Capacity audit-pack manifest SHA-256 does not match."
                entries = manifest.get("entries")
                if not isinstance(entries, list) or not entries:
                    return False, "Capacity audit-pack manifest has no entries."
                for item in entries:
                    if not isinstance(item, Mapping):
                        return False, "Capacity audit-pack entry is invalid."
                    name = str(item.get("path") or "")
                    if not self._safe_archive_name(name) or name not in names:
                        return False, "Capacity audit-pack entry path is unsafe or missing."
                    data = archive.read(name)
                    if len(data) != self._safe_int(item.get("size_bytes"), -1):
                        return False, "Capacity audit-pack entry size changed."
                    if hashlib.sha256(data).hexdigest() != str(item.get("sha256") or ""):
                        return False, "Capacity audit-pack entry SHA-256 changed."
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
            return False, "Capacity audit pack is unreadable."
        return True, "Capacity audit pack and receipt are intact."

    def export_snapshot(self, snapshot: CapacityReadinessSnapshot) -> Path:
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
    ) -> tuple[tuple[CapacityObservationSource, ...], int]:
        sources: list[CapacityObservationSource] = []
        rejected = 0
        seen_ids: set[str] = set()
        for path in paths:
            ok, _detail = self.verify_observation(path)
            payload = self._read_json(Path(path))
            if not ok or not isinstance(payload, dict):
                rejected += 1
                continue
            observation_id = str(payload.get("observation_id") or "")
            if not observation_id or observation_id in seen_ids:
                rejected += 1
                continue
            seen_ids.add(observation_id)
            sources.append(self._observation_source(Path(path), payload))
        sources.sort(key=lambda source: source.captured_at)
        return tuple(sources), rejected

    def _observation_source(
        self,
        path: Path,
        payload: Mapping[str, object],
    ) -> CapacityObservationSource:
        return CapacityObservationSource(
            observation_id=str(payload.get("observation_id") or ""),
            captured_at=str(payload.get("captured_at") or ""),
            interval_minutes=self._safe_int(payload.get("interval_minutes")),
            current_load_per_minute=self._safe_int(
                payload.get("current_load_per_minute")
            ),
            peak_load_per_minute=self._safe_int(payload.get("peak_load_per_minute")),
            sustainable_capacity_per_minute=self._safe_int(
                payload.get("sustainable_capacity_per_minute")
            ),
            queue_depth=self._safe_int(payload.get("queue_depth")),
            worker_utilization_percent=self._safe_float(
                payload.get("worker_utilization_percent")
            ),
            memory_utilization_percent=self._safe_float(
                payload.get("memory_utilization_percent")
            ),
            provider_throttle_percent=self._safe_float(
                payload.get("provider_throttle_percent")
            ),
            daily_growth_percent=self._safe_float(payload.get("daily_growth_percent")),
            observation_path=path,
            observation_sha256=self._sha256(path),
        )

    def _slo_sources(
        self,
        snapshot_paths: Iterable[Path],
        decision_paths: Iterable[Path],
        pack_paths: Iterable[Path],
        receipt_paths: Iterable[Path],
    ) -> tuple[tuple[CapacitySloSource, ...], int]:
        snapshots = self._index_json(snapshot_paths, "snapshot_id")
        decisions = self._index_json(decision_paths, "decision_id")
        decision_payloads = {
            key: self._read_json(path) or {} for key, path in decisions.items()
        }
        decision_to_snapshot = {
            key: str(payload.get("snapshot_filename") or "")
            for key, payload in decision_payloads.items()
        }
        snapshot_by_name = {path.name: (key, path) for key, path in snapshots.items()}
        packs = {self._pack_decision_id(path): Path(path) for path in pack_paths}
        receipts = self._index_json(receipt_paths, "decision_id")
        all_ids = set(decisions) | set(packs) | set(receipts)
        sources: list[CapacitySloSource] = []
        rejected = 0
        for decision_id in sorted(all_ids):
            decision_path = decisions.get(decision_id)
            pack_path = packs.get(decision_id)
            receipt_path = receipts.get(decision_id)
            snapshot_entry = snapshot_by_name.get(
                decision_to_snapshot.get(decision_id, "")
            )
            if None in (decision_path, pack_path, receipt_path, snapshot_entry):
                rejected += 1
                continue
            assert decision_path is not None
            assert pack_path is not None
            assert receipt_path is not None
            assert snapshot_entry is not None
            _snapshot_id, snapshot_path = snapshot_entry
            snapshot_ok, _ = self.service_level_objectives_service.verify_snapshot(
                snapshot_path
            )
            decision_ok, _ = self.service_level_objectives_service.verify_decision(
                decision_path
            )
            pack_ok, _ = self.service_level_objectives_service.verify_audit_pack(
                pack_path,
                receipt_path,
            )
            snapshot_payload = self._read_json(snapshot_path) or {}
            decision_payload = self._read_json(decision_path) or {}
            if not snapshot_ok or not decision_ok or not pack_ok:
                rejected += 1
                continue
            sources.append(
                CapacitySloSource(
                    decision_id=decision_id,
                    decision=str(decision_payload.get("decision") or ""),
                    release_gate=str(snapshot_payload.get("release_gate") or ""),
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

    def _create_audit_pack(
        self,
        *,
        decision_id: str,
        snapshot_path: Path,
        decision_path: Path,
        snapshot: CapacityReadinessSnapshot,
    ) -> tuple[Path, Path]:
        entries: dict[str, bytes] = {
            "capacity/snapshot.json": snapshot_path.read_bytes(),
            "capacity/decision.json": decision_path.read_bytes(),
        }
        for source in snapshot.observations:
            entries[f"observations/{source.observation_path.name}"] = (
                source.observation_path.read_bytes()
            )
        for source in snapshot.slo_sources:
            entries[f"slo/{source.snapshot_path.name}"] = source.snapshot_path.read_bytes()
            entries[f"slo/{source.decision_path.name}"] = source.decision_path.read_bytes()
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
            "entries": manifest_entries,
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        pack_path = self.audit_packs_dir / f"{decision_id}-audit-pack.zip"
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr("manifest.json", self._json_bytes(manifest))
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "decision_id": decision_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{decision_id}-receipt.json"
        self._write_json(receipt_path, receipt)
        return pack_path, receipt_path

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "automatic_scale": False,
            "automatic_load_shedding": False,
            "automatic_queue_change": False,
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
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> CapacityReadinessGate:
        return CapacityReadinessGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    def _capacity_gate(
        self,
        code: str,
        label: str,
        value: float,
        target: float,
        detail: str,
        remediation: str,
    ) -> CapacityReadinessGate:
        if value < 0:
            status = "block"
        elif value < target:
            status = "warn"
        else:
            status = "pass"
        return self._gate(
            code,
            label,
            status,
            "blocker" if status == "block" else "warning",
            detail,
            remediation,
        )

    def _threshold_gate(
        self,
        code: str,
        label: str,
        value: float,
        warning: float,
        blocker: float,
        suffix: str,
    ) -> CapacityReadinessGate:
        status = "pass"
        if value >= blocker:
            status = "block"
        elif value >= warning:
            status = "warn"
        return self._gate(
            code,
            label,
            status,
            "blocker" if status == "block" else "warning",
            f"Maximum observed value is {value:.2f}{suffix}.",
            "Reduce pressure or add reviewed capacity before release.",
        )

    @staticmethod
    def _days_to_saturation(
        *,
        peak_load: int,
        capacity: int,
        daily_growth_percent: float,
    ) -> float | None:
        if peak_load <= 0 or capacity <= peak_load:
            return 0.0 if capacity and peak_load >= capacity else None
        if daily_growth_percent <= 0:
            return None
        growth_factor = 1.0 + daily_growth_percent / 100.0
        if growth_factor <= 1.0:
            return None
        return math.log(capacity / peak_load) / math.log(growth_factor)

    @staticmethod
    def _summary(status: str, headroom: float, projected_headroom: float) -> str:
        if status == "blocked":
            return "Capacity blockers require a release hold and reviewed remediation."
        if status == "ready_with_warnings":
            return (
                "Capacity requires human review before release; current headroom "
                f"{headroom:.2f}%, projected {projected_headroom:.2f}%."
            )
        return (
            "Capacity evidence supports release consideration; current headroom "
            f"{headroom:.2f}%, projected {projected_headroom:.2f}%."
        )

    def _index_json(
        self,
        paths: Iterable[Path],
        key: str,
    ) -> dict[str, Path]:
        result: dict[str, Path] = {}
        for path in paths:
            payload = self._read_json(Path(path))
            identifier = str((payload or {}).get(key) or "")
            if identifier and identifier not in result:
                result[identifier] = Path(path)
        return result

    @staticmethod
    def _pack_decision_id(path: Path) -> str:
        suffix = "-audit-pack.zip"
        return path.name[: -len(suffix)] if path.name.endswith(suffix) else ""

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        pure = PurePosixPath(name)
        return bool(name) and not pure.is_absolute() and ".." not in pure.parts

    def _clean_text(self, value: str, *, required: bool, limit: int) -> str:
        cleaned = " ".join(str(value or "").split())[:limit]
        if required and not cleaned:
            return ""
        return cleaned

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
        return hashlib.sha256(path.read_bytes()).hexdigest()

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
            payload = json.loads(path.read_text(encoding="utf-8"))
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

    @staticmethod
    def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
        parsed = CapacityReadinessService._safe_int(value, default)
        return min(max(parsed, minimum), maximum)

    @staticmethod
    def _bounded_float(
        value: Any,
        minimum: float,
        maximum: float,
        default: float,
    ) -> float:
        parsed = CapacityReadinessService._safe_float(value, default)
        return min(max(parsed, minimum), maximum)

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
        return {"status": "blocked", "detail": detail}
