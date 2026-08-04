from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.final_release_dialog import FinalReleaseDialog
from app.models.final_release import SigningEvidence, UpdateArtifact
from app.services.final_release_service import FinalReleaseService


class _DistributionService:
    MANIFEST_NAME = "distribution-manifest.json"
    CHECKSUM_NAME = "SHA256SUMS.txt"
    RESULT_NAME = "distribution-result.json"

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def latest_distribution_dir(self) -> Path:
        return self.folder

    def verify_distribution_manifest(self, path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for item in payload["artifacts"]:
                artifact = path.parent / Path(item["path"]).name
                if not artifact.exists():
                    return False, f"Missing {artifact.name}"
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                if digest != item["sha256"]:
                    return False, f"SHA mismatch for {artifact.name}"
            return True, "Distribution manifest verified."
        except Exception as exc:
            return False, str(exc)


def _runtime(tmp_path: Path) -> RuntimeConfig:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    runtime = RuntimeConfig.from_root(root)
    runtime.ensure_directories()
    return runtime


def _artifact(role: str, path: Path) -> dict[str, object]:
    return {
        "role": role,
        "path": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": "verified",
        "detail": "",
    }


def _distribution(
    runtime: RuntimeConfig,
    *,
    installer: bool = False,
    signed: bool = False,
) -> tuple[Path, Path, Path | None]:
    folder = runtime.artifacts_dir / "distribution" / "latest"
    folder.mkdir(parents=True, exist_ok=True)
    portable = folder / "S-Talking-0.18.2-rc1-portable.zip"
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("S-Talking.exe", b"MZ" + b"\0" * 8190)
        archive.writestr("portable.mode", b"")
        archive.writestr("RUN.cmd", b"@echo off")
    artifacts = [_artifact("portable_package", portable)]
    installer_path = None
    if installer:
        installer_path = folder / "S-Talking-0.18.2-rc1-setup.exe"
        installer_path.write_bytes(b"MZ" + b"\0" * 8190)
        artifacts.append(_artifact("windows_installer", installer_path))
    notes = folder / "RELEASE-NOTES.md"
    notes.write_text("# Release notes\n", encoding="utf-8")
    artifacts.append(_artifact("release_notes", notes))
    manifest = {
        "schema_version": 1,
        "distribution_id": "dist-phase53",
        "version": "0.18.2-rc1",
        "release_channel": "rc",
        "artifacts": artifacts,
    }
    (folder / _DistributionService.MANIFEST_NAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (folder / _DistributionService.CHECKSUM_NAME).write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in artifacts),
        encoding="ascii",
    )

    package = runtime.artifacts_dir / "package"
    package.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "role": "application_executable",
            "path": str(portable),
            "status": "verified" if signed else "unsigned",
            "sha256": hashlib.sha256(portable.read_bytes()).hexdigest(),
            "subject": "CN=S Talking" if signed else "",
            "thumbprint": "ABC123" if signed else "",
            "timestamped": signed,
            "detail": "Authenticode signature verified." if signed else "Artifact is not signed.",
        },
        {
            "role": "windows_installer",
            "path": str(installer_path) if installer_path else "",
            "status": "verified" if installer and signed else "unsigned" if installer else "unavailable",
            "sha256": hashlib.sha256(installer_path.read_bytes()).hexdigest() if installer_path else "",
            "subject": "CN=S Talking" if installer and signed else "",
            "thumbprint": "ABC123" if installer and signed else "",
            "timestamped": bool(installer and signed),
            "detail": "Authenticode signature verified." if installer and signed else "Installer is unsigned or unavailable.",
        },
    ]
    (package / FinalReleaseService.SIGNING_RESULT_NAME).write_text(
        json.dumps({"schema_version": 1, "artifacts": records}), encoding="utf-8"
    )
    return folder, portable, installer_path


def _service(
    tmp_path: Path,
    *,
    installer: bool = False,
    signed: bool = False,
) -> FinalReleaseService:
    runtime = _runtime(tmp_path)
    folder, _portable, _installer = _distribution(
        runtime, installer=installer, signed=signed
    )
    return FinalReleaseService(
        runtime,
        _DistributionService(folder),
        version="0.18.2-rc1",
        release_channel="rc",
    )


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_phase53_models_serialize_signing_and_update_metadata() -> None:
    evidence = SigningEvidence(
        role="windows_installer",
        path=Path("setup.exe"),
        status="verified",
        thumbprint="ABC",
        timestamped=True,
    )
    artifact = UpdateArtifact(
        role="windows_installer",
        filename="setup.exe",
        size_bytes=10,
        sha256="f" * 64,
        url="setup.exe",
        signature_status="verified",
    )
    assert evidence.verified
    assert evidence.to_dict()["path"] == "setup.exe"
    assert artifact.to_dict()["signature_status"] == "verified"
    assert FinalReleaseService.normalize_channel("rc") == "preview"


def test_phase53_unsigned_portable_release_is_ready_with_warnings(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).snapshot()
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.channel == "preview"
    assert snapshot.blocker_count == 0
    assert not snapshot.executable_signed
    assert not snapshot.installer_signed
    stable = _service(tmp_path / "stable").snapshot(channel="stable")
    assert stable.status == "blocked"
    assert any(
        gate.code == "stable_version_policy" and not gate.passed
        for gate in stable.gates
    )


def test_phase53_signed_installer_and_application_are_ready(tmp_path: Path) -> None:
    snapshot = _service(tmp_path, installer=True, signed=True).snapshot()
    assert snapshot.status == "ready"
    assert snapshot.executable_signed
    assert snapshot.installer_signed
    assert all(item.timestamped for item in snapshot.signatures if item.verified)


def test_phase53_strict_release_rejects_missing_signatures(tmp_path: Path) -> None:
    service = _service(tmp_path, installer=True, signed=False)
    with pytest.raises(RuntimeError, match="signatures"):
        service.build_final_release(require_installer=True, require_signatures=True)


def test_phase53_build_writes_final_manifest_feed_digest_and_latest(tmp_path: Path) -> None:
    service = _service(tmp_path, installer=True, signed=True)
    snapshot = service.build_final_release(
        channel="preview",
        rollout_percentage=25,
        require_installer=True,
        require_signatures=True,
    )
    assert snapshot.status == "ready"
    assert snapshot.bundle_dir is not None
    assert snapshot.update_feed is not None
    assert snapshot.rollout_percentage == 25
    assert (snapshot.bundle_dir / service.MANIFEST_NAME).exists()
    assert (snapshot.bundle_dir / service.CHECKSUM_NAME).exists()
    assert (snapshot.bundle_dir / service.FEED_DIGEST_NAME).exists()
    assert (snapshot.bundle_dir / service.SIGNING_RESULT_NAME).exists()
    feed_payload = json.loads(snapshot.update_feed.read_text(encoding="utf-8"))
    assert feed_payload["release_notes_url"] == "RELEASE-NOTES.md"
    assert len(feed_payload["release_notes_sha256"]) == 64
    assert (service.latest_channel_feed("preview").parent / "RELEASE-NOTES.md").exists()
    assert (service.latest_release_dir() / service.MANIFEST_NAME).exists()
    assert service.latest_channel_feed("preview").exists()
    ok, _detail = service.verify_update_feed(service.latest_channel_feed("preview"))
    assert ok


def test_phase53_update_feed_and_manifest_detect_tampering(tmp_path: Path) -> None:
    service = _service(tmp_path, installer=True, signed=True)
    snapshot = service.build_final_release(require_installer=True, require_signatures=True)
    portable = next(item.path for item in snapshot.artifacts if item.role == "portable_package")
    portable.write_bytes(portable.read_bytes() + b"tampered")
    manifest_ok, manifest_detail = service.verify_final_manifest(
        snapshot.bundle_dir / service.MANIFEST_NAME
    )
    feed_ok, feed_detail = service.verify_update_feed(snapshot.update_feed)
    assert not manifest_ok
    assert not feed_ok
    assert "sha-256" in manifest_detail.casefold()
    assert "sha-256" in feed_detail.casefold()


def test_phase53_build_script_uses_store_thumbprint_signtool_and_timestamp() -> None:
    build = Path("scripts/build.ps1").read_text(encoding="utf-8")
    assert "S_TALKING_SIGN_CERT_THUMBPRINT" in build
    assert "S_TALKING_SIGNTOOL_PATH" in build
    assert "S_TALKING_TIMESTAMP_URL" in build
    assert "Get-AuthenticodeSignature" in build
    assert "SignTool verification failed" in build
    assert "PFX" not in build.upper()
    script = Path("scripts/final-release.ps1").read_text(encoding="utf-8")
    assert "RequireSigning" in script
    assert "RequireInstaller" in script
    assert "build_final_release" in script


def test_phase53_dialog_and_mainwindow_contract_are_exposed(qt_app, tmp_path: Path) -> None:
    service = _service(tmp_path)
    dialog = FinalReleaseDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "finalReleaseDialog"
    assert dialog.channel.currentText() == "preview"
    assert dialog.rollout.value() == 100
    assert dialog.gate_table.rowCount() >= 9
    assert dialog.require_signatures.text() == "Require verified signatures"
    main = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "Final Release & Updates" in main
    assert "open_final_release" in main
    dialog.close()
    dialog.deleteLater()
    _drain(qt_app)
