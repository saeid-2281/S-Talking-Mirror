from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.update_delivery_dialog import UpdateDeliveryDialog
from app.models.update_delivery import UpdatePreferences
from app.services.final_release_service import FinalReleaseService
from app.services.update_delivery_service import UpdateDeliveryService


class _DistributionStub:
    def latest_distribution_dir(self) -> Path:
        return Path("missing")


def _runtime(tmp_path: Path) -> RuntimeConfig:
    root = tmp_path / "project"
    root.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeConfig.from_root(root)
    runtime.ensure_directories()
    return runtime


def _service(
    tmp_path: Path,
    *,
    current_version: str = "0.18.2-rc1",
    machine_id: str = "0123456789abcdef0123456789abcdef",
    signature_verifier=None,
) -> UpdateDeliveryService:
    return UpdateDeliveryService(
        _runtime(tmp_path),
        current_version=current_version,
        machine_id=machine_id,
        signature_verifier=signature_verifier,
    )


def _feed(
    folder: Path,
    *,
    channel: str = "preview",
    version: str = "0.18.2",
    rollout: int = 100,
    role: str = "portable_package",
    filename: str | None = None,
    signature_status: str = "not_applicable",
    unsafe_url: str | None = None,
) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    filename = filename or (
        f"S-Talking-{version}-setup.exe"
        if role == "windows_installer"
        else f"S-Talking-{version}-portable.zip"
    )
    artifact = folder / filename
    artifact.write_bytes(
        (b"MZ" + b"\0" * 8190)
        if role == "windows_installer"
        else b"verified portable package"
    )
    notes = folder / "RELEASE-NOTES.md"
    notes.write_text("# S Talking update\n\n- Verified delivery.\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "product": "S Talking",
        "channel": channel,
        "version": version,
        "published_at": "2026-08-04T10:00:00Z",
        "rollout_percentage": rollout,
        "minimum_supported_version": "0.18.0",
        "critical": False,
        "release_notes_url": notes.name,
        "release_notes_sha256": hashlib.sha256(notes.read_bytes()).hexdigest(),
        "artifacts": [
            {
                "role": role,
                "filename": filename,
                "size_bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "url": unsafe_url if unsafe_url is not None else filename,
                "signature_status": signature_status,
            }
        ],
    }
    feed = folder / "latest.json"
    feed.write_text(json.dumps(payload), encoding="utf-8")
    (folder / "latest.sha256").write_text(
        f"{hashlib.sha256(feed.read_bytes()).hexdigest()}  latest.json\n",
        encoding="ascii",
    )
    return feed, artifact


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_phase55_preferences_are_user_controlled_and_startup_checks_are_due(tmp_path: Path) -> None:
    service = _service(tmp_path)
    defaults = service.load_preferences()
    assert defaults.enabled
    assert not defaults.check_on_startup
    saved = service.save_preferences(
        UpdatePreferences(
            enabled=True,
            check_on_startup=True,
            channel="beta",
            feed_url=str(tmp_path / "latest.json"),
            check_interval_hours=12,
            prefer_installer=False,
        )
    )
    assert saved.channel == "beta"
    assert service.load_preferences() == saved
    now = datetime(2026, 8, 4, 10, tzinfo=timezone.utc)
    assert service.should_check_on_startup(now)
    service.state_path.write_text(
        json.dumps({"last_checked_at": (now - timedelta(hours=2)).isoformat()}),
        encoding="utf-8",
    )
    assert not service.should_check_on_startup(now)
    windows_path = service.save_preferences(
        UpdatePreferences(channel="preview", feed_url=r"D:\Updates\preview\latest.json")
    )
    assert windows_path.feed_url.startswith("D:")
    disabled = service.save_preferences(UpdatePreferences(enabled=False, channel="preview"))
    assert service.check_for_updates(force=False).status == "disabled"
    assert not disabled.enabled
    assert service._compare_versions("0.18.2", "0.18.2-rc1") > 0
    assert service._is_prerelease("0.18.2-preview1")


def test_phase55_verified_local_feed_reports_available_update_and_notes(tmp_path: Path) -> None:
    service = _service(tmp_path)
    feed, _artifact = _feed(tmp_path / "feed")
    service.save_preferences(
        UpdatePreferences(channel="preview", feed_url=str(feed), prefer_installer=False)
    )
    snapshot = service.check_for_updates()
    assert snapshot.status == "available"
    assert snapshot.latest_version == "0.18.2"
    assert snapshot.eligible
    assert snapshot.selected_artifact is not None
    assert snapshot.selected_artifact.role == "portable_package"
    assert "Verified delivery" in snapshot.release_notes
    assert snapshot.blocker_count == 0
    assert (service.receipt_root / "latest-update-check.json").exists()


def test_phase55_staged_rollout_defers_client_without_overriding_user_choice(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.rollout_bucket = lambda _channel, _version: 99  # type: ignore[method-assign]
    feed, _artifact = _feed(tmp_path / "feed", rollout=10)
    service.save_preferences(UpdatePreferences(channel="preview", feed_url=str(feed)))
    snapshot = service.check_for_updates()
    assert snapshot.status == "deferred"
    assert not snapshot.eligible
    assert snapshot.rollout_bucket == 99
    assert not snapshot.update_available
    assert any(gate.code == "staged_rollout" and not gate.passed for gate in snapshot.gates)


def test_phase55_tampered_feed_and_unsafe_artifact_paths_are_blocked(tmp_path: Path) -> None:
    service = _service(tmp_path)
    feed, _artifact = _feed(tmp_path / "tampered")
    (feed.parent / "latest.sha256").write_text(f"{'0' * 64}  latest.json\n", encoding="ascii")
    service.save_preferences(UpdatePreferences(channel="preview", feed_url=str(feed)))
    tampered = service.check_for_updates()
    assert tampered.status == "blocked"
    assert any(gate.code == "feed_integrity" and not gate.passed for gate in tampered.gates)

    unsafe_feed, _ = _feed(tmp_path / "unsafe", unsafe_url="../package.zip")
    service.save_preferences(UpdatePreferences(channel="preview", feed_url=str(unsafe_feed)))
    unsafe = service.check_for_updates()
    assert unsafe.status == "blocked"
    assert any(gate.code.startswith("artifact_") and not gate.passed for gate in unsafe.gates)
    with pytest.raises(ValueError, match="query strings"):
        service.save_preferences(
            UpdatePreferences(
                channel="preview",
                feed_url="https://updates.example.com/preview/latest.json?token=secret",
            )
        )


def test_phase55_download_verifies_hash_writes_receipt_and_never_installs(tmp_path: Path) -> None:
    service = _service(tmp_path)
    feed, artifact = _feed(tmp_path / "feed")
    service.save_preferences(
        UpdatePreferences(channel="preview", feed_url=str(feed), prefer_installer=False)
    )
    snapshot = service.check_for_updates()
    downloaded = service.download_update(snapshot)
    assert downloaded.downloaded_path is not None
    assert downloaded.downloaded_path.read_bytes() == artifact.read_bytes()
    receipts = list(service.receipt_root.glob("download-*.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "verified"
    assert "Installation was not started" in receipt["detail"]
    plan = service.install_plan(downloaded)
    assert plan["allowed"] is True
    assert plan["automatic_restart"] is False
    assert plan["command"][0] == "explorer.exe"


def test_phase55_installer_requires_local_authenticode_verification(tmp_path: Path) -> None:
    feed, _artifact = _feed(
        tmp_path / "feed",
        role="windows_installer",
        signature_status="verified",
    )
    rejected = _service(
        tmp_path / "rejected",
        signature_verifier=lambda _path: (False, "NotSigned"),
    )
    rejected.save_preferences(UpdatePreferences(channel="preview", feed_url=str(feed)))
    with pytest.raises(RuntimeError, match="Authenticode"):
        rejected.download_update(rejected.check_for_updates())

    accepted = _service(
        tmp_path / "accepted",
        signature_verifier=lambda _path: (True, "Valid and timestamped"),
    )
    accepted.save_preferences(UpdatePreferences(channel="preview", feed_url=str(feed)))
    downloaded = accepted.download_update(accepted.check_for_updates())
    plan = accepted.install_plan(downloaded)
    assert plan["allowed"] is True
    assert plan["requires_confirmation"] is True
    assert plan["automatic_restart"] is False
    assert str(plan["command"][0]).endswith(".exe")


def test_phase55_published_channel_feed_carries_verified_release_notes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    service = FinalReleaseService(
        runtime,
        _DistributionStub(),  # type: ignore[arg-type]
        version="0.18.2-rc1",
        release_channel="rc",
    )
    source = tmp_path / "bundle"
    source.mkdir()
    portable = source / "S-Talking-0.18.2-rc1-portable.zip"
    portable.write_bytes(b"package")
    notes = source / "RELEASE-NOTES.md"
    notes.write_text("# Notes", encoding="utf-8")
    feed = source / "S-Talking-preview.json"
    feed.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "S Talking",
                "channel": "preview",
                "version": "0.18.2-rc1",
                "release_notes_url": notes.name,
                "release_notes_sha256": hashlib.sha256(notes.read_bytes()).hexdigest(),
                "artifacts": [
                    {
                        "role": "portable_package",
                        "filename": portable.name,
                        "size_bytes": portable.stat().st_size,
                        "sha256": hashlib.sha256(portable.read_bytes()).hexdigest(),
                        "url": portable.name,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service._publish_channel_feed(feed, "preview")
    published = service.latest_channel_feed("preview")
    assert published.exists()
    assert (published.parent / portable.name).exists()
    assert (published.parent / notes.name).read_text(encoding="utf-8") == "# Notes"
    assert published.with_suffix(".sha256").exists()


def test_phase55_dialog_background_controller_and_mainwindow_contract(qt_app, tmp_path: Path) -> None:
    service = _service(tmp_path)
    dialog = UpdateDeliveryDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "updateDeliveryDialog"
    assert dialog.channel.currentText() == "preview"
    assert dialog.download_button.text() == "Download verified update"
    assert "automatic installation" in dialog.workspace.header.subtitle_label.text().casefold()
    assert not dialog.download_button.isEnabled()
    main = Path("app/gui/main.py").read_text(encoding="utf-8")
    controller = Path("app/gui/update_delivery_controller.py").read_text(encoding="utf-8")
    assert "Update Delivery" in main
    assert "check_updates_on_startup" in main
    assert "QThreadPool.globalInstance" in controller
    assert "automatic_restart" in Path("app/services/update_delivery_service.py").read_text(encoding="utf-8")
    dialog.close()
    dialog.deleteLater()
    _drain(qt_app)
