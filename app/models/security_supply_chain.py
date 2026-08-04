from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SecurityGate:
    gate_id: str
    label: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "not_applicable", "not_measured"}

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class SecurityComponent:
    name: str
    version: str
    component_type: str = "library"
    supplier: str = ""
    license_expression: str = "NOASSERTION"
    purl: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SecurityArtifact:
    role: str
    path: Path
    size_bytes: int
    sha256: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = self.path.name
        return payload


@dataclass(frozen=True)
class SecurityAuditReceipt:
    audit_id: str
    created_at: str
    status: str
    report_path: Path
    sha256: str
    package_path: Path | None = None
    issue_count: int = 0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_path"] = self.report_path.name
        payload["package_path"] = self.package_path.name if self.package_path else ""
        return payload


@dataclass(frozen=True)
class SecuritySupplyChainSnapshot:
    captured_at: str
    status: str
    summary: str
    credential_backend: str
    credential_status: str
    component_count: int
    vulnerability_status: str
    package_path: Path | None = None
    gates: tuple[SecurityGate, ...] = field(default_factory=tuple)
    artifacts: tuple[SecurityArtifact, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "credential_backend": self.credential_backend,
            "credential_status": self.credential_status,
            "component_count": self.component_count,
            "vulnerability_status": self.vulnerability_status,
            "package_path": self.package_path.name if self.package_path else "",
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [gate.to_dict() for gate in self.gates],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }
