from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PreventionEffectivenessGate:
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
class PreventiveActionState:
    code: str
    label: str
    owner: str
    target_days: int
    pattern_fingerprint: str
    due_at: str
    status: str
    attestation_id: str = ""
    attested_at: str = ""
    evidence_summary: str = ""
    overdue: bool = False
    automatic: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PreventionEffectivenessPattern:
    fingerprint: str
    component: str
    baseline_occurrence_count: int
    post_baseline_occurrence_count: int
    baseline_risk_score: int
    residual_risk_score: int
    new_recurrence: bool
    effectiveness: str
    latest_closed_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PreventionEffectivenessSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    baseline_path: Path
    register_path: Path
    baseline_id: str
    register_id: str
    observation_days: int
    status: str
    status_summary: str
    review_allowed: bool
    selected_closure_count: int
    verified_closure_count: int
    rejected_closure_count: int
    ignored_closure_count: int
    open_action_count: int
    completed_action_count: int
    deferred_action_count: int
    accepted_risk_action_count: int
    overdue_action_count: int
    recurrent_pattern_count: int
    ineffective_pattern_count: int
    actions: tuple[PreventiveActionState, ...] = field(default_factory=tuple)
    patterns: tuple[PreventionEffectivenessPattern, ...] = field(default_factory=tuple)
    gates: tuple[PreventionEffectivenessGate, ...] = field(default_factory=tuple)

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
            "baseline_path": str(self.baseline_path),
            "register_path": str(self.register_path),
            "baseline_id": self.baseline_id,
            "register_id": self.register_id,
            "observation_days": self.observation_days,
            "status": self.status,
            "status_summary": self.status_summary,
            "review_allowed": self.review_allowed,
            "selected_closure_count": self.selected_closure_count,
            "verified_closure_count": self.verified_closure_count,
            "rejected_closure_count": self.rejected_closure_count,
            "ignored_closure_count": self.ignored_closure_count,
            "open_action_count": self.open_action_count,
            "completed_action_count": self.completed_action_count,
            "deferred_action_count": self.deferred_action_count,
            "accepted_risk_action_count": self.accepted_risk_action_count,
            "overdue_action_count": self.overdue_action_count,
            "recurrent_pattern_count": self.recurrent_pattern_count,
            "ineffective_pattern_count": self.ineffective_pattern_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "actions": [action.to_dict() for action in self.actions],
            "patterns": [pattern.to_dict() for pattern in self.patterns],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class PreventionEffectivenessRecord:
    review_id: str
    created_at: str
    review_path: Path
    decision_path: Path
    baseline_id: str
    decision: str
    action_count: int
    pattern_count: int
    status: str = "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["review_path"] = str(self.review_path)
        payload["decision_path"] = str(self.decision_path)
        return payload
