from __future__ import annotations

import json
import zipfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.release_candidate_dialog import ReleaseCandidateDialog
from app.services.git_service import GitStatus
from app.services.release_candidate_service import ReleaseCandidateService


class _Git:
    def __init__(self, *, clean: bool = True) -> None:
        self.clean = clean

    def status(self) -> GitStatus:
        return GitStatus("fix/provider-accounts-layout", self.clean, [] if self.clean else ["dirty.py"])

    def recent_commits(self, limit: int = 1) -> list[str]:
        return ["abc1234 feat: release candidate"]


class _Readiness:
    def __init__(self, package: Path) -> None:
        self.package = package

    def create_portable_zip(self) -> Path:
        return self.package


def _runtime(tmp_path: Path) -> RuntimeConfig:
    root = tmp_path / "project"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname="s-talking"\nversion="0.18.2rc1"\n',
        encoding="utf-8",
    )
    return RuntimeConfig.from_root(root)


def _release_check(runtime: RuntimeConfig, *, passed: int = 757) -> None:
    folder = runtime.artifacts_dir / "release-check" / "latest"
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "success": True,
        "steps": {
            "compileall": {"success": True, "exit_code": 0},
            "ruff": {"success": True, "exit_code": 0},
            "pytest": {"success": True, "exit_code": 0, "passed": passed},
            "release_smoke": {"success": True, "exit_code": 0},
        },
    }
    (folder / "result.json").write_text(json.dumps(payload), encoding="utf-8-sig")


def _package(path: Path, *, forbidden: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        root = "S-Talking-0.18.2-rc1-portable/"
        archive.writestr(root + "README.md", "release")
        archive.writestr(root + "pyproject.toml", '[project]\nversion="0.18.2rc1"\n')
        archive.writestr(root + "RUN-S-TALKING.bat", "@echo off")
        archive.writestr(root + "app/__init__.py", '__version__="0.18.2-rc1"')
        archive.writestr(root + "app/data/catalog.json", "{}")
        if forbidden:
            archive.writestr(root + "credentials/api-profiles.json", "{}")
    return path


def _service(tmp_path: Path, *, package: Path | None = None, clean: bool = True) -> ReleaseCandidateService:
    runtime = _runtime(tmp_path)
    _release_check(runtime)
    return ReleaseCandidateService(
        runtime,
        _Git(clean=clean),
        _Readiness(package) if package else None,
        version="0.18.2-rc1",
        release_channel="rc",
        schema_version=22,
    )


def _drain(qt_app) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_phase50_version_normalization_matches_pyproject_rc_syntax() -> None:
    assert ReleaseCandidateService.normalize_version("0.18.2-rc1") == "0.18.2rc1"
    assert ReleaseCandidateService.normalize_version("0.18.2rc1") == "0.18.2rc1"

    script = (Path(__file__).resolve().parents[1] / "scripts" / "release-candidate.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "& $Python -c $code" not in script
    assert "[System.IO.File]::WriteAllText($tempScript, $code, $utf8NoBom)" in script
    assert "& $Python $tempScript" in script
    assert 'print("Failed release gates:")' in script
    assert "Remove-Item" in script


def test_phase50_snapshot_blocks_when_package_is_missing(tmp_path: Path) -> None:
    service = _service(tmp_path)
    snapshot = service.snapshot()
    assert snapshot.status == "blocked"
    assert any(gate.code == "package_exists" and not gate.passed for gate in snapshot.gates)


def test_phase50_package_audit_accepts_verified_portable_layout(tmp_path: Path) -> None:
    package = _package(tmp_path / "candidate.zip")
    service = _service(tmp_path, package=package)
    audit = service.audit_package(package)
    assert audit.status == "verified"
    assert audit.sha256


def test_phase50_package_audit_rejects_credentials_and_runtime_files(tmp_path: Path) -> None:
    package = _package(tmp_path / "unsafe.zip", forbidden=True)
    service = _service(tmp_path, package=package)
    audit = service.audit_package(package)
    assert audit.status == "failed"
    assert "forbidden" in audit.detail.casefold()


def test_phase50_build_writes_manifest_checksums_notes_and_latest(tmp_path: Path) -> None:
    package = _package(tmp_path / "source" / "candidate.zip")
    service = _service(tmp_path, package=package)
    snapshot = service.build_candidate()
    assert snapshot.status == "ready"
    assert snapshot.package_path is not None
    assert snapshot.package_path.name == "S-Talking-0.18.2-rc1-portable.zip"
    assert snapshot.manifest_path and snapshot.manifest_path.exists()
    assert snapshot.checksum_path and snapshot.checksum_path.exists()
    assert snapshot.notes_path and snapshot.notes_path.exists()
    assert (service.latest_candidate_dir() / service.MANIFEST_NAME).exists()
    ok, _detail = service.verify_manifest(snapshot.manifest_path)
    assert ok


def test_phase50_manifest_detects_package_tampering(tmp_path: Path) -> None:
    package = _package(tmp_path / "source" / "candidate.zip")
    service = _service(tmp_path, package=package)
    snapshot = service.build_candidate()
    assert snapshot.package_path is not None
    with snapshot.package_path.open("ab") as handle:
        handle.write(b"tampered")
    ok, detail = service.verify_manifest(snapshot.manifest_path)
    assert not ok
    assert "sha-256" in detail.casefold()


def test_phase50_export_snapshot_is_structured_and_secret_free(tmp_path: Path) -> None:
    package = _package(tmp_path / "candidate.zip")
    service = _service(tmp_path, package=package)
    snapshot = service.snapshot(package)
    path = service.export_snapshot(snapshot)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == "0.18.2-rc1"
    assert payload["test_count"] == 757
    text = path.read_text(encoding="utf-8").casefold()
    assert "api_key" not in text
    assert "bearer " not in text


def test_phase50_dialog_renders_release_gates_and_releases(qt_app, tmp_path: Path) -> None:
    package = _package(tmp_path / "candidate.zip")
    service = _service(tmp_path, package=package)
    dialog = ReleaseCandidateDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "releaseCandidateDialog"
    assert dialog.gate_table.rowCount() >= 8
    assert "Release candidate" in dialog.windowTitle()
    dialog.close()
    dialog.deleteLater()
    _drain(qt_app)
