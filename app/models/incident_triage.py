from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IncidentTriageGate:
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
class IncidentTriageAction:
    order: int
    code: str
    label: str
    owner: str
    target_minutes: int
    automatic: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IncidentTriageSnapshot:
    case_id: str
    generated_at: str
    version: str
    channel: str
    incident_id: str
    source_bundle: Path
    source_receipt: Path | None
    reported_severity: str
    effective_severity: str
    priority: str
    component: str
    status: str
    status_summary: str
    summary: str
    triage_allowed: bool
    duplicate_count: int
    report_count: int
    log_count: int
    acknowledgement_target_minutes: int
    remediation_target_minutes: int
    fingerprint: str
    gates: tuple[IncidentTriageGate, ...] = field(default_factory=tuple)
    actions: tuple[IncidentTriageAction, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "incident_id": self.incident_id,
            "source_bundle": self.source_bundle.name,
            "source_receipt": self.source_receipt.name if self.source_receipt else "",
            "reported_severity": self.reported_severity,
            "effective_severity": self.effective_severity,
            "priority": self.priority,
            "component": self.component,
            "status": self.status,
            "status_summary": self.status_summary,
            "summary": self.summary,
            "triage_allowed": self.triage_allowed,
            "duplicate_count": self.duplicate_count,
            "report_count": self.report_count,
            "log_count": self.log_count,
            "acknowledgement_target_minutes": self.acknowledgement_target_minutes,
            "remediation_target_minutes": self.remediation_target_minutes,
            "fingerprint": self.fingerprint,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [gate.to_dict() for gate in self.gates],
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class IncidentTriageCase:
    case_id: str
    incident_id: str
    created_at: str
    case_path: Path
    plan_path: Path
    source_bundle: Path
    priority: str
    component: str
    effective_severity: str
    fingerprint: str
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["case_path"] = str(self.case_path)
        payload["plan_path"] = str(self.plan_path)
        payload["source_bundle"] = str(self.source_bundle)
        return payload
