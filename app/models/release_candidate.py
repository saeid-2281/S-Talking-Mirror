from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ReleaseCandidateGate:
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
class ReleaseCandidateArtifact:
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
class ReleaseCandidateSnapshot:
    candidate_id: str
    version: str
    release_channel: str
    schema_version: int
    branch: str
    commit: str
    captured_at: str
    status: str
    summary: str
    test_count: int = 0
    package_path: Path | None = None
    manifest_path: Path | None = None
    checksum_path: Path | None = None
    notes_path: Path | None = None
    gates: tuple[ReleaseCandidateGate, ...] = field(default_factory=tuple)
    artifacts: tuple[ReleaseCandidateArtifact, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.severity == "blocker" and item.status != "passed" for item in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" and item.status != "passed" for item in self.gates)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "version": self.version,
            "release_channel": self.release_channel,
            "schema_version": self.schema_version,
            "branch": self.branch,
            "commit": self.commit,
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "test_count": self.test_count,
            "package_path": str(self.package_path) if self.package_path else "",
            "manifest_path": str(self.manifest_path) if self.manifest_path else "",
            "checksum_path": str(self.checksum_path) if self.checksum_path else "",
            "notes_path": str(self.notes_path) if self.notes_path else "",
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [item.to_dict() for item in self.gates],
            "artifacts": [item.to_dict() for item in self.artifacts],
        }
