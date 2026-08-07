from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class EvidenceFreshnessEntry:
    code: str
    label: str
    status: str
    age_days: float | None
    max_age_days: int
    due_soon_days: int
    evidence_filename: str = ""
    evidence_sha256: str = ""
    verification_detail: str = ""
    action_code: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceRefreshSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    project_id: int | None
    overall_status: str
    entries: tuple[EvidenceFreshnessEntry, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    def count(self, status: str) -> int:
        return sum(item.status == status for item in self.entries)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "project_id": self.project_id,
            "overall_status": self.overall_status,
            "fresh_count": self.count("fresh"),
            "due_soon_count": self.count("due_soon"),
            "expired_count": self.count("expired"),
            "missing_count": self.count("missing"),
            "blocked_count": self.count("blocked"),
            "entries": [item.to_dict() for item in self.entries],
            "recommendations": list(self.recommendations),
        }
