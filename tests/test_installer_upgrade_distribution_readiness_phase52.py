from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication, QEvent

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.distribution_readiness_dialog import DistributionReadinessDialog
from app.services.distribution_readiness_service import DistributionReadinessService


class _ReleaseCandidate:
    MANIFEST_NAME = "release-candidate-manifest.json"
    CHECKSUM_NAME = "SHA256SUMS.txt"
    NOTES_NAME = "RELEASE-NOTES.md"

    def __init__(self, candidate: Path) -> None:
        self.candidate = candidate

    def latest_candidate_dir(self) -> Path:
        return self.candidate

    def verify_manifest(self, path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            package = path.parent / Path(payload["package"]["path"]).name
            expected = payload["package"]["sha256"]
            actual = hashlib.sha256(package.read_bytes()).hexdigest()
            return (actual == expected, "Release candidate manifest verified." if actual == expected else "SHA mismatch")
        except Exception as exc:
            return False, str(exc)

    def audit_package(self, path: Path):
        return SimpleNamespace(status="verified", detail="Portable package layout and privacy verified.")


def _runtime(tmp_path: Path) -> RuntimeConfig:
    root = tmp_path / "project"
    (root / "packaging" / "windows").mkdir(parents=True)
    source = Path("packaging/windows/S-Talking.iss").read_text(encoding="utf-8")
    (root / "packaging" / "windows" / "S-Talking.iss").write_text(source, encoding="utf-8")
    runtime = RuntimeConfig.from_root(root)
    runtime.ensure_directories()
    return runtime


def _candidate(runtime: RuntimeConfig) -> Path:
    candidate = runtime.artifacts_dir / "release-candidate" / "latest"
    candidate.mkdir(parents=True, exist_ok=True)
    package = candidate / "S-Talking-0.18.2-rc1-portable.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("S-Talking-0.18.2-rc1-portable/S-Talking.exe", b"portable")
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "package": {
            "path": str(package),
            "sha256": digest,
        },
    }
    (candidate / _ReleaseCandidate.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    (candidate / _ReleaseCandidate.CHECKSUM_NAME).write_text(f"{digest}  {package.name}\n", encoding="ascii")
    (candidate / _ReleaseCandidate.NOTES_NAME).write_text("# Notes\n", encoding="utf-8")
    return candidate



def _compiled_portable(runtime: RuntimeConfig) -> Path:
    folder = runtime.artifacts_dir / "package"
    folder.mkdir(parents=True, exist_ok=True)
    package = folder / "S-Talking-0.18.2-rc1-portable.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("S-Talking.exe", b"MZ" + b"\0" * 8190)
        archive.writestr("portable.mode", b"")
        archive.writestr("RUN.cmd", b"@echo off")
        archive.writestr("README.txt", b"portable")
    result = {
        "schema_version": 2,
        "success": True,
        "stage": "complete",
        "version": "0.18.2-rc1",
        "zip_path": str(package),
    }
    (folder / "build-result.json").write_text(json.dumps(result), encoding="utf-8")
    return package

def _service(tmp_path: Path, *, with_candidate: bool = True) -> DistributionReadinessService:
    runtime = _runtime(tmp_path)
    candidate = _candidate(runtime) if with_candidate else runtime.artifacts_dir / "release-candidate" / "latest"
    if with_candidate:
        _compiled_portable(runtime)
    return DistributionReadinessService(runtime, _ReleaseCandidate(candidate), version="0.18.2-rc1")


def _real_installer(service: DistributionReadinessService) -> Path:
    folder = service.runtime.artifacts_dir / "package" / "installer"
    folder.mkdir(parents=True, exist_ok=True)
    installer = folder / "S-Talking-0.18.2-rc1-setup.exe"
    installer.write_bytes(b"MZ" + b"\0" * 8190)
    result = {
        "schema_version": 2,
        "success": True,
        "available": True,
        "distributable": True,
        "artifact_kind": "installer",
        "installer_path": str(installer),
        "unsigned": True,
    }
    result_path = service.runtime.artifacts_dir / "package" / "installer-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return installer


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_phase52_inno_contract_is_per_user_upgrade_safe_and_non_destructive() -> None:
    text = Path("packaging/windows/S-Talking.iss").read_text(encoding="utf-8")
    assert "AppId={{BD8A7352-0C93-4C2E-ACD7-7F3F5C8AA221}" in text
    assert "DefaultDirName={localappdata}\\Programs\\S Talking" in text
    assert "PrivilegesRequired=lowest" in text
    assert "UsePreviousAppDir=yes" in text
    assert "CloseApplications=yes" in text
    assert "RestartApplications=no" in text
    assert "[UninstallDelete]" not in text


def test_phase52_build_script_never_creates_fake_installer_exe() -> None:
    build = Path("scripts/build.ps1").read_text(encoding="utf-8")
    assert "schema_version = 3" in build
    assert "signing-result.json" in build
    assert "Test-PortableExecutable" in build
    assert "S-Talking-$version-installer-unavailable.txt" in build
    assert 'artifact_kind = "placeholder"' in build
    assert "No placeholder .exe was created" in build
    distribution = Path("scripts/distribution-candidate.ps1").read_text(encoding="utf-8")
    assert "BuildPackages" in distribution
    assert "RequireInstaller" in distribution
    assert "distribution_readiness_service.build_distribution" in distribution


def test_phase52_snapshot_blocks_without_verified_release_candidate(tmp_path: Path) -> None:
    snapshot = _service(tmp_path, with_candidate=False).snapshot()
    assert snapshot.status == "blocked"
    assert snapshot.blocker_count >= 2
    assert any(gate.code == "release_candidate" and not gate.passed for gate in snapshot.gates)


def test_phase52_portable_channel_is_ready_with_installer_warning(tmp_path: Path) -> None:
    snapshot = _service(tmp_path).snapshot()
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.blocker_count == 0
    assert not snapshot.installer_distributable
    assert any(gate.code == "installer_artifact" and gate.severity == "warning" for gate in snapshot.gates)


def test_phase52_real_installer_is_verified_and_version_matched(tmp_path: Path) -> None:
    service = _service(tmp_path)
    installer = _real_installer(service)
    snapshot = service.snapshot()
    assert snapshot.status == "ready"
    assert snapshot.installer_distributable
    assert any(item.path == installer and item.status == "verified" for item in snapshot.artifacts)


def test_phase52_build_distribution_writes_upgrade_rollback_manifest_and_latest(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_distribution()
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.bundle_dir is not None
    assert (snapshot.bundle_dir / service.UPGRADE_PLAN_NAME).exists()
    assert (snapshot.bundle_dir / service.ROLLBACK_NAME).exists()
    assert (snapshot.bundle_dir / service.INSTALL_NAME).exists()
    manifest = snapshot.bundle_dir / service.MANIFEST_NAME
    assert manifest.exists()
    assert (service.latest_distribution_dir() / service.MANIFEST_NAME).exists()
    ok, _detail = service.verify_distribution_manifest(manifest)
    assert ok


def test_phase52_distribution_manifest_detects_tampering(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.build_distribution()
    package = next(item.path for item in snapshot.artifacts if item.role == "portable_package")
    package.write_bytes(package.read_bytes() + b"tampered")
    ok, detail = service.verify_distribution_manifest(snapshot.bundle_dir / service.MANIFEST_NAME)
    assert not ok
    assert "sha-256" in detail.casefold()


def test_phase52_dialog_and_mainwindow_contract_are_exposed(qt_app, tmp_path: Path) -> None:
    service = _service(tmp_path)
    dialog = DistributionReadinessDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "distributionReadinessDialog"
    assert dialog.gate_table.rowCount() >= 8
    assert dialog.require_installer.text() == "Require compiled Windows installer"
    main = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "Distribution Readiness" in main
    assert "open_distribution_readiness" in main
    dialog.close()
    dialog.deleteLater()
    _drain(qt_app)
