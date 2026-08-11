from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ProviderGACertificationGate:
    code: str
    label: str
    status: str
    severity: str
    detail: str
    action: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderGACertificationSource:
    role: str
    label: str
    relative_path: str
    sha256: str
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderGACertificationSnapshot:
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
    builtin_provider_count: int
    plugin_sdk_api_version: int
    danish_pending_count: int
    active_plugin_count: int
    gates: tuple[ProviderGACertificationGate, ...] = field(default_factory=tuple)
    sources: tuple[ProviderGACertificationSource, ...] = field(default_factory=tuple)

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
            "builtin_provider_count": self.builtin_provider_count,
            "plugin_sdk_api_version": self.plugin_sdk_api_version,
            "danish_pending_count": self.danish_pending_count,
            "active_plugin_count": self.active_plugin_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "pass_count": self.pass_count,
            "gates": [item.to_dict() for item in self.gates],
            "sources": [item.to_dict() for item in self.sources],
        }
