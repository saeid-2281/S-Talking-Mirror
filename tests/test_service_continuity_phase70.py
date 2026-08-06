from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from app.config.runtime import RuntimeConfig
from app.models.service_continuity import ServiceContinuityDrillRecord
from app.services.service_continuity_service import ServiceContinuityService


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _runtime(root: Path) -> RuntimeConfig:
    runtime = RuntimeConfig(
        app_root=root,
        data_dir=root / "data",
        database_path=root / "data" / "s_talking.db",
        legacy_database_path=root / "data" / "s-talking.db",
        settings_path=root / "settings" / "settings.json",
        log_dir=root / "logs",
        cache_dir=root / "cache",
        default_output_dir=root / "output",
        reports_dir=root / "reports",
        artifacts_dir=root / "artifacts",
        resource_dir=root,
    )
    runtime.ensure_directories()
    return runtime


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Mapping[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


class _FakeRenewalService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self.root = runtime.artifacts_dir / "reliability-assurance-renewal"
        self.renewals_dir = self.root / "renewals"
        self.follow_up_dir = self.root / "follow-up"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        for path in (
            self.renewals_dir,
            self.follow_up_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def verify_renewal(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "Renewal is unreadable."
        expected = str(payload.pop("renewal_sha256", ""))
        if expected != _digest(payload):
            return False, "Renewal SHA-256 does not match."
        if payload.get("status") != "verified":
            return False, "Renewal is not verified."
        if payload.get("human_renewal_completed") is not True:
            return False, "Renewal lacks human acknowledgement."
        return True, "Renewal is intact."

    def verify_follow_up(self, path: Path) -> tuple[bool, str]:
        payload = self._read(path)
        if payload is None:
            return False, "Follow-up is unreadable."
        expected = str(payload.pop("follow_up_sha256", ""))
        if expected != _digest(payload):
            return False, "Follow-up SHA-256 does not match."
        if payload.get("human_follow_up_reviewed") is not True:
            return False, "Follow-up lacks human review."
        if payload.get("status") not in {"open", "not_required"}:
            return False, "Follow-up status is invalid."
        return True, "Follow-up is intact."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        receipt = self._read(receipt_path)
        if receipt is None or not pack_path.is_file():
            return False, "Pack or receipt is missing."
        expected = str(receipt.pop("receipt_sha256", ""))
        if expected != _digest(receipt):
            return False, "Receipt SHA-256 does not match."
        if receipt.get("pack_filename") != pack_path.name:
            return False, "Pack filename changed."
        if int(receipt.get("pack_size_bytes") or -1) != pack_path.stat().st_size:
            return False, "Pack size changed."
        if receipt.get("pack_sha256") != _sha256(pack_path):
            return False, "Pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack_path) as archive:
                required = {"renewal/record.json", "renewal/follow-up.json"}
                if not required.issubset(archive.namelist()):
                    return False, "Pack is incomplete."
        except zipfile.BadZipFile:
            return False, "Pack is unreadable."
        return True, "Pack is intact."

    @staticmethod
    def _read(path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


class _FakeUpgradeRecoveryService:
    MANIFEST_NAME = "upgrade-backup-manifest.json"

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.root = runtime.artifacts_dir / "upgrade-recovery"
        self.root.mkdir(parents=True, exist_ok=True)

    def verify_backup(self, backup_dir: Path) -> tuple[bool, str]:
        manifest_path = Path(backup_dir) / self.MANIFEST_NAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "Backup manifest is unreadable."
        if not isinstance(manifest, dict):
            return False, "Backup manifest is invalid."
        expected = str(manifest.pop("manifest_sha256", ""))
        if expected != _digest(manifest):
            return False, "Backup manifest SHA-256 does not match."
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            return False, "Backup manifest has no files."
        for item in files:
            if not isinstance(item, dict):
                return False, "Backup file record is invalid."
            path = Path(backup_dir) / str(item.get("relative_path") or "")
            if not path.is_file():
                return False, "Backup payload is missing."
            if int(item.get("size_bytes") or -1) != path.stat().st_size:
                return False, "Backup payload size changed."
            if item.get("sha256") != _sha256(path):
                return False, "Backup payload SHA-256 changed."
        return True, "Backup is intact."


def _renewal_source(
    service: _FakeRenewalService,
    *,
    suffix: str = "alpha",
    decision: str = "renew",
    follow_up_status: str = "not_required",
) -> tuple[Path, Path, Path, Path]:
    renewal_id = f"renewal-{suffix}"
    renewal_payload: dict[str, object] = {
        "schema_version": 1,
        "renewal_id": renewal_id,
        "created_at": NOW.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "status": "verified",
        "decision": decision,
        "owner": "Reliability lead",
        "statement": "Human verified assurance renewal for continuity planning.",
        "human_renewal_completed": True,
        "private_data_included": False,
    }
    renewal_payload["renewal_sha256"] = _digest(renewal_payload)
    renewal_path = _write(
        service.renewals_dir / f"{renewal_id}.json",
        renewal_payload,
    )

    follow_up_payload: dict[str, object] = {
        "schema_version": 1,
        "follow_up_id": f"follow-up-{suffix}",
        "renewal_id": renewal_id,
        "created_at": NOW.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "status": follow_up_status,
        "owner": "Risk owner" if follow_up_status == "open" else "",
        "items": [{"code": "follow-up"}] if follow_up_status == "open" else [],
        "human_follow_up_reviewed": True,
        "private_data_included": False,
    }
    follow_up_payload["follow_up_sha256"] = _digest(follow_up_payload)
    follow_up_path = _write(
        service.follow_up_dir / f"{renewal_id}-follow-up.json",
        follow_up_payload,
    )

    pack_path = service.audit_packs_dir / f"{renewal_id}-audit-pack.zip"
    with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("renewal/record.json", renewal_path.read_bytes())
        archive.writestr("renewal/follow-up.json", follow_up_path.read_bytes())

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "renewal_id": renewal_id,
        "created_at": NOW.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "pack_filename": pack_path.name,
        "pack_size_bytes": pack_path.stat().st_size,
        "pack_sha256": _sha256(pack_path),
        "entry_count": 2,
        "private_data_included": False,
    }
    receipt_payload["receipt_sha256"] = _digest(receipt_payload)
    receipt_path = _write(
        service.receipts_dir / f"{renewal_id}-receipt.json",
        receipt_payload,
    )
    return renewal_path, follow_up_path, pack_path, receipt_path


def _backup_source(
    service: _FakeUpgradeRecoveryService,
    *,
    suffix: str = "alpha",
    age_days: int = 5,
    database: bool = True,
) -> Path:
    backup_dir = service.root / f"backup-{suffix}"
    relative = "payload/database/s_talking.db" if database else "payload/settings.json"
    payload_path = backup_dir / relative
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(b"sqlite-backup" if database else b"{}")
    files = [
        {
            "role": "database" if database else "settings",
            "relative_path": relative,
            "size_bytes": payload_path.stat().st_size,
            "sha256": _sha256(payload_path),
        }
    ]
    manifest: dict[str, object] = {
        "schema_version": 1,
        "backup_id": f"backup-{suffix}",
        "created_at": (NOW - timedelta(days=age_days)).isoformat(),
        "source_version": "1.0.0",
        "target_version": "1.0.0",
        "files": files,
    }
    manifest["manifest_sha256"] = _digest(manifest)
    _write(backup_dir / service.MANIFEST_NAME, manifest)
    return backup_dir


def _service(
    root: Path,
) -> tuple[ServiceContinuityService, _FakeRenewalService, _FakeUpgradeRecoveryService]:
    runtime = _runtime(root)
    renewal = _FakeRenewalService(runtime)
    recovery = _FakeUpgradeRecoveryService(runtime)
    service = ServiceContinuityService(
        runtime,
        renewal,  # type: ignore[arg-type]
        recovery,  # type: ignore[arg-type]
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    return service, renewal, recovery


def _snapshot(root: Path, *, age_days: int = 5, follow_up: str = "not_required"):
    service, renewal, recovery = _service(root)
    source = _renewal_source(renewal, follow_up_status=follow_up)
    backup = _backup_source(recovery, age_days=age_days)
    snapshot = service.snapshot(
        renewal_paths=(source[0],),
        follow_up_paths=(source[1],),
        audit_pack_paths=(source[2],),
        receipt_paths=(source[3],),
        backup_dirs=(backup,),
    )
    return service, source, backup, snapshot


def test_phase70_verified_renewal_and_backup_are_ready(tmp_path: Path) -> None:
    _service_instance, _source, _backup, snapshot = _snapshot(tmp_path)

    assert snapshot.status == "ready"
    assert snapshot.drill_allowed
    assert snapshot.verified_renewal_count == 1
    assert snapshot.verified_backup_count == 1
    assert snapshot.blocker_count == 0


def test_phase70_open_follow_up_or_stale_backup_requires_follow_up(tmp_path: Path) -> None:
    service, renewal, recovery = _service(tmp_path)
    source = _renewal_source(renewal, follow_up_status="open")
    backup = _backup_source(recovery, age_days=120)

    snapshot = service.snapshot(
        renewal_paths=(source[0],),
        follow_up_paths=(source[1],),
        audit_pack_paths=(source[2],),
        receipt_paths=(source[3],),
        backup_dirs=(backup,),
        drill_window_days=90,
    )

    assert snapshot.status == "ready_with_follow_up"
    assert snapshot.warning_count == 2
    assert snapshot.open_follow_up_count == 1
    assert snapshot.stale_backup_count == 1


def test_phase70_missing_tampered_or_withheld_source_blocks(tmp_path: Path) -> None:
    service, renewal, recovery = _service(tmp_path)
    source = _renewal_source(renewal, decision="withhold_renewal")
    backup = _backup_source(recovery)
    withheld = service.snapshot(
        renewal_paths=(source[0],),
        follow_up_paths=(source[1],),
        audit_pack_paths=(source[2],),
        receipt_paths=(source[3],),
        backup_dirs=(backup,),
    )

    payload = json.loads(source[0].read_text(encoding="utf-8"))
    payload["owner"] = "tampered"
    _write(source[0], payload)
    tampered = service.snapshot(
        renewal_paths=(source[0],),
        follow_up_paths=(source[1],),
        audit_pack_paths=(source[2],),
        receipt_paths=(source[3],),
        backup_dirs=(backup,),
    )

    missing_backup = service.snapshot(
        renewal_paths=(source[0],),
        follow_up_paths=(source[1],),
        audit_pack_paths=(source[2],),
        receipt_paths=(source[3],),
        backup_dirs=(tmp_path / "missing-backup",),
    )

    assert withheld.status == "blocked"
    assert tampered.status == "blocked"
    assert missing_backup.status == "blocked"


def test_phase70_plan_creation_is_dry_run_without_acknowledgement(tmp_path: Path) -> None:
    service, _source, _backup, snapshot = _snapshot(tmp_path)

    result = service.create_drill_plan(
        snapshot,
        owner="Continuity lead",
        environment="isolated_sandbox",
        notes="Prepare a private isolated continuity drill with verified evidence only.",
    )

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"


def test_phase70_plan_is_tamper_evident_and_non_destructive(tmp_path: Path) -> None:
    service, _source, _backup, snapshot = _snapshot(tmp_path)

    result = service.create_drill_plan(
        snapshot,
        owner="Continuity lead",
        environment="isolated_sandbox",
        notes="Prepare a private isolated continuity drill with verified evidence only.",
        acknowledge=True,
    )

    assert isinstance(result, ServiceContinuityDrillRecord)
    ok, detail = service.verify_plan(result.plan_path)
    payload = json.loads(result.plan_path.read_text(encoding="utf-8"))
    assert ok, detail
    assert all(step["automatic"] is False for step in payload["steps"])
    assert payload["automatic_restore"] is False
    assert payload["production_data_modified"] is False


def test_phase70_privacy_material_is_rejected(tmp_path: Path) -> None:
    service, _source, _backup, snapshot = _snapshot(tmp_path)

    result = service.create_drill_plan(
        snapshot,
        owner="Continuity lead",
        environment="isolated_sandbox",
        notes="password=secret and use C:\\Users\\Private\\backup for the drill.",
        acknowledge=True,
    )

    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase70_failed_objective_creates_withheld_attestation(tmp_path: Path) -> None:
    service, _source, _backup, snapshot = _snapshot(tmp_path)
    plan = service.create_drill_plan(
        snapshot,
        owner="Continuity lead",
        environment="isolated_sandbox",
        notes="Prepare a private isolated continuity drill with verified evidence only.",
        acknowledge=True,
    )
    assert isinstance(plan, ServiceContinuityDrillRecord)

    result = service.record_drill_result(
        plan.plan_path,
        actual_restore_minutes=90,
        observed_data_loss_minutes=10,
        database_quick_check="ok",
        manifest_verified=True,
        regression_test_count=25,
        failed_test_count=0,
        owner="Continuity lead",
        conclusion="The recovery completed safely but exceeded the approved recovery time objective.",
        acknowledge=True,
    )

    assert isinstance(result, ServiceContinuityDrillRecord)
    assert result.outcome == "failed"
    attestation = json.loads(result.attestation_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    assert attestation["status"] == "withheld"
    assert service.verify_result(result.result_path)[0]  # type: ignore[arg-type]


def test_phase70_successful_drill_creates_verified_audit_chain(tmp_path: Path) -> None:
    service, _source, _backup, snapshot = _snapshot(tmp_path)
    plan = service.create_drill_plan(
        snapshot,
        owner="Continuity lead",
        environment="isolated_sandbox",
        notes="Prepare a private isolated continuity drill with verified evidence only.",
        acknowledge=True,
    )
    assert isinstance(plan, ServiceContinuityDrillRecord)

    result = service.record_drill_result(
        plan.plan_path,
        actual_restore_minutes=35,
        observed_data_loss_minutes=20,
        database_quick_check="ok",
        manifest_verified=True,
        regression_test_count=25,
        failed_test_count=0,
        owner="Continuity lead",
        conclusion="The isolated recovery met both objectives and all approved integrity checks passed.",
        acknowledge=True,
    )

    assert isinstance(result, ServiceContinuityDrillRecord)
    assert result.outcome == "passed"
    assert service.verify_result(result.result_path)[0]  # type: ignore[arg-type]
    assert service.verify_attestation(result.attestation_path)[0]  # type: ignore[arg-type]
    assert service.verify_audit_pack(result.audit_pack_path, result.receipt_path)[0]  # type: ignore[arg-type]


def test_phase70_tampering_breaks_result_and_pack_verification(tmp_path: Path) -> None:
    service, _source, _backup, snapshot = _snapshot(tmp_path)
    plan = service.create_drill_plan(
        snapshot,
        owner="Continuity lead",
        environment="isolated_sandbox",
        notes="Prepare a private isolated continuity drill with verified evidence only.",
        acknowledge=True,
    )
    assert isinstance(plan, ServiceContinuityDrillRecord)
    result = service.record_drill_result(
        plan.plan_path,
        actual_restore_minutes=35,
        observed_data_loss_minutes=20,
        database_quick_check="ok",
        manifest_verified=True,
        regression_test_count=25,
        failed_test_count=0,
        owner="Continuity lead",
        conclusion="The isolated recovery met both objectives and all approved integrity checks passed.",
        acknowledge=True,
    )
    assert isinstance(result, ServiceContinuityDrillRecord)

    payload = json.loads(result.result_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    payload["actual_restore_minutes"] = 999
    _write(result.result_path, payload)  # type: ignore[arg-type]

    assert not service.verify_result(result.result_path)[0]  # type: ignore[arg-type]
    assert not service.verify_attestation(result.attestation_path)[0]  # type: ignore[arg-type]

    receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    receipt["pack_size_bytes"] = 1
    _write(result.receipt_path, receipt)  # type: ignore[arg-type]
    assert not service.verify_audit_pack(result.audit_pack_path, result.receipt_path)[0]  # type: ignore[arg-type]

    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app" / "gui" / "dialogs" / "service_continuity_dialog.py").read_text(
        encoding="utf-8"
    )
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app" / "bootstrap.py").read_text(encoding="utf-8")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "service-continuity.ps1").read_text(encoding="utf-8")
    docs = (root / "docs" / "SERVICE_CONTINUITY_PHASE70.md").read_text(encoding="utf-8")

    assert "serviceContinuityDialog" in dialog
    assert "continuityCreatePlanButton" in dialog
    assert "continuityRecordResultButton" in dialog
    assert "service_continuity_service: ServiceContinuityService" in container
    assert "service_continuity_service=services.service_continuity_service" in bootstrap
    assert "Service Continuity & Recovery Drill" in main
    assert "--create-service-continuity-plan" in frozen
    assert "--record-service-continuity-result" in frozen
    assert "ManifestVerified" in script
    assert "never performs" in docs
