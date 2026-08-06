from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ServiceLevelGate:
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
class ServiceLevelObservationSource:
    observation_id: str
    window_start: str
    window_end: str
    window_minutes: int
    total_operations: int
    successful_operations: int
    failed_operations: int
    unavailable_minutes: int
    p95_latency_ms: int
    observation_path: Path
    observation_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["observation_path"] = str(self.observation_path)
        return payload


@dataclass(frozen=True)
class ServiceLevelContinuitySource:
    drill_id: str
    outcome: str
    attestation_status: str
    result_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path
    result_sha256: str
    attestation_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "result_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload


@dataclass(frozen=True)
class ServiceLevelObjectivesSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    window_days: int
    availability_target_percent: float
    success_target_percent: float
    p95_latency_target_ms: int
    status: str
    status_summary: str
    release_gate: str
    observed_window_minutes: int
    expected_window_minutes: int
    total_operations: int
    successful_operations: int
    failed_operations: int
    unavailable_minutes: int
    availability_percent: float
    success_percent: float
    p95_latency_ms: int
    error_budget_minutes: float
    error_budget_consumed_minutes: float
    error_budget_remaining_minutes: float
    error_budget_burn_rate: float
    selected_observation_count: int
    verified_observation_count: int
    selected_continuity_count: int
    verified_continuity_count: int
    rejected_source_count: int
    observations: tuple[ServiceLevelObservationSource, ...] = field(
        default_factory=tuple
    )
    continuity_sources: tuple[ServiceLevelContinuitySource, ...] = field(
        default_factory=tuple
    )
    gates: tuple[ServiceLevelGate, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    @property
    def decision_allowed(self) -> bool:
        return self.release_gate in {"allow", "manual_review", "hold"}

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "window_days": self.window_days,
            "availability_target_percent": self.availability_target_percent,
            "success_target_percent": self.success_target_percent,
            "p95_latency_target_ms": self.p95_latency_target_ms,
            "status": self.status,
            "status_summary": self.status_summary,
            "release_gate": self.release_gate,
            "observed_window_minutes": self.observed_window_minutes,
            "expected_window_minutes": self.expected_window_minutes,
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "unavailable_minutes": self.unavailable_minutes,
            "availability_percent": self.availability_percent,
            "success_percent": self.success_percent,
            "p95_latency_ms": self.p95_latency_ms,
            "error_budget_minutes": self.error_budget_minutes,
            "error_budget_consumed_minutes": self.error_budget_consumed_minutes,
            "error_budget_remaining_minutes": self.error_budget_remaining_minutes,
            "error_budget_burn_rate": self.error_budget_burn_rate,
            "selected_observation_count": self.selected_observation_count,
            "verified_observation_count": self.verified_observation_count,
            "selected_continuity_count": self.selected_continuity_count,
            "verified_continuity_count": self.verified_continuity_count,
            "rejected_source_count": self.rejected_source_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "observations": [source.to_dict() for source in self.observations],
            "continuity_sources": [
                source.to_dict() for source in self.continuity_sources
            ],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class ServiceLevelDecisionRecord:
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
