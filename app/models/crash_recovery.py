from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CrashRecoveryGate:
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
class CrashReportRecord:
    report_id: str
    created_at: str
    source: str
    severity: str
    exception_type: str
    summary: str
    thread_name: str
    app_version: str
    fingerprint: str
    report_path: Path
    acknowledged: bool = False
    integrity_status: str = "verified"
    safe_mode_recommended: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_path"] = str(self.report_path)
        return payload


@dataclass(frozen=True)
class CrashRecoverySnapshot:
    captured_at: str
    status: str
    summary: str
    session_id: str = ""
    session_started_at: str = ""
    safe_mode: bool = False
    previous_unclean_shutdown: bool = False
    crash_count: int = 0
    unacknowledged_count: int = 0
    integrity_failure_count: int = 0
    queue_recovery_available: bool = False
    session_restore_available: bool = False
    database_status: str = "unknown"
    latest_report_path: Path | None = None
    gates: tuple[CrashRecoveryGate, ...] = field(default_factory=tuple)
    reports: tuple[CrashReportRecord, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(item.severity == "blocker" and not item.passed for item in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" and not item.passed for item in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "session_id": self.session_id,
            "session_started_at": self.session_started_at,
            "safe_mode": self.safe_mode,
            "previous_unclean_shutdown": self.previous_unclean_shutdown,
            "crash_count": self.crash_count,
            "unacknowledged_count": self.unacknowledged_count,
            "integrity_failure_count": self.integrity_failure_count,
            "queue_recovery_available": self.queue_recovery_available,
            "session_restore_available": self.session_restore_available,
            "database_status": self.database_status,
            "latest_report_path": str(self.latest_report_path) if self.latest_report_path else "",
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [item.to_dict() for item in self.gates],
            "reports": [item.to_dict() for item in self.reports],
        }


@dataclass(frozen=True)
class CrashDiagnosticsBundle:
    bundle_id: str
    created_at: str
    path: Path
    report_count: int
    log_count: int
    size_bytes: int
    sha256: str
    status: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload
