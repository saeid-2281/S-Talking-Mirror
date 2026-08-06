from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CapacityReadinessGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class CapacityObservationSource:
    observation_id: str
    captured_at: str
    interval_minutes: int
    current_load_per_minute: int
    peak_load_per_minute: int
    sustainable_capacity_per_minute: int
    queue_depth: int
    worker_utilization_percent: float
    memory_utilization_percent: float
    provider_throttle_percent: float
    daily_growth_percent: float
    observation_path: Path
    observation_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["observation_path"] = str(self.observation_path)
        return payload


@dataclass(frozen=True)
class CapacitySloSource:
    decision_id: str
    decision: str
    release_gate: str
    snapshot_status: str
    snapshot_path: Path
    decision_path: Path
    audit_pack_path: Path
    receipt_path: Path
    snapshot_sha256: str
    decision_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "decision_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload


@dataclass(frozen=True)
class CapacityReadinessSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    forecast_days: int
    minimum_headroom_percent: float
    status: str
    status_summary: str
    release_gate: str
    recommended_decision: str
    selected_observation_count: int
    verified_observation_count: int
    selected_slo_count: int
    verified_slo_count: int
    rejected_source_count: int
    current_load_per_minute: int
    peak_load_per_minute: int
    sustainable_capacity_per_minute: int
    current_headroom_percent: float
    projected_peak_load_per_minute: float
    projected_headroom_percent: float
    days_to_saturation: float | None
    max_queue_depth: int
    max_worker_utilization_percent: float
    max_memory_utilization_percent: float
    max_provider_throttle_percent: float
    max_daily_growth_percent: float
    observations: tuple[CapacityObservationSource, ...] = field(default_factory=tuple)
    slo_sources: tuple[CapacitySloSource, ...] = field(default_factory=tuple)
    gates: tuple[CapacityReadinessGate, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "forecast_days": self.forecast_days,
            "minimum_headroom_percent": self.minimum_headroom_percent,
            "status": self.status,
            "status_summary": self.status_summary,
            "release_gate": self.release_gate,
            "recommended_decision": self.recommended_decision,
            "selected_observation_count": self.selected_observation_count,
            "verified_observation_count": self.verified_observation_count,
            "selected_slo_count": self.selected_slo_count,
            "verified_slo_count": self.verified_slo_count,
            "rejected_source_count": self.rejected_source_count,
            "current_load_per_minute": self.current_load_per_minute,
            "peak_load_per_minute": self.peak_load_per_minute,
            "sustainable_capacity_per_minute": self.sustainable_capacity_per_minute,
            "current_headroom_percent": self.current_headroom_percent,
            "projected_peak_load_per_minute": self.projected_peak_load_per_minute,
            "projected_headroom_percent": self.projected_headroom_percent,
            "days_to_saturation": self.days_to_saturation,
            "max_queue_depth": self.max_queue_depth,
            "max_worker_utilization_percent": self.max_worker_utilization_percent,
            "max_memory_utilization_percent": self.max_memory_utilization_percent,
            "max_provider_throttle_percent": self.max_provider_throttle_percent,
            "max_daily_growth_percent": self.max_daily_growth_percent,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "observations": [source.to_dict() for source in self.observations],
            "slo_sources": [source.to_dict() for source in self.slo_sources],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class CapacityDecisionRecord:
    decision_id: str
    created_at: str
    decision: str
    snapshot_path: Path
    decision_path: Path
    audit_pack_path: Path
    receipt_path: Path
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "decision_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
