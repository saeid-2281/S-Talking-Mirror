from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ServiceContinuityGate:
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
class ServiceContinuityRenewalSource:
    renewal_id: str
    decision: str
    created_at: str
    follow_up_status: str
    renewal_path: Path
    follow_up_path: Path
    audit_pack_path: Path
    receipt_path: Path
    renewal_sha256: str
    follow_up_sha256: str
    audit_pack_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "renewal_path",
            "follow_up_path",
            "audit_pack_path",
            "receipt_path",
        ):
            payload[field_name] = str(payload[field_name])
        return payload


@dataclass(frozen=True)
class ServiceContinuityBackupSource:
    backup_id: str
    backup_name: str
    created_at: str
    age_days: int
    file_count: int
    database_included: bool
    backup_dir: Path
    manifest_path: Path
    manifest_sha256: str
    status: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["backup_dir"] = str(self.backup_dir)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


@dataclass(frozen=True)
class ServiceContinuitySnapshot:
    snapshot_id: str
    generated_at: str
    version: str
    channel: str
    rto_target_minutes: int
    rpo_target_minutes: int
    drill_window_days: int
    status: str
    status_summary: str
    drill_allowed: bool
    selected_renewal_count: int
    selected_follow_up_count: int
    selected_pack_count: int
    selected_receipt_count: int
    selected_backup_count: int
    verified_renewal_count: int
    verified_backup_count: int
    stale_backup_count: int
    open_follow_up_count: int
    withheld_renewal_count: int
    rejected_source_count: int
    renewals: tuple[ServiceContinuityRenewalSource, ...] = field(default_factory=tuple)
    backups: tuple[ServiceContinuityBackupSource, ...] = field(default_factory=tuple)
    gates: tuple[ServiceContinuityGate, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "version": self.version,
            "channel": self.channel,
            "rto_target_minutes": self.rto_target_minutes,
            "rpo_target_minutes": self.rpo_target_minutes,
            "drill_window_days": self.drill_window_days,
            "status": self.status,
            "status_summary": self.status_summary,
            "drill_allowed": self.drill_allowed,
            "selected_renewal_count": self.selected_renewal_count,
            "selected_follow_up_count": self.selected_follow_up_count,
            "selected_pack_count": self.selected_pack_count,
            "selected_receipt_count": self.selected_receipt_count,
            "selected_backup_count": self.selected_backup_count,
            "verified_renewal_count": self.verified_renewal_count,
            "verified_backup_count": self.verified_backup_count,
            "stale_backup_count": self.stale_backup_count,
            "open_follow_up_count": self.open_follow_up_count,
            "withheld_renewal_count": self.withheld_renewal_count,
            "rejected_source_count": self.rejected_source_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "renewals": [source.to_dict() for source in self.renewals],
            "backups": [source.to_dict() for source in self.backups],
            "gates": [gate.to_dict() for gate in self.gates],
        }


@dataclass(frozen=True)
class ServiceContinuityDrillRecord:
    drill_id: str
    created_at: str
    outcome: str
    plan_path: Path
    result_path: Path | None = None
    attestation_path: Path | None = None
    audit_pack_path: Path | None = None
    receipt_path: Path | None = None
    status: str = "planned"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        for field_name in (
            "plan_path",
            "result_path",
            "attestation_path",
            "audit_pack_path",
            "receipt_path",
        ):
            value = payload[field_name]
            payload[field_name] = str(value) if value is not None else ""
        return payload
