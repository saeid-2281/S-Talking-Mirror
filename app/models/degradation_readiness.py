from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DegradationReadinessGate:
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
class DegradationPlanSource:
    plan_id: str
    scenario: str
    target_load_reduction_percent: float
    max_queue_depth: int
    recovery_target_minutes: int
    max_failed_requests: int
    plan_path: Path
    plan_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["plan_path"] = str(self.plan_path)
        return payload


@dataclass(frozen=True)
class DegradationCapacitySource:
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
class DegradationReadinessSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    status: str
    status_summary: str
    release_gate: str
    recommended_decision: str
    selected_plan_count: int
    verified_plan_count: int
    selected_capacity_count: int
    verified_capacity_count: int
    rejected_source_count: int
    required_scenarios: tuple[str, ...] = field(default_factory=tuple)
    verified_scenarios: tuple[str, ...] = field(default_factory=tuple)
    plans: tuple[DegradationPlanSource, ...] = field(default_factory=tuple)
    capacity_sources: tuple[DegradationCapacitySource, ...] = field(
        default_factory=tuple
    )
    gates: tuple[DegradationReadinessGate, ...] = field(default_factory=tuple)

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
            "status": self.status,
            "status_summary": self.status_summary,
            "release_gate": self.release_gate,
            "recommended_decision": self.recommended_decision,
            "selected_plan_count": self.selected_plan_count,
            "verified_plan_count": self.verified_plan_count,
            "selected_capacity_count": self.selected_capacity_count,
            "verified_capacity_count": self.verified_capacity_count,
            "rejected_source_count": self.rejected_source_count,
            "required_scenarios": list(self.required_scenarios),
            "verified_scenarios": list(self.verified_scenarios),
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "plans": [source.to_dict() for source in self.plans],
            "capacity_sources": [
                source.to_dict() for source in self.capacity_sources
            ],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class DegradationDrillRecord:
    drill_id: str
    created_at: str
    scenario: str
    outcome_status: str
    snapshot_path: Path
    plan_path: Path
    result_path: Path
    attestation_path: Path
    audit_pack_path: Path
    receipt_path: Path

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "snapshot_path",
            "plan_path",
            "result_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload
