from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DistributionGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DistributionArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str
    status: str = "verified"
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class DistributionSnapshot:
    distribution_id: str
    version: str
    release_channel: str
    captured_at: str
    status: str
    summary: str
    source_candidate: Path | None = None
    bundle_dir: Path | None = None
    installer_available: bool = False
    installer_distributable: bool = False
    gates: tuple[DistributionGate, ...] = field(default_factory=tuple)
    artifacts: tuple[DistributionArtifact, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.severity == "blocker" and not item.passed for item in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" and not item.passed for item in self.gates)

    @property
    def ready(self) -> bool:
        return self.status in {"ready", "ready_with_warnings"}

    def to_dict(self) -> dict[str, object]:
        return {
            "distribution_id": self.distribution_id,
            "version": self.version,
            "release_channel": self.release_channel,
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "source_candidate": str(self.source_candidate) if self.source_candidate else "",
            "bundle_dir": str(self.bundle_dir) if self.bundle_dir else "",
            "installer_available": self.installer_available,
            "installer_distributable": self.installer_distributable,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [item.to_dict() for item in self.gates],
            "artifacts": [item.to_dict() for item in self.artifacts],
        }
