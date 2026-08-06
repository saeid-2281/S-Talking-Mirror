from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IncidentResolutionGate:
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
class IncidentResolutionAction:
    order: int
    code: str
    label: str
    owner: str
    automatic: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IncidentResolutionEvidence:
    kind: str
    path: Path
    status: str
    tests_passed: int
    tests_skipped: int
    tests_failed: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "filename": self.path.name,
            "status": self.status,
            "tests_passed": self.tests_passed,
            "tests_skipped": self.tests_skipped,
            "tests_failed": self.tests_failed,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class IncidentResolutionSnapshot:
    resolution_id: str
    generated_at: str
    version: str
    channel: str
    case_id: str
    incident_id: str
    case_path: Path
    plan_path: Path
    priority: str
    component: str
    resolution_type: str
    resolution_summary: str
    customer_impact: str
    status: str
    status_summary: str
    closure_allowed: bool
    duplicate_count: int
    evidence: tuple[IncidentResolutionEvidence, ...] = field(default_factory=tuple)
    gates: tuple[IncidentResolutionGate, ...] = field(default_factory=tuple)
    actions: tuple[IncidentResolutionAction, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "resolution_id": self.resolution_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "case_id": self.case_id,
            "incident_id": self.incident_id,
            "case_path": self.case_path.name,
            "plan_path": self.plan_path.name,
            "priority": self.priority,
            "component": self.component,
            "resolution_type": self.resolution_type,
            "resolution_summary": self.resolution_summary,
            "customer_impact": self.customer_impact,
            "status": self.status,
            "status_summary": self.status_summary,
            "closure_allowed": self.closure_allowed,
            "duplicate_count": self.duplicate_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "evidence": [item.to_dict() for item in self.evidence],
            "gates": [gate.to_dict() for gate in self.gates],
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class IncidentResolutionRecord:
    resolution_id: str
    case_id: str
    created_at: str
    resolution_path: Path
    closure_path: Path
    knowledge_path: Path
    evidence_dir: Path
    priority: str
    component: str
    resolution_type: str
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("resolution_path", "closure_path", "knowledge_path", "evidence_dir"):
            payload[key] = str(payload[key])
        return payload
