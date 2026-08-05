from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class StablePromotionGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class StablePromotionArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str
    status: str = "verified"
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = self.path.name
        return payload


@dataclass(frozen=True)
class StablePromotionSnapshot:
    promotion_id: str
    generated_at: str
    version: str
    channel: str
    source_commit: str
    attested_commit: str
    rollout_percentage: int
    status: str
    summary: str
    promotion_allowed: bool
    gates: tuple[StablePromotionGate, ...] = field(default_factory=tuple)
    artifacts: tuple[StablePromotionArtifact, ...] = field(default_factory=tuple)
    rollback_manifest: Path | None = None
    receipt_path: Path | None = None

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "promotion_id": self.promotion_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "source_commit": self.source_commit,
            "attested_commit": self.attested_commit,
            "rollout_percentage": self.rollout_percentage,
            "status": self.status,
            "summary": self.summary,
            "promotion_allowed": self.promotion_allowed,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [gate.to_dict() for gate in self.gates],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "rollback_manifest": self.rollback_manifest.name if self.rollback_manifest else "",
            "receipt_path": self.receipt_path.name if self.receipt_path else "",
        }
