from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProductionCertificationGate:
    gate_id: str
    label: str
    category: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "not_applicable"}

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class ProductionEvidenceArtifact:
    role: str
    path: Path
    status: str
    size_bytes: int
    sha256: str
    captured_at: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = self.path.name
        return payload


@dataclass(frozen=True)
class ProductionCertificationSnapshot:
    certification_id: str
    generated_at: str
    source_version: str
    target_version: str
    source_commit: str
    release_channel: str
    status: str
    summary: str
    expected_test_count: int
    observed_test_count: int
    promotion_allowed: bool
    gates: tuple[ProductionCertificationGate, ...] = field(default_factory=tuple)
    evidence: tuple[ProductionEvidenceArtifact, ...] = field(default_factory=tuple)
    attestation_path: Path | None = None

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "certification_id": self.certification_id,
            "generated_at": self.generated_at,
            "source_version": self.source_version,
            "target_version": self.target_version,
            "source_commit": self.source_commit,
            "release_channel": self.release_channel,
            "status": self.status,
            "summary": self.summary,
            "expected_test_count": self.expected_test_count,
            "observed_test_count": self.observed_test_count,
            "promotion_allowed": self.promotion_allowed,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [gate.to_dict() for gate in self.gates],
            "evidence": [artifact.to_dict() for artifact in self.evidence],
            "attestation_path": self.attestation_path.name if self.attestation_path else "",
        }
