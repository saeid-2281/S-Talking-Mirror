from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.release_lifecycle_validation_dialog import (
    ReleaseLifecycleValidationDialog,
)
from app.models.update_delivery import UpdatePreferences
from app.services.release_lifecycle_validation_service import (
    ReleaseLifecycleValidationService,
)
from app.services.update_delivery_service import UpdateDeliveryService


class _FinalReleaseStub:
    def verify_final_manifest(self, path: Path) -> tuple[bool, str]:
        return (
            path.read_text(encoding="utf-8") == "manifest-ok",
            "final manifest verified",
        )

    def verify_update_feed(self, path: Path) -> tuple[bool, str]:
        return (
            path.read_text(encoding="utf-8") == "feed-ok",
            "stable feed verified",
        )


class _StableStub:
    RECEIPT_NAME = "stable-release-promotion-receipt.json"

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.root = runtime.artifacts_dir / "stable-promotion"

    def default_final_manifest_path(self) -> Path:
        return (
            self.root.parent
            / "final-release"
            / "latest"
            / "final-release-manifest.json"
        )

    def default_stable_feed_path(self) -> Path:
        return self.root.parent / "update-channel" / "stable" / "latest.json"

    def verify_promotion_receipt(self, path: Path) -> tuple[bool, str]:
        return (
            path.read_text(encoding="utf-8") == "receipt-ok",
            "promotion receipt verified",
        )


class _UpdateStub:
    def __init__(self, *, blocked: bool = False) -> None:
        self.blocked = blocked

    def check_for_updates(self, *_args, **_kwargs):
        return SimpleNamespace(
            blocker_count=1 if self.blocked else 0,
            status="blocked" if self.blocked else "current",
            channel="stable",
            latest_version="1.0.0",
            summary=(
                "verified update client" if not self.blocked else "blocked update client"
            ),
            selected_artifact=(
                None
                if self.blocked
                else SimpleNamespace(filename="S-Talking-1.0.0-portable.zip")
            ),
        )


class _UpgradeStub:
    MANIFEST_NAME = "upgrade-backup-manifest.json"
    target_schema = 23

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        migration_blocked: bool = False,
    ) -> None:
        self.runtime = runtime
        self.migration_blocked = migration_blocked

    def latest_backup_dir(self) -> Path:
        return self.runtime.artifacts_dir / "upgrade-recovery" / "latest"

    def verify_backup(self, path: Path) -> tuple[bool, str]:
        manifest = path / self.MANIFEST_NAME
        return (
            manifest.exists()
            and manifest.read_text(encoding="utf-8") == "backup-ok",
            "backup verified",
        )

    def snapshot(self, **_kwargs):
        return SimpleNamespace(
            blocker_count=0,
            warning_count=0,
            summary="upgrade preflight verified",
            current_schema=23,
            target_schema=23,
        )

    def validate_migration(self, **_kwargs):
        return {
            "status": "blocked" if self.migration_blocked else "ready",
            "detail": (
                "migration blocked"
                if self.migration_blocked
                else "disposable migration ready"
            ),
        }


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path / "project")
    runtime.ensure_directories()
    return runtime


def _evidence(runtime: RuntimeConfig) -> tuple[Path, Path, Path, Path]:
    manifest = (
        runtime.artifacts_dir
        / "final-release"
        / "latest"
        / "final-release-manifest.json"
    )
    feed = runtime.artifacts_dir / "update-channel" / "stable" / "latest.json"
    receipt = (
        runtime.artifacts_dir
        / "stable-promotion"
        / "stable-release-promotion-receipt.json"
    )
    backup = runtime.artifacts_dir / "upgrade-recovery" / "latest"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    feed.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    backup.mkdir(parents=True, exist_ok=True)
    manifest.write_text("manifest-ok", encoding="utf-8")
    feed.write_text("feed-ok", encoding="utf-8")
    receipt.write_text("receipt-ok", encoding="utf-8")
    (backup / "upgrade-backup-manifest.json").write_text(
        "backup-ok",
        encoding="utf-8",
    )
    return manifest, feed, receipt, backup


def _service(
    tmp_path: Path,
    *,
    update_blocked: bool = False,
    migration_blocked: bool = False,
) -> tuple[ReleaseLifecycleValidationService, RuntimeConfig]:
    runtime = _runtime(tmp_path)
    service = ReleaseLifecycleValidationService(
        runtime,
        _FinalReleaseStub(),
        _UpdateStub(blocked=update_blocked),
        _UpgradeStub(runtime, migration_blocked=migration_blocked),
        _StableStub(runtime),
        version="1.0.0",
        channel="stable",
    )
    return service, runtime


def test_phase87_missing_release_chain_is_blocked(tmp_path: Path) -> None:
    service, _runtime_value = _service(tmp_path)
    snapshot = service.assess()
    assert snapshot.status == "blocked"
    assert snapshot.blocker_count >= 4
    assert not snapshot.sources


def test_phase87_verified_release_update_migration_and_backup_are_ready(
    tmp_path: Path,
) -> None:
    service, runtime = _service(tmp_path)
    _evidence(runtime)
    snapshot = service.assess()
    assert snapshot.status == "ready"
    assert snapshot.blocker_count == 0
    assert snapshot.update_status == "current"
    assert snapshot.update_artifact.endswith("portable.zip")
    assert snapshot.current_schema == snapshot.target_schema == 23
    assert len(snapshot.sources) == 4


def test_phase87_tampered_final_manifest_blocks_handoff(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    manifest, _feed, _receipt, _backup = _evidence(runtime)
    manifest.write_text("tampered", encoding="utf-8")
    snapshot = service.assess()
    gate = next(item for item in snapshot.gates if item.code == "final_manifest")
    assert gate.status == "block"
    assert snapshot.status == "blocked"


def test_phase87_update_client_blocker_is_not_hidden(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path, update_blocked=True)
    _evidence(runtime)
    snapshot = service.assess()
    gate = next(item for item in snapshot.gates if item.code == "update_client")
    assert gate.status == "block"
    assert snapshot.status == "blocked"


def test_phase87_verified_backup_is_mandatory_for_recovery_chain(
    tmp_path: Path,
) -> None:
    service, runtime = _service(tmp_path)
    _manifest, _feed, _receipt, backup = _evidence(runtime)
    (backup / "upgrade-backup-manifest.json").unlink()
    snapshot = service.assess()
    assert (
        next(item for item in snapshot.gates if item.code == "verified_backup").status
        == "block"
    )
    assert (
        next(item for item in snapshot.gates if item.code == "rollback_recovery").status
        == "block"
    )


def test_phase87_disposable_migration_blocker_is_not_bypassed(
    tmp_path: Path,
) -> None:
    service, runtime = _service(tmp_path, migration_blocked=True)
    _evidence(runtime)
    snapshot = service.assess()
    assert (
        next(item for item in snapshot.gates if item.code == "disposable_migration").status
        == "block"
    )


def test_phase87_export_verifies_then_detects_source_custody_change(
    tmp_path: Path,
) -> None:
    service, runtime = _service(tmp_path)
    manifest, _feed, _receipt, _backup = _evidence(runtime)
    snapshot = service.assess()
    path = service.export_snapshot(snapshot)
    ok, detail = service.verify_snapshot(path)
    assert ok, detail
    manifest.write_text("changed-after-export", encoding="utf-8")
    ok, detail = service.verify_snapshot(path)
    assert not ok
    assert "custody changed" in detail


def _real_feed(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    artifact = folder / "S-Talking-1.0.0-portable.zip"
    artifact.write_bytes(b"verified portable package")
    notes = folder / "RELEASE-NOTES.md"
    notes.write_text("# Stable release\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "product": "S Talking",
        "channel": "stable",
        "version": "1.0.0",
        "published_at": "2026-08-08T10:00:00Z",
        "rollout_percentage": 100,
        "minimum_supported_version": "0.18.0",
        "critical": False,
        "release_notes_url": notes.name,
        "release_notes_sha256": hashlib.sha256(notes.read_bytes()).hexdigest(),
        "artifacts": [
            {
                "role": "portable_package",
                "filename": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "url": artifact.name,
                "signature_status": "not_applicable",
            }
        ],
    }
    feed = folder / "latest.json"
    feed.write_text(json.dumps(payload), encoding="utf-8")
    (folder / "latest.sha256").write_text(
        f"{hashlib.sha256(feed.read_bytes()).hexdigest()}  latest.json\n",
        encoding="ascii",
    )
    return feed


def test_phase87_update_channel_override_does_not_mutate_user_preferences(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    update = UpdateDeliveryService(
        runtime,
        current_version="1.0.0",
        machine_id="0123456789abcdef0123456789abcdef",
    )
    saved = update.save_preferences(
        UpdatePreferences(channel="preview", feed_url="", prefer_installer=True)
    )
    feed = _real_feed(tmp_path / "stable-feed")
    snapshot = update.check_for_updates(
        feed,
        force=True,
        channel_override="stable",
        prefer_installer_override=False,
    )
    assert snapshot.blocker_count == 0
    assert snapshot.channel == "stable"
    assert snapshot.status == "current"
    assert update.load_preferences() == saved
    assert update.load_preferences().channel == "preview"


def test_phase87_gui_cli_and_safety_contract_are_exposed(
    qt_app,
    tmp_path: Path,
) -> None:
    service, runtime = _service(tmp_path)
    _evidence(runtime)
    dialog = ReleaseLifecycleValidationDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "releaseLifecycleValidationDialog"
    assert dialog.table.rowCount() >= 8
    assert dialog.current_snapshot is not None
    assert dialog.current_snapshot.status == "ready"
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    frozen = Path("app/frozen_main.py").read_text(encoding="utf-8")
    workspace = Path("app/gui/dialogs/operations_workspace_dialog.py").read_text(
        encoding="utf-8"
    )
    assert "Release Lifecycle E2E Validation" in source
    assert "open_release_lifecycle_validation" in source
    assert "--release-lifecycle-validation" in frozen
    assert "release-lifecycle" in workspace
    contract = service._safety_contract()
    assert contract["automatic_download"] is False
    assert contract["automatic_install"] is False
    assert contract["automatic_restore"] is False
    assert contract["automatic_publish"] is False
    dialog.close()
