from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ReleaseLifecycleGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    action: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseLifecycleSource:
    role: str
    label: str
    relative_path: str
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ReleaseLifecycleSnapshot:
    validation_id: str
    generated_at: str
    version: str
    channel: str
    source_version: str
    status: str
    summary: str
    current_schema: int
    target_schema: int
    update_status: str = "unknown"
    update_artifact: str = ""
    gates: tuple[ReleaseLifecycleGate, ...] = field(default_factory=tuple)
    sources: tuple[ReleaseLifecycleSource, ...] = field(default_factory=tuple)

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
            "validation_id": self.validation_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "source_version": self.source_version,
            "status": self.status,
            "summary": self.summary,
            "current_schema": self.current_schema,
            "target_schema": self.target_schema,
            "update_status": self.update_status,
            "update_artifact": self.update_artifact,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "pass_count": self.pass_count,
            "gates": [item.to_dict() for item in self.gates],
            "sources": [item.to_dict() for item in self.sources],
        }
