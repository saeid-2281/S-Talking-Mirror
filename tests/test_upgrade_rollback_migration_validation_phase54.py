from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from app.config.runtime import RuntimeConfig
from app.database.connection import Database
from app.gui.dialogs.upgrade_recovery_dialog import UpgradeRecoveryDialog
from app.models.upgrade_recovery import UpgradeArtifact, UpgradeGate, UpgradeSnapshot
from app.release import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION
from app.services.upgrade_recovery_service import UpgradeRecoveryService


def _runtime(tmp_path: Path) -> RuntimeConfig:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    runtime = RuntimeConfig.from_root(root)
    runtime.ensure_directories()
    return runtime


def _service(tmp_path: Path) -> UpgradeRecoveryService:
    runtime = _runtime(tmp_path)
    database = Database(runtime.database_path)
    database.initialize()
    return UpgradeRecoveryService(runtime, database, version="0.18.2-rc1", target_schema=DATABASE_SCHEMA_VERSION)


def _seed_user_state(service: UpgradeRecoveryService) -> None:
    settings_dir = service.runtime.settings_path.parent
    service.runtime.settings_path.write_text(json.dumps({"theme": "Graphite"}), encoding="utf-8")
    (settings_dir / "api-profiles.json").write_text(
        json.dumps({"schema_version": 1, "profiles": [{"profile_id": "safe-profile"}]}),
        encoding="utf-8",
    )
    (settings_dir / "workspace-profiles.json").write_text(
        json.dumps({"profiles": [{"name": "Studio"}]}), encoding="utf-8"
    )
    credentials = settings_dir / "credentials"
    credentials.mkdir(parents=True, exist_ok=True)
    (credentials / "opaque.cred").write_text("encrypted-payload", encoding="ascii")
    dictionaries = settings_dir / "pronunciation-dictionaries"
    dictionaries.mkdir(parents=True, exist_ok=True)
    (dictionaries / "da.json").write_text(json.dumps({"rules": []}), encoding="utf-8")
    (service.runtime.data_dir / "provider-cache.json").write_text("{}", encoding="utf-8")
    (service.runtime.default_output_dir / "keep.mp3").write_bytes(b"audio")
    (service.runtime.log_dir / "private.log").write_text("log", encoding="utf-8")


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_phase54_default_target_schema_uses_application_database_schema(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    database = Database(runtime.database_path)
    database.initialize()
    service = UpgradeRecoveryService(runtime, database, version="0.18.2-rc1")

    assert service.target_schema == DATABASE_SCHEMA_VERSION == 23
    assert service.MANIFEST_SCHEMA_VERSION == 1
    snapshot = service.snapshot(source_version="0.18.2-rc1")
    assert snapshot.current_schema == DATABASE_SCHEMA_VERSION
    assert snapshot.target_schema == DATABASE_SCHEMA_VERSION
    assert snapshot.blocker_count == 0


def test_phase54_models_and_transition_modes_are_deterministic(tmp_path: Path) -> None:
    service = _service(tmp_path)
    portable = tmp_path / "portable"
    portable.mkdir()
    (portable / "portable.mode").write_text("", encoding="ascii")
    snapshot = service.snapshot(source_root=portable)
    assert snapshot.mode == "portable_to_installed"
    assert snapshot.target_schema == DATABASE_SCHEMA_VERSION
    gate = UpgradeGate("code", "Gate", "passed", "blocker", "ok")
    artifact = UpgradeArtifact("manifest", Path("manifest.json"), 10, "f" * 64)
    model = UpgradeSnapshot(
        "id", "now", "0.18.1", "0.18.2-rc1", "in_place", "ready", "ok",
        gates=(gate,), artifacts=(artifact,),
    )
    assert model.ready
    assert model.to_dict()["artifacts"][0]["path"] == "manifest.json"


def test_phase54_healthy_current_schema_is_compatible_but_requests_backup(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.snapshot(source_version="0.18.1")
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.current_schema == DATABASE_SCHEMA_VERSION
    assert not snapshot.migration_required
    assert snapshot.blocker_count == 0
    assert any(gate.code == "pre_upgrade_backup" and not gate.passed for gate in snapshot.gates)


def test_phase54_newer_database_schema_blocks_downgrade(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with sqlite3.connect(service.runtime.database_path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (99, "future"),
        )
    snapshot = service.snapshot(source_version="9.0.0", mode="rollback")
    assert snapshot.status == "blocked"
    assert snapshot.rollback
    assert any(gate.code == "schema_compatibility" and not gate.passed for gate in snapshot.gates)
    result = service.validate_migration(source_version="9.0.0")
    assert result["status"] == "blocked"


def test_phase54_backup_preserves_critical_state_without_outputs_or_logs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _seed_user_state(service)
    snapshot = service.create_backup(source_version="0.18.1")
    assert snapshot.status == "ready"
    assert snapshot.backup_dir is not None
    ok, detail = service.verify_backup(snapshot.backup_dir)
    assert ok, detail
    manifest = json.loads((snapshot.backup_dir / service.MANIFEST_NAME).read_text(encoding="utf-8"))
    roles = {item["role"] for item in manifest["files"]}
    assert {"database", "settings", "api_profiles", "workspace_profiles", "credentials"}.issubset(roles)
    listed = "\n".join(item["relative_path"] for item in manifest["files"])
    assert "keep.mp3" not in listed
    assert "private.log" not in listed
    assert "encrypted-payload" not in json.dumps(manifest)


def test_phase54_backup_manifest_detects_tampering_and_unsafe_paths(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _seed_user_state(service)
    backup = service.create_backup().backup_dir
    assert backup is not None
    settings = backup / "payload" / "settings" / "settings.json"
    settings.write_text("tampered", encoding="utf-8")
    ok, detail = service.verify_backup(backup)
    assert not ok
    assert "integrity mismatch" in detail.casefold() or "size mismatch" in detail.casefold()


def test_phase54_disposable_migration_reaches_target_without_mutating_source(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with sqlite3.connect(service.runtime.database_path) as connection:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = ?",
            (DATABASE_SCHEMA_VERSION,),
        )
    before = service._database_schema(service.runtime.database_path)
    result = service.validate_migration(source_version="0.18.1")
    after_source = service._database_schema(service.runtime.database_path)
    assert before == DATABASE_SCHEMA_VERSION - 1
    assert after_source == DATABASE_SCHEMA_VERSION - 1
    assert result["status"] == "ready"
    assert result["after_schema"] == DATABASE_SCHEMA_VERSION
    assert result["migration_required"] is True
    assert Path(result["result_path"]).exists()


def test_phase54_restore_dry_run_and_acknowledged_restore_are_recoverable(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _seed_user_state(service)
    backup = service.create_backup().backup_dir
    assert backup is not None
    dry_run = service.restore_backup(backup, dry_run=True)
    assert dry_run["status"] == "dry_run"
    service.runtime.settings_path.write_text(json.dumps({"theme": "Light"}), encoding="utf-8")
    with sqlite3.connect(service.runtime.database_path) as connection:
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES(?, ?)",
            (99, "failed-upgrade"),
        )
    with pytest.raises(PermissionError):
        service.restore_backup(backup, dry_run=False)
    restored = service.restore_backup(backup, dry_run=False, acknowledge=True)
    assert restored["status"] == "restored"
    assert Path(restored["safety_backup"]).exists()
    assert "raw forensic state" in restored["detail"].casefold()
    assert json.loads(service.runtime.settings_path.read_text(encoding="utf-8"))["theme"] == "Graphite"
    assert Database(service.runtime.database_path).quick_check() == "ok"


def test_phase54_dialog_script_and_mainwindow_contract_are_exposed(qt_app, tmp_path: Path) -> None:
    service = _service(tmp_path)
    dialog = UpgradeRecoveryDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "upgradeRecoveryDialog"
    assert dialog.mode.currentText() == "auto"
    assert dialog.gate_table.rowCount() >= 8
    assert "actual restore" in dialog.acknowledge_restore.text().casefold()
    main = Path("app/gui/main.py").read_text(encoding="utf-8")
    script = Path("scripts/upgrade-validation.ps1").read_text(encoding="utf-8")
    frozen = Path("app/frozen_main.py").read_text(encoding="utf-8")
    assert "Upgrade & Recovery" in main
    assert "open_upgrade_recovery" in main
    assert "AcknowledgeRestore" in script
    assert "Close every running S-Talking.exe" in script
    assert "--restore-backup" in frozen
    assert "--acknowledge-restore" in frozen
    dialog.close()
    dialog.deleteLater()
    _drain(qt_app)
