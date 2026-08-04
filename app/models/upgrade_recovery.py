from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class UpgradeGate:
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
class UpgradeArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str = ""
    status: str = "verified"
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class UpgradeSnapshot:
    operation_id: str
    captured_at: str
    source_version: str
    target_version: str
    mode: str
    status: str
    summary: str
    source_root: Path | None = None
    target_root: Path | None = None
    backup_dir: Path | None = None
    current_schema: int = 0
    target_schema: int = 0
    migration_required: bool = False
    rollback: bool = False
    gates: tuple[UpgradeGate, ...] = field(default_factory=tuple)
    artifacts: tuple[UpgradeArtifact, ...] = field(default_factory=tuple)

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
            "operation_id": self.operation_id,
            "captured_at": self.captured_at,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "mode": self.mode,
            "status": self.status,
            "summary": self.summary,
            "source_root": str(self.source_root) if self.source_root else "",
            "target_root": str(self.target_root) if self.target_root else "",
            "backup_dir": str(self.backup_dir) if self.backup_dir else "",
            "current_schema": self.current_schema,
            "target_schema": self.target_schema,
            "migration_required": self.migration_required,
            "rollback": self.rollback,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [item.to_dict() for item in self.gates],
            "artifacts": [item.to_dict() for item in self.artifacts],
        }
