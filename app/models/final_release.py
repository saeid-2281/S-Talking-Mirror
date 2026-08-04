from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FinalReleaseGate:
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
class SigningEvidence:
    role: str
    path: Path | None
    status: str
    sha256: str = ""
    subject: str = ""
    thumbprint: str = ""
    timestamped: bool = False
    detail: str = ""

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path) if self.path else ""
        return payload


@dataclass(frozen=True)
class UpdateArtifact:
    role: str
    filename: str
    size_bytes: int
    sha256: str
    url: str
    signature_status: str = "not_applicable"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FinalReleaseArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str
    signature_status: str = "not_applicable"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class FinalReleaseSnapshot:
    release_id: str
    version: str
    channel: str
    captured_at: str
    status: str
    summary: str
    source_distribution: Path | None = None
    bundle_dir: Path | None = None
    update_feed: Path | None = None
    rollout_percentage: int = 100
    gates: tuple[FinalReleaseGate, ...] = field(default_factory=tuple)
    signatures: tuple[SigningEvidence, ...] = field(default_factory=tuple)
    artifacts: tuple[FinalReleaseArtifact, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.severity == "blocker" and not item.passed for item in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" and not item.passed for item in self.gates)

    @property
    def ready(self) -> bool:
        return self.status in {"ready", "ready_with_warnings"}

    @property
    def installer_signed(self) -> bool:
        return any(item.role == "windows_installer" and item.verified for item in self.signatures)

    @property
    def executable_signed(self) -> bool:
        return any(item.role == "application_executable" and item.verified for item in self.signatures)

    def to_dict(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "version": self.version,
            "channel": self.channel,
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "source_distribution": str(self.source_distribution) if self.source_distribution else "",
            "bundle_dir": str(self.bundle_dir) if self.bundle_dir else "",
            "update_feed": str(self.update_feed) if self.update_feed else "",
            "rollout_percentage": self.rollout_percentage,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "installer_signed": self.installer_signed,
            "executable_signed": self.executable_signed,
            "gates": [item.to_dict() for item in self.gates],
            "signatures": [item.to_dict() for item in self.signatures],
            "artifacts": [item.to_dict() for item in self.artifacts],
        }
