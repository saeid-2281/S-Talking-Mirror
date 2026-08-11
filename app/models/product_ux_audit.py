from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ProductUXEvidence:
    code: str
    label: str
    status: str
    importance: str
    relative_path: str
    detail: str
    action: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductUXJourney:
    journey_id: str
    label: str
    stage: str
    score: int
    status: str
    summary: str
    evidence: tuple[ProductUXEvidence, ...] = field(default_factory=tuple)

    @property
    def required_gap_count(self) -> int:
        return sum(item.status == "missing" and item.importance == "required" for item in self.evidence)

    @property
    def opportunity_count(self) -> int:
        return sum(item.status == "missing" and item.importance == "opportunity" for item in self.evidence)

    def to_dict(self) -> dict[str, object]:
        return {
            "journey_id": self.journey_id,
            "label": self.label,
            "stage": self.stage,
            "score": self.score,
            "status": self.status,
            "summary": self.summary,
            "required_gap_count": self.required_gap_count,
            "opportunity_count": self.opportunity_count,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class ProductUXBacklogItem:
    priority: int
    journey_id: str
    journey_label: str
    evidence_code: str
    title: str
    rationale: str
    action: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProductUXAuditSnapshot:
    audit_id: str
    generated_at: str
    source_commit: str
    roadmap: str
    phase: str
    overall_score: int
    status: str
    summary: str
    journeys: tuple[ProductUXJourney, ...] = field(default_factory=tuple)
    backlog: tuple[ProductUXBacklogItem, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.required_gap_count for item in self.journeys)

    @property
    def opportunity_count(self) -> int:
        return sum(item.opportunity_count for item in self.journeys)

    @property
    def ready_journey_count(self) -> int:
        return sum(item.status == "ready" for item in self.journeys)

    def to_dict(self) -> dict[str, object]:
        return {
            "audit_id": self.audit_id,
            "generated_at": self.generated_at,
            "source_commit": self.source_commit,
            "roadmap": self.roadmap,
            "phase": self.phase,
            "overall_score": self.overall_score,
            "status": self.status,
            "summary": self.summary,
            "blocker_count": self.blocker_count,
            "opportunity_count": self.opportunity_count,
            "ready_journey_count": self.ready_journey_count,
            "journeys": [item.to_dict() for item in self.journeys],
            "backlog": [item.to_dict() for item in self.backlog],
        }
