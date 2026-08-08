from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class FinalProductionCertificationGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    action: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FinalProductionCertificationSource:
    role: str
    label: str
    relative_path: str
    sha256: str
    required: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FinalProductionCertificationSnapshot:
    certification_id: str
    generated_at: str
    version: str
    channel: str
    schema_version: int
    source_commit: str
    status: str
    summary: str
    minimum_test_count: int
    observed_test_count: int
    gates: tuple[FinalProductionCertificationGate, ...] = field(default_factory=tuple)
    sources: tuple[FinalProductionCertificationSource, ...] = field(default_factory=tuple)

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
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "status": self.status,
            "summary": self.summary,
            "minimum_test_count": self.minimum_test_count,
            "observed_test_count": self.observed_test_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "pass_count": self.pass_count,
            "gates": [item.to_dict() for item in self.gates],
            "sources": [item.to_dict() for item in self.sources],
        }
