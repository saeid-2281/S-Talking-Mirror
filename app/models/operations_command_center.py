from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class OperationsDomainStatus:
    code: str
    label: str
    status: str
    headline: str
    metric: str
    detail: str
    evidence_filename: str = ""
    evidence_sha256: str = ""
    action_code: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OperationsCommandSnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    project_id: int | None
    overall_status: str
    status_summary: str
    domains: tuple[OperationsDomainStatus, ...] = field(default_factory=tuple)
    recommendations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def healthy_count(self) -> int:
        return sum(item.status == "healthy" for item in self.domains)

    @property
    def warning_count(self) -> int:
        return sum(item.status == "warning" for item in self.domains)

    @property
    def critical_count(self) -> int:
        return sum(item.status == "critical" for item in self.domains)

    @property
    def unknown_count(self) -> int:
        return sum(item.status == "unknown" for item in self.domains)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "project_id": self.project_id,
            "overall_status": self.overall_status,
            "status_summary": self.status_summary,
            "healthy_count": self.healthy_count,
            "warning_count": self.warning_count,
            "critical_count": self.critical_count,
            "unknown_count": self.unknown_count,
            "domains": [item.to_dict() for item in self.domains],
            "recommendations": list(self.recommendations),
        }
