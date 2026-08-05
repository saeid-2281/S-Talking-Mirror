from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IncidentSupportGate:
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
class IncidentSupportArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str
    status: str = "verified"
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = self.path.name
        return payload


@dataclass(frozen=True)
class IncidentSupportSnapshot:
    incident_id: str
    generated_at: str
    version: str
    channel: str
    severity: str
    summary: str
    status: str
    status_summary: str
    support_allowed: bool
    baseline_verified: bool
    crash_count: int
    unacknowledged_count: int
    integrity_failure_count: int
    eligible_log_count: int
    estimated_size_bytes: int
    max_bundle_bytes: int
    gates: tuple[IncidentSupportGate, ...] = field(default_factory=tuple)
    artifacts: tuple[IncidentSupportArtifact, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "severity": self.severity,
            "summary": self.summary,
            "status": self.status,
            "status_summary": self.status_summary,
            "support_allowed": self.support_allowed,
            "baseline_verified": self.baseline_verified,
            "crash_count": self.crash_count,
            "unacknowledged_count": self.unacknowledged_count,
            "integrity_failure_count": self.integrity_failure_count,
            "eligible_log_count": self.eligible_log_count,
            "estimated_size_bytes": self.estimated_size_bytes,
            "max_bundle_bytes": self.max_bundle_bytes,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [gate.to_dict() for gate in self.gates],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class IncidentSupportBundle:
    bundle_id: str
    incident_id: str
    created_at: str
    path: Path
    receipt_path: Path
    severity: str
    report_count: int
    log_count: int
    size_bytes: int
    sha256: str
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["receipt_path"] = str(self.receipt_path)
        return payload
