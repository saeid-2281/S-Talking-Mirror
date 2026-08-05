from __future__ import annotations

import hashlib
import json
import os
import zipfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.incident_support import IncidentSupportBundle
from app.services.crash_recovery_service import CrashRecoveryService
from app.services.incident_support_service import IncidentSupportService
from app.services.post_ga_maintenance_service import PostGaMaintenanceService


NOW = datetime(2026, 8, 5, 18, 30, tzinfo=timezone.utc)
SUMMARY = "Audio generation stops after queue resume while the interface remains responsive."


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


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _baseline(runtime: RuntimeConfig, post_ga: PostGaMaintenanceService) -> Path:
    evidence_root = runtime.artifacts_dir / "phase63-baseline-evidence"
    artifacts = []
    for index in range(3):
        path = _write(evidence_root / f"evidence-{index}.json", {"index": index})
        artifacts.append(
            {
                "role": f"evidence_{index}",
                "path": path.resolve().relative_to(runtime.app_root.resolve()).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha(path),
            }
        )
    payload: dict[str, object] = {
        "schema_version": 1,
        "baseline_id": "post-ga-phase63",
        "created_at": NOW.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "status": "ready",
        "warning_count": 0,
        "evidence_age_days": 0,
        "rollout_percentage": 100,
        "free_space_bytes": 4 * 1024**3,
        "manual_maintenance_required": True,
        "automatic_cleanup": False,
        "automatic_publish": False,
        "automatic_update": False,
        "automatic_restart": False,
        "gates": [],
        "artifacts": artifacts,
        "private_data_included": False,
    }
    payload["baseline_sha256"] = post_ga._payload_digest(payload)
    path = post_ga.default_baseline_path()
    _write(path, payload)
    return path


def _services(
    runtime: RuntimeConfig,
    *,
    free_mb: int = 4096,
) -> tuple[CrashRecoveryService, PostGaMaintenanceService, IncidentSupportService, Path]:
    Usage = namedtuple("usage", "total used free")
    crash = CrashRecoveryService(runtime, now=lambda: NOW)
    post_ga = PostGaMaintenanceService(
        runtime,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )
    baseline = _baseline(runtime, post_ga)
    incident = IncidentSupportService(
        runtime,
        crash,
        post_ga,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
        disk_usage=lambda _path: Usage(10 * 1024**3, 5 * 1024**3, free_mb * 1024**2),
    )
    return crash, post_ga, incident, baseline


def _acknowledged_crash(crash: CrashRecoveryService, message: str = "controlled failure") -> None:
    record = crash.capture_message(message, source="phase63-test")
    assert record is not None
    crash.acknowledge(record.report_id)


def test_phase63_ready_snapshot_verifies_baseline_crash_logs_and_manual_transport(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    crash, _post_ga, service, baseline = _services(runtime)
    _acknowledged_crash(crash)
    (runtime.log_dir / "application.log").write_text("Queue resumed; generation stopped.\n", encoding="utf-8")

    snapshot = service.snapshot(
        summary=SUMMARY,
        severity="high",
        baseline_path=baseline,
    )

    assert snapshot.status == "ready"
    assert snapshot.support_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.baseline_verified
    assert snapshot.crash_count == 1
    assert snapshot.eligible_log_count == 1
    assert {gate.code for gate in snapshot.gates} >= {
        "incident_summary",
        "post_ga_baseline",
        "crash_evidence",
        "privacy_policy",
        "manual_transport",
    }


def test_phase63_blocks_short_secret_summary_invalid_severity_and_identity(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _crash, post_ga, _service, baseline = _services(runtime)
    service = IncidentSupportService(
        runtime,
        post_ga_service=post_ga,
        version="1.0.0-rc1",
        channel="preview",
        now=lambda: NOW,
    )

    snapshot = service.snapshot(
        summary="api_key=sk-private-phase63-secret",
        severity="emergency",
        baseline_path=baseline,
    )

    blocked = {gate.code for gate in snapshot.gates if gate.status == "block"}
    assert {"incident_summary", "incident_severity", "stable_identity"} <= blocked
    assert snapshot.status == "blocked"
    assert not snapshot.support_allowed


def test_phase63_tampered_post_ga_baseline_blocks_support(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _crash, _post_ga, service, baseline = _services(runtime)
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    payload["rollout_percentage"] = 50
    _write(baseline, payload)

    snapshot = service.snapshot(summary=SUMMARY, baseline_path=baseline)

    assert snapshot.status == "blocked"
    assert any(
        gate.code == "post_ga_baseline" and gate.status == "block"
        for gate in snapshot.gates
    )


def test_phase63_tampered_crash_report_blocks_bundle_preparation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    crash, _post_ga, service, baseline = _services(runtime)
    record = crash.capture_message("controlled incident")
    assert record is not None
    payload = json.loads(record.report_path.read_text(encoding="utf-8"))
    payload["summary"] = "modified after capture"
    _write(record.report_path, payload)

    snapshot = service.snapshot(summary=SUMMARY, baseline_path=baseline)

    assert snapshot.integrity_failure_count == 1
    assert snapshot.status == "blocked"
    result = service.create_bundle(snapshot, baseline_path=baseline, acknowledge=True)
    assert isinstance(result, dict)
    assert result["status"] == "blocked"


def test_phase63_bundle_creation_is_dry_run_until_acknowledged(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    crash, _post_ga, service, baseline = _services(runtime)
    _acknowledged_crash(crash)
    snapshot = service.snapshot(
        summary=SUMMARY,
        baseline_path=baseline,
        include_logs=False,
    )

    result = service.create_bundle(
        snapshot,
        baseline_path=baseline,
        include_logs=False,
        acknowledge=False,
    )

    assert isinstance(result, dict)
    assert result["status"] == "dry_run"
    assert not tuple(service.bundles_dir.glob("*.zip"))


def test_phase63_verified_bundle_redacts_logs_and_excludes_private_sources(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    crash, _post_ga, service, baseline = _services(runtime)
    _acknowledged_crash(crash, "Authorization: Bearer crash-secret-token")
    runtime.settings_path.write_text('{"api_key":"sk-settings-secret"}', encoding="utf-8")
    (runtime.settings_path.parent / "api-profiles.json").write_text(
        '{"token":"provider-secret"}', encoding="utf-8"
    )
    runtime.database_path.write_bytes(b"private-database")
    (runtime.default_output_dir / "private.mp3").write_bytes(b"private-audio")
    (runtime.log_dir / "application.log").write_text(
        "Authorization: Bearer support-secret-token\n"
        "api_key=sk-log-private-123456789\n"
        f"Failure at {Path.home() / 'private' / 'file.txt'}\n",
        encoding="utf-8",
    )
    snapshot = service.snapshot(summary=SUMMARY, baseline_path=baseline)

    result = service.create_bundle(
        snapshot,
        baseline_path=baseline,
        acknowledge=True,
    )

    assert isinstance(result, IncidentSupportBundle)
    ok, detail = service.verify_bundle(result.path)
    assert ok, detail
    receipt_ok, receipt_detail = service.verify_receipt(result.receipt_path)
    assert receipt_ok, receipt_detail
    with zipfile.ZipFile(result.path) as archive:
        names = archive.namelist()
        content = b"\n".join(archive.read(name) for name in names).decode(
            "utf-8", errors="ignore"
        )
    lowered = "\n".join(names).casefold()
    assert "settings.json" not in lowered
    assert "api-profiles" not in lowered
    assert ".db" not in lowered
    assert ".mp3" not in lowered
    assert "support-secret-token" not in content
    assert "sk-log-private" not in content
    assert str(Path.home()) not in content
    assert "[REDACTED]" in content
    assert "automatic_upload" in content
    assert '"automatic_upload": false' in content


def test_phase63_bundle_and_receipt_tamper_are_detected(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    crash, _post_ga, service, baseline = _services(runtime)
    _acknowledged_crash(crash)
    snapshot = service.snapshot(summary=SUMMARY, baseline_path=baseline, include_logs=False)
    result = service.create_bundle(
        snapshot,
        baseline_path=baseline,
        include_logs=False,
        acknowledge=True,
    )
    assert isinstance(result, IncidentSupportBundle)

    extracted = tmp_path / "tampered"
    with zipfile.ZipFile(result.path) as archive:
        archive.extractall(extracted)
    summary_path = extracted / "incident" / "summary.json"
    summary_path.write_text(summary_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    tampered_bundle = service.bundles_dir / "tampered.zip"
    with zipfile.ZipFile(tampered_bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(extracted.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(extracted).as_posix())
    ok, detail = service.verify_bundle(tampered_bundle)
    assert not ok
    assert "mismatch" in detail

    receipt_payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
    receipt_payload["report_count"] = 99
    _write(result.receipt_path, receipt_payload)
    receipt_ok, receipt_detail = service.verify_receipt(result.receipt_path)
    assert not receipt_ok
    assert "SHA-256" in receipt_detail


def test_phase63_log_age_inventory_and_bundle_budget_are_bounded(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    crash, _post_ga, service, baseline = _services(runtime)
    _acknowledged_crash(crash)
    old_log = runtime.log_dir / "old.log"
    old_log.write_text("old incident evidence", encoding="utf-8")
    old_timestamp = (NOW - timedelta(days=40)).timestamp()
    os.utime(old_log, (old_timestamp, old_timestamp))
    for index in range(8):
        (runtime.log_dir / f"large-{index}.log").write_text(
            "runtime evidence " * 20_000,
            encoding="utf-8",
        )

    snapshot = service.snapshot(
        summary=SUMMARY,
        baseline_path=baseline,
        max_log_age_days=14,
        max_bundle_mb=1,
    )

    assert snapshot.eligible_log_count == 8
    assert snapshot.estimated_size_bytes > snapshot.max_bundle_bytes
    assert any(
        gate.code == "bundle_budget" and gate.status == "warn"
        for gate in snapshot.gates
    )
    assert old_log not in service._eligible_logs(14)


def test_phase63_ui_container_cli_script_and_no_automatic_transport_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app" / "gui" / "dialogs" / "incident_support_dialog.py").read_text(
        encoding="utf-8"
    )
    service = (root / "app" / "services" / "incident_support_service.py").read_text(
        encoding="utf-8"
    )
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app" / "bootstrap.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "incident-support.ps1").read_text(encoding="utf-8")
    documentation = (root / "docs" / "PRODUCTION_INCIDENT_SUPPORT_PHASE63.md").read_text(
        encoding="utf-8"
    )

    assert 'setObjectName("incidentSupportDialog")' in dialog
    assert "Production Incident Support" in main
    assert "Reports: Production Incident Support" in main
    assert "incident_support_service" in container
    assert "incident_support_service" in bootstrap
    assert "--create-incident-support-bundle" in frozen
    assert "--verify-incident-support-receipt" in frozen
    assert "--acknowledge-incident-support" in script
    assert "never uploads, emails, publishes" in documentation
    assert "automatic_upload\": False" in service
    assert "automatic_send\": False" in service
    assert "generated audio and project sources are excluded" in service
