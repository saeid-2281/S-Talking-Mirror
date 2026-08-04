from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class UpdatePreferences:
    enabled: bool = True
    check_on_startup: bool = False
    channel: str = "preview"
    feed_url: str = ""
    check_interval_hours: int = 24
    prefer_installer: bool = True

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UpdateDeliveryGate:
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
class UpdateDownloadArtifact:
    role: str
    filename: str
    url: str
    size_bytes: int
    sha256: str
    signature_status: str = "not_applicable"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UpdateCheckSnapshot:
    check_id: str
    captured_at: str
    current_version: str
    latest_version: str
    channel: str
    status: str
    summary: str
    feed_source: str = ""
    published_at: str = ""
    rollout_percentage: int = 100
    rollout_bucket: int = 0
    eligible: bool = False
    critical: bool = False
    minimum_supported_version: str = ""
    release_notes: str = ""
    release_notes_url: str = ""
    selected_artifact: UpdateDownloadArtifact | None = None
    downloaded_path: Path | None = None
    gates: tuple[UpdateDeliveryGate, ...] = field(default_factory=tuple)
    artifacts: tuple[UpdateDownloadArtifact, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.severity == "blocker" and not item.passed for item in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" and not item.passed for item in self.gates)

    @property
    def update_available(self) -> bool:
        return self.status == "available" and self.selected_artifact is not None

    @property
    def download_ready(self) -> bool:
        return self.downloaded_path is not None and self.downloaded_path.exists()

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "captured_at": self.captured_at,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "channel": self.channel,
            "status": self.status,
            "summary": self.summary,
            "feed_source": self.feed_source,
            "published_at": self.published_at,
            "rollout_percentage": self.rollout_percentage,
            "rollout_bucket": self.rollout_bucket,
            "eligible": self.eligible,
            "critical": self.critical,
            "minimum_supported_version": self.minimum_supported_version,
            "release_notes": self.release_notes,
            "release_notes_url": self.release_notes_url,
            "selected_artifact": (
                self.selected_artifact.to_dict() if self.selected_artifact else None
            ),
            "downloaded_path": str(self.downloaded_path) if self.downloaded_path else "",
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [item.to_dict() for item in self.gates],
            "artifacts": [item.to_dict() for item in self.artifacts],
        }


@dataclass(frozen=True)
class UpdateDownloadReceipt:
    receipt_id: str
    created_at: str
    check_id: str
    version: str
    channel: str
    artifact_role: str
    artifact_path: Path
    size_bytes: int
    sha256: str
    signature_status: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["artifact_path"] = str(self.artifact_path)
        return payload
