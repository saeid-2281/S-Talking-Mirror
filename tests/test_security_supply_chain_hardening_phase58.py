from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.secure_credentials import SecureCredentialStore
from app.services.security_supply_chain_service import SecuritySupplyChainService


class _MemoryCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set_password(self, target: str, secret: str) -> None:
        self.values[target] = secret

    def get_password(self, target: str) -> str | None:
        return self.values.get(target)

    def delete_password(self, target: str) -> None:
        self.values.pop(target, None)


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _service(
    tmp_path: Path,
    *,
    credential_store: SecureCredentialStore | None = None,
    command_runner=None,
) -> SecuritySupplyChainService:
    runtime = _runtime(tmp_path)
    return SecuritySupplyChainService(
        runtime,
        credential_store or SecureCredentialStore(runtime.settings_path.parent / "credentials", platform="test"),
        now=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
        command_runner=command_runner,
    )


def _valid_package(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("S-Talking.exe", b"MZ" + b"\0" * 8192)
        archive.writestr("portable.mode", b"")
        archive.writestr("RUN.cmd", b"@echo off\r\nstart S-Talking.exe\r\n")
        archive.writestr("_internal/python313.dll", b"MZ" + b"\0" * 1024)
        archive.writestr("_internal/PySide6/Qt/plugins/platforms/qwindows.dll", b"MZ")
    return path


def test_phase58_native_credential_backend_migrates_and_deletes_legacy_file(tmp_path: Path) -> None:
    directory = tmp_path / "credentials"
    legacy = SecureCredentialStore(directory, platform="test")
    legacy.set_password("profile-1", "secret-provider-key")
    legacy_path = legacy._path("profile-1")
    assert legacy_path.exists()

    backend = _MemoryCredentialBackend()
    hardened = SecureCredentialStore(
        directory,
        platform="test",
        native_backend=backend,
    )
    assert hardened.get_password("profile-1") == "secret-provider-key"
    assert hardened.backend_name == "windows-credential-manager"
    assert hardened.security_status()[0] == "pass"
    assert not legacy_path.exists()
    assert list(backend.values.values()) == ["secret-provider-key"]
    hardened.delete_password("profile-1")
    assert backend.values == {}


def test_phase58_spdx_sbom_is_verified_private_and_tamper_sensitive(tmp_path: Path) -> None:
    service = _service(tmp_path)
    path = service.generate_sbom()
    ok, detail = service.verify_sbom(path)
    assert ok, detail
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["spdxVersion"] == "SPDX-2.3"
    assert any(item["name"] == "s-talking" for item in payload["packages"])
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "settings.json" not in serialized

    payload["api_key"] = "sk-private-value"
    path.write_text(json.dumps(payload), encoding="utf-8")
    ok, detail = service.verify_sbom(path)
    assert not ok
    assert "secret-related" in detail


def test_phase58_package_audit_accepts_internal_dlls_and_rejects_unsafe_paths(tmp_path: Path) -> None:
    service = _service(tmp_path)
    package = _valid_package(tmp_path / "S-Talking-0.18.2-rc1-portable.zip")
    ok, detail, issues = service.inspect_package(package)
    assert ok, detail
    assert issues == ()

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("S-Talking.exe", b"MZ")
        archive.writestr("portable.mode", b"")
        archive.writestr("RUN.cmd", b"")
        archive.writestr("evil.dll", b"MZ")
        archive.writestr("../settings.json", b'{"api_key":"private"}')
        link = zipfile.ZipInfo("_internal/link.dll")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "target.dll")
    ok, detail, issues = service.inspect_package(unsafe)
    assert not ok
    assert "dll:untrusted-location:evil.dll" in issues
    assert any(issue.startswith("path:traversal:") for issue in issues)
    assert any(issue.startswith("privacy:private-file:") for issue in issues)
    assert any(issue.startswith("path:symlink:") for issue in issues)


def test_phase58_package_audit_receipt_revalidates_size_hash_and_issues(tmp_path: Path) -> None:
    service = _service(tmp_path)
    package = _valid_package(tmp_path / "candidate.zip")
    receipt = service.audit_package(package)
    assert receipt.status == "verified"
    ok, detail = service.verify_audit(receipt.report_path, package)
    assert ok, detail

    package.write_bytes(package.read_bytes() + b"tamper")
    ok, detail = service.verify_audit(receipt.report_path, package)
    assert not ok
    assert "size" in detail or "SHA-256" in detail


def test_phase58_vulnerability_scan_blocks_high_findings(monkeypatch, tmp_path: Path) -> None:
    result = {
        "dependencies": [
            {
                "name": "example-package",
                "version": "1.0",
                "vulns": [
                    {
                        "id": "CVE-2026-0001",
                        "severity": "high",
                        "fix_versions": ["1.1"],
                    }
                ],
            }
        ]
    }

    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, json.dumps(result), "")

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    service = _service(tmp_path, command_runner=runner)
    report = service.run_vulnerability_scan()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "vulnerable"
    assert payload["vulnerabilities"][0]["severity"] == "high"
    snapshot = service.snapshot()
    gate = next(item for item in snapshot.gates if item.gate_id == "vulnerabilities")
    assert gate.status == "block"
    assert snapshot.status == "blocked"


def test_phase58_snapshot_export_contains_metadata_not_private_values(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.settings_path.write_text('{"api_key":"sk-settings-private"}', encoding="utf-8")
    (runtime.settings_path.parent / "api-profiles.json").write_text(
        '{"token":"profile-private"}',
        encoding="utf-8",
    )
    (runtime.default_output_dir / "private.mp3").write_bytes(b"private-audio")
    service = SecuritySupplyChainService(
        runtime,
        SecureCredentialStore(runtime.settings_path.parent / "credentials", platform="test"),
    )
    json_path, csv_path = service.export_snapshot()
    content = json_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    assert "sk-settings-private" not in content
    assert "profile-private" not in content
    assert "private.mp3" not in content
    assert str(tmp_path) not in content
    assert "credential_backend" in content


def test_phase58_frozen_cli_build_script_and_privacy_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    service = (root / "app" / "services" / "security_supply_chain_service.py").read_text(encoding="utf-8")
    runtime = (root / "app" / "security_runtime.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "security-audit.ps1").read_text(encoding="utf-8")
    build = (root / "scripts" / "build.ps1").read_text(encoding="utf-8")
    assert "--security-snapshot" in frozen
    assert "--generate-sbom" in frozen
    assert "--security-audit-package" in frozen
    assert "SetDefaultDllDirectories" in runtime
    assert "project text, database rows" in service
    assert "Invoke-Expression" not in script
    assert "--security-audit-package" in script
    assert "security_supply_chain" in build
    assert "--generate-sbom --security-audit-package" in build


def test_phase58_dialog_mainwindow_and_service_container_contracts(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container
    from app.gui.dialogs.security_supply_chain_dialog import SecuritySupplyChainDialog
    from app.gui.main import MainWindow

    runtime = _runtime(tmp_path)
    container = create_service_container(runtime)
    service = container.security_supply_chain_service
    dialog = SecuritySupplyChainDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "securitySupplyChainDialog"
    assert dialog.gate_table.rowCount() >= 9
    assert dialog.component_table.rowCount() >= 1
    sbom = dialog.generate_sbom()
    assert sbom.exists()
    dialog.close()

    window = MainWindow(create_application_context(container))
    window.show()
    qt_app.processEvents()
    assert "Security & Supply Chain" in window.actions_by_name
    assert any(
        command.name == "Reports: Security & Supply Chain"
        for command in window.command_palette_commands()
    )
    opened = window.open_security_supply_chain()
    assert opened.objectName() == "securitySupplyChainDialog"
    window.close()
