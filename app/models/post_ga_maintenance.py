from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PostGaMaintenanceGate:
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
class PostGaMaintenanceArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str
    captured_at: str = ""
    status: str = "verified"
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = self.path.name
        return payload


@dataclass(frozen=True)
class PostGaMaintenanceSnapshot:
    baseline_id: str
    generated_at: str
    version: str
    channel: str
    status: str
    summary: str
    maintenance_allowed: bool
    evidence_age_days: int
    rollout_percentage: int
    free_space_bytes: int
    gates: tuple[PostGaMaintenanceGate, ...] = field(default_factory=tuple)
    artifacts: tuple[PostGaMaintenanceArtifact, ...] = field(default_factory=tuple)
    baseline_path: Path | None = None
    plan_path: Path | None = None

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_id": self.baseline_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "status": self.status,
            "summary": self.summary,
            "maintenance_allowed": self.maintenance_allowed,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "evidence_age_days": self.evidence_age_days,
            "rollout_percentage": self.rollout_percentage,
            "free_space_bytes": self.free_space_bytes,
            "gates": [gate.to_dict() for gate in self.gates],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "baseline_path": self.baseline_path.name if self.baseline_path else "",
            "plan_path": self.plan_path.name if self.plan_path else "",
        }
