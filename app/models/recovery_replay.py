from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RecoveryReplayGate:
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
class RecoveryReplayPlanSource:
    plan_id: str
    expected_job_count: int
    recovery_target_minutes: int
    max_duplicate_requests: int
    max_duplicate_outputs: int
    max_orphan_artifacts: int
    max_manifest_mismatches: int
    max_cost_variance_percent: float
    plan_path: Path
    plan_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["plan_path"] = str(self.plan_path)
        return payload


@dataclass(frozen=True)
class RecoveryReplayDegradationSource:
    drill_id: str
    scenario: str
    outcome_status: str
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
class RecoveryReplaySnapshot:
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
    selected_degradation_count: int
    verified_degradation_count: int
    rejected_source_count: int
    plans: tuple[RecoveryReplayPlanSource, ...] = field(default_factory=tuple)
    degradation_sources: tuple[RecoveryReplayDegradationSource, ...] = field(
        default_factory=tuple
    )
    gates: tuple[RecoveryReplayGate, ...] = field(default_factory=tuple)

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
            "selected_degradation_count": self.selected_degradation_count,
            "verified_degradation_count": self.verified_degradation_count,
            "rejected_source_count": self.rejected_source_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "plans": [source.to_dict() for source in self.plans],
            "degradation_sources": [
                source.to_dict() for source in self.degradation_sources
            ],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class RecoveryReplayRecord:
    replay_id: str
    created_at: str
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
