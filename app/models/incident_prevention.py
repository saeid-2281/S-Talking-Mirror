from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class IncidentPreventionGate:
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
class IncidentPreventionSource:
    path: Path
    closure_id: str
    resolution_id: str
    case_id: str
    fingerprint: str
    priority: str
    component: str
    resolution_type: str
    closed_at: str
    age_days: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.path.name,
            "closure_id": self.closure_id,
            "resolution_id": self.resolution_id,
            "case_id": self.case_id,
            "fingerprint": self.fingerprint,
            "priority": self.priority,
            "component": self.component,
            "resolution_type": self.resolution_type,
            "closed_at": self.closed_at,
            "age_days": self.age_days,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class IncidentPreventionPattern:
    fingerprint: str
    component: str
    resolution_type: str
    occurrence_count: int
    priorities: tuple[str, ...]
    case_ids: tuple[str, ...]
    first_closed_at: str
    last_closed_at: str
    risk_score: int
    recurring: bool
    high_risk: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["priorities"] = list(self.priorities)
        payload["case_ids"] = list(self.case_ids)
        return payload


@dataclass(frozen=True)
class IncidentPreventionAction:
    order: int
    code: str
    label: str
    owner: str
    target_days: int
    pattern_fingerprint: str = ""
    automatic: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IncidentPreventionSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    lookback_days: int
    recurrence_threshold: int
    high_risk_threshold: int
    status: str
    status_summary: str
    baseline_allowed: bool
    selected_count: int
    verified_count: int
    rejected_count: int
    ignored_count: int
    recurring_pattern_count: int
    high_risk_pattern_count: int
    sources: tuple[IncidentPreventionSource, ...] = field(default_factory=tuple)
    patterns: tuple[IncidentPreventionPattern, ...] = field(default_factory=tuple)
    gates: tuple[IncidentPreventionGate, ...] = field(default_factory=tuple)
    actions: tuple[IncidentPreventionAction, ...] = field(default_factory=tuple)

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
            "lookback_days": self.lookback_days,
            "recurrence_threshold": self.recurrence_threshold,
            "high_risk_threshold": self.high_risk_threshold,
            "status": self.status,
            "status_summary": self.status_summary,
            "baseline_allowed": self.baseline_allowed,
            "selected_count": self.selected_count,
            "verified_count": self.verified_count,
            "rejected_count": self.rejected_count,
            "ignored_count": self.ignored_count,
            "recurring_pattern_count": self.recurring_pattern_count,
            "high_risk_pattern_count": self.high_risk_pattern_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "sources": [source.to_dict() for source in self.sources],
            "patterns": [pattern.to_dict() for pattern in self.patterns],
            "gates": [gate.to_dict() for gate in self.gates],
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class IncidentPreventionRecord:
    baseline_id: str
    created_at: str
    baseline_path: Path
    register_path: Path
    source_closure_count: int
    pattern_count: int
    recurring_pattern_count: int
    high_risk_pattern_count: int
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["baseline_path"] = str(self.baseline_path)
        payload["register_path"] = str(self.register_path)
        return payload
