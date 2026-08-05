from __future__ import annotations

import hashlib
import json
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.post_ga_maintenance_service import PostGaMaintenanceService
from app.services.stable_release_promotion_service import StableReleasePromotionService


NOW = datetime(2026, 8, 5, 17, 30, tzinfo=timezone.utc)


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


def _record(root: Path, role: str, path: Path) -> dict[str, object]:
    return {
        "role": role,
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _stable_chain(
    runtime: RuntimeConfig,
    *,
    created_at: datetime = NOW,
    rollout: int = 100,
) -> tuple[StableReleasePromotionService, Path, Path, Path]:
    stable = StableReleasePromotionService(
        runtime,
        version="1.0.0",
        channel="stable",
        now=lambda: NOW,
    )

    rollback_dir = runtime.artifacts_dir / "stable-promotion" / "rollback-points" / "stable"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    previous = rollback_dir / "previous-release-identity.json"
    _write(previous, {"source_version": "0.18.2-rc1", "target_version": "1.0.0"})
    rollback_payload: dict[str, object] = {
        "schema_version": 1,
        "rollback_id": "rollback-phase62",
        "created_at": created_at.isoformat(),
        "stable_version": "1.0.0",
        "stable_commit": "b" * 40,
        "attested_commit": "a" * 40,
        "automatic_restore": False,
        "automatic_publish": False,
        "artifacts": [
            {
                "role": "previous_release_identity",
                "path": previous.name,
                "size_bytes": previous.stat().st_size,
                "sha256": _sha(previous),
            }
        ],
    }
    rollback_payload["manifest_sha256"] = stable._payload_digest(rollback_payload)
    rollback = _write(rollback_dir / stable.ROLLBACK_MANIFEST_NAME, rollback_payload)

    final_manifest = _write(
        runtime.artifacts_dir / "final-release" / "latest" / "final-release-manifest.json",
        {"version": "1.0.0", "channel": "stable", "artifacts": []},
    )
    attestation = _write(
        runtime.artifacts_dir / "production-certification" / "production-release-attestation.json",
        {"payload": {"target_version": "1.0.0", "source_commit": "a" * 40}},
    )
    sbom = _write(
        runtime.artifacts_dir / "security-supply-chain" / "sbom" / "S-Talking-SBOM.spdx.json",
        {"spdxVersion": "SPDX-2.3", "packages": [{"name": "S Talking"}]},
    )

    feed_dir = runtime.artifacts_dir / "update-channel" / "stable"
    feed_dir.mkdir(parents=True, exist_ok=True)
    package = feed_dir / "S-Talking-1.0.0-portable.zip"
    package.write_bytes(b"stable-package-phase62")
    feed = _write(
        feed_dir / "latest.json",
        {
            "schema_version": 1,
            "product": "S Talking",
            "channel": "stable",
            "version": "1.0.0",
            "published_at": created_at.isoformat(),
            "rollout_percentage": rollout,
            "artifacts": [
                {
                    "role": "portable_package",
                    "filename": package.name,
                    "url": package.name,
                    "size_bytes": package.stat().st_size,
                    "sha256": _sha(package),
                }
            ],
        },
    )
    feed.with_suffix(".sha256").write_text(f"{_sha(feed)}  {feed.name}\n", encoding="ascii")

    receipt_payload: dict[str, object] = {
        "schema_version": 1,
        "promotion_id": "promotion-phase62",
        "created_at": created_at.isoformat(),
        "version": "1.0.0",
        "channel": "stable",
        "source_commit": "b" * 40,
        "attested_commit": "a" * 40,
        "rollout_percentage": rollout,
        "status": "ready",
        "warning_count": 0,
        "manual_publish_required": True,
        "automatic_publish": False,
        "automatic_tag": False,
        "automatic_push": False,
        "automatic_install": False,
        "artifacts": [
            _record(runtime.app_root, "production_attestation", attestation),
            _record(runtime.app_root, "rollback_manifest", rollback),
            _record(runtime.app_root, "final_release_manifest", final_manifest),
            _record(runtime.app_root, "stable_update_feed", feed),
            _record(runtime.app_root, "spdx_sbom", sbom),
        ],
    }
    receipt_payload["receipt_sha256"] = stable._payload_digest(receipt_payload)
    receipt = _write(
        runtime.artifacts_dir / "stable-promotion" / stable.RECEIPT_NAME,
        receipt_payload,
    )
    return stable, receipt, feed, rollback


def _service(
    runtime: RuntimeConfig,
    stable: StableReleasePromotionService,
    *,
    now: datetime = NOW,
    free_mb: int = 4096,
) -> PostGaMaintenanceService:
    Usage = namedtuple("usage", "total used free")
    return PostGaMaintenanceService(
        runtime,
        stable,
        version="1.0.0",
        channel="stable",
        now=lambda: now,
        disk_usage=lambda _path: Usage(10 * 1024**3, 5 * 1024**3, free_mb * 1024**2),
    )


def test_phase62_ready_snapshot_verifies_stable_chain_runtime_and_privacy(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime)
    service = _service(runtime, stable)

    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
    )

    assert snapshot.status == "ready"
    assert snapshot.maintenance_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.rollout_percentage == 100
    assert {artifact.role for artifact in snapshot.artifacts} == {
        "stable_promotion_receipt",
        "stable_update_feed",
        "stable_rollback_manifest",
    }


def test_phase62_blocks_tampered_promotion_receipt_and_rollback(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime)
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    receipt_payload["warning_count"] = 99
    _write(receipt, receipt_payload)
    rollback_payload = json.loads(rollback.read_text(encoding="utf-8"))
    rollback_payload["stable_commit"] = "c" * 40
    _write(rollback, rollback_payload)
    service = _service(runtime, stable)

    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
    )

    blocked = {gate.code for gate in snapshot.gates if gate.status == "block"}
    assert {"promotion_receipt", "rollback_manifest"} <= blocked
    assert snapshot.status == "blocked"
    assert not snapshot.maintenance_allowed


def test_phase62_blocks_tampered_feed_and_invalid_stable_identity(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime)
    feed.write_text(feed.read_text(encoding="utf-8") + " ", encoding="utf-8")
    service = PostGaMaintenanceService(
        runtime,
        stable,
        version="1.0.0-rc1",
        channel="preview",
        now=lambda: NOW,
    )

    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
    )

    blocked = {gate.code for gate in snapshot.gates if gate.status == "block"}
    assert {"stable_identity", "stable_update_feed"} <= blocked


def test_phase62_evidence_freshness_warns_then_blocks_at_hard_limit(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    created = NOW - timedelta(days=40)
    stable, receipt, feed, rollback = _stable_chain(runtime, created_at=created)
    warning_service = _service(runtime, stable, now=NOW)
    warning = warning_service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
        max_evidence_age_days=30,
    )
    assert warning.status == "ready_with_warnings"
    assert next(gate for gate in warning.gates if gate.code == "evidence_freshness").status == "warn"

    blocked_service = _service(runtime, stable, now=created + timedelta(days=91))
    blocked = blocked_service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
        max_evidence_age_days=30,
    )
    assert next(gate for gate in blocked.gates if gate.code == "evidence_freshness").status == "block"
    assert blocked.status == "blocked"


def test_phase62_partial_rollout_warns_and_low_disk_blocks(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime, rollout=25)
    service = _service(runtime, stable, free_mb=128)

    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
        minimum_free_space_mb=512,
        expected_rollout_percentage=100,
    )

    by_code = {gate.code: gate for gate in snapshot.gates}
    assert by_code["stable_rollout"].status == "warn"
    assert by_code["free_space"].status == "block"
    assert snapshot.status == "blocked"


def test_phase62_baseline_requires_acknowledgement_and_is_tamper_evident(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime)
    service = _service(runtime, stable)
    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
    )

    dry_run = service.write_baseline(snapshot)
    assert dry_run["status"] == "dry_run"

    result = service.write_baseline(snapshot, acknowledge=True)
    baseline = Path(str(result["path"]))
    ok, detail = service.verify_baseline(baseline)
    assert result["status"] == "verified"
    assert ok, detail
    text = baseline.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert '"automatic_cleanup": false' in text
    document = json.loads(text)
    document["warning_count"] = 99
    _write(baseline, document)
    ok, detail = service.verify_baseline(baseline)
    assert not ok
    assert "SHA-256" in detail


def test_phase62_maintenance_plan_is_manual_privacy_safe_and_tamper_evident(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime)
    service = _service(runtime, stable)
    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
    )
    baseline_result = service.write_baseline(snapshot, acknowledge=True)
    baseline = Path(str(baseline_result["path"]))

    dry_run = service.prepare_maintenance_plan(snapshot, baseline_path=baseline)
    assert dry_run["status"] == "dry_run"

    result = service.prepare_maintenance_plan(
        snapshot,
        baseline_path=baseline,
        acknowledge=True,
    )
    plan = Path(str(result["path"]))
    ok, detail = service.verify_maintenance_plan(plan)
    assert result["status"] == "prepared"
    assert ok, detail
    document = json.loads(plan.read_text(encoding="utf-8"))
    assert len(document["actions"]) == 5
    assert all(action["automatic"] is False for action in document["actions"])
    assert str(tmp_path) not in plan.read_text(encoding="utf-8")
    document["automatic_cleanup"] = True
    _write(plan, document)
    ok, detail = service.verify_maintenance_plan(plan)
    assert not ok
    assert "SHA-256" in detail or "manual-operation" in detail


def test_phase62_privacy_gate_blocks_secret_bearing_stable_evidence(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    stable, receipt, feed, rollback = _stable_chain(runtime)
    payload = json.loads(feed.read_text(encoding="utf-8"))
    payload["api_key"] = "xi_phase62_secret_value_123456"
    _write(feed, payload)
    feed.with_suffix(".sha256").write_text(f"{_sha(feed)}  {feed.name}\n", encoding="ascii")
    service = _service(runtime, stable)

    snapshot = service.snapshot(
        promotion_receipt_path=receipt,
        stable_feed_path=feed,
        rollback_manifest_path=rollback,
    )

    privacy = next(gate for gate in snapshot.gates if gate.code == "privacy_contract")
    assert privacy.status == "block"
    assert snapshot.status == "blocked"


def test_phase62_dialog_cli_container_and_documentation_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    dialog = (root / "app" / "gui" / "dialogs" / "post_ga_maintenance_dialog.py").read_text(
        encoding="utf-8"
    )
    service = (root / "app" / "services" / "post_ga_maintenance_service.py").read_text(
        encoding="utf-8"
    )
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    bootstrap = (root / "app" / "bootstrap.py").read_text(encoding="utf-8")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "post-ga-maintenance.ps1").read_text(encoding="utf-8")
    docs = (root / "docs" / "POST_GA_MAINTENANCE_PHASE62.md").read_text(encoding="utf-8")

    assert "postGaMaintenanceDialog" in dialog
    assert "automatic_cleanup" in service and "automatic_restart" in service
    assert "post_ga_maintenance_service" in container
    assert "post_ga_maintenance_service" in bootstrap
    assert "Post-GA Maintenance" in main
    assert "--post-ga-maintenance-snapshot" in frozen
    assert "--write-post-ga-baseline" in script
    assert "Phase 62" in docs
