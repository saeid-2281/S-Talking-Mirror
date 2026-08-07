from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class OperationalReadinessSource:
    role: str
    label: str
    filename: str
    sha256: str
    verification_detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OperationalReadinessGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    action: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class OperationalReadinessSnapshot:
    certification_id: str
    generated_at: str
    version: str
    channel: str
    source_commit: str
    project_id: int | None
    status: str
    summary: str
    gates: tuple[OperationalReadinessGate, ...] = field(default_factory=tuple)
    sources: tuple[OperationalReadinessSource, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.status == "block" for item in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(item.status == "warn" for item in self.gates)

    @property
    def pass_count(self) -> int:
        return sum(item.status == "pass" for item in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "certification_id": self.certification_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "source_commit": self.source_commit,
            "project_id": self.project_id,
            "status": self.status,
            "summary": self.summary,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "pass_count": self.pass_count,
            "gates": [item.to_dict() for item in self.gates],
            "sources": [item.to_dict() for item in self.sources],
        }
