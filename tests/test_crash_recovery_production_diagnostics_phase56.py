from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import threading
import zipfile
from pathlib import Path

import pytest

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.crash_recovery_dialog import CrashRecoveryDialog
from app.gui.main import MainWindow
from app.services.crash_recovery_service import CrashRecoveryService


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _raise_sensitive_error() -> None:
    source_text = "This is private project source text that must never be copied into a traceback frame."
    raise RuntimeError(
        "api_key=sk-private-1234567890 and password='open-sesame' and "
        + repr(source_text * 2)
    )


def test_phase56_capture_redacts_secrets_and_omits_source_lines(tmp_path: Path) -> None:
    service = CrashRecoveryService(_runtime(tmp_path))
    service.begin_session(argv=["S-Talking.exe"])
    try:
        _raise_sensitive_error()
    except RuntimeError as exc:
        record = service.capture_exception(
            type(exc),
            exc,
            exc.__traceback__,
            context={"api_key": "sk-context-secret", "queue_total": 12},
        )
    assert record is not None
    payload = json.loads(record.report_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "sk-private" not in serialized
    assert "open-sesame" not in serialized
    assert "sk-context-secret" not in serialized
    assert "private project source text" not in serialized
    assert payload["context"]["api_key"] == "[REDACTED]"
    assert payload["frames"]
    assert all(set(frame) == {"file", "line", "function"} for frame in payload["frames"])
    assert payload["integrity_sha256"]
    assert service.read_report(record.report_id)["report_id"] == record.report_id


def test_phase56_authorization_header_redacts_entire_credential(tmp_path: Path) -> None:
    service = CrashRecoveryService(_runtime(tmp_path))
    samples = [
        "Authorization: Bearer secret-token-123456789",
        "authorization=Basic dXNlcjpwYXNzd29yZA==",
        "AUTHORIZATION: direct-secret-value",
        "Bearer standalone-secret-token",
    ]
    sanitized = "\n".join(service._sanitize_text(sample) for sample in samples)
    assert "secret-token" not in sanitized
    assert "dXNlcjpwYXNzd29yZA" not in sanitized
    assert "direct-secret-value" not in sanitized
    assert sanitized.count("[REDACTED]") == len(samples)


def test_phase56_unclean_session_detection_and_clean_shutdown(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    first = CrashRecoveryService(runtime)
    first.begin_session(argv=["S-Talking.exe"], pid=101)
    assert first.session_marker.exists()

    second = CrashRecoveryService(runtime)
    second.begin_session(argv=["S-Talking.exe", "--safe-mode"], pid=202)
    snapshot = second.snapshot()
    assert snapshot.previous_unclean_shutdown is True
    assert snapshot.safe_mode is True
    assert snapshot.status == "attention"
    assert "--safe-mode" in second.safe_mode_command()

    clean = second.mark_clean_shutdown()
    assert clean.exists()
    assert not second.session_marker.exists()
    assert json.loads(clean.read_text(encoding="utf-8"))["status"] == "clean"


def test_phase56_report_tamper_blocks_acknowledgement_and_snapshot(tmp_path: Path) -> None:
    service = CrashRecoveryService(_runtime(tmp_path))
    try:
        raise ValueError("controlled failure")
    except ValueError as exc:
        record = service.capture_exception(type(exc), exc, exc.__traceback__)
    assert record is not None
    payload = json.loads(record.report_path.read_text(encoding="utf-8"))
    payload["summary"] = "modified after capture"
    record.report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    snapshot = service.snapshot()
    assert snapshot.status == "blocked"
    assert snapshot.integrity_failure_count == 1
    assert snapshot.blocker_count == 1
    with pytest.raises(ValueError, match="integrity"):
        service.acknowledge(record.report_id)


def test_phase56_bundle_is_verified_redacted_and_excludes_private_files(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.settings_path.write_text('{"api_key":"sk-settings-secret"}', encoding="utf-8")
    (runtime.settings_path.parent / "api-profiles.json").write_text(
        '{"token":"profile-secret"}', encoding="utf-8"
    )
    credentials = runtime.settings_path.parent / "credentials"
    credentials.mkdir(parents=True)
    (credentials / "provider.bin").write_bytes(b"credential-bytes")
    (runtime.default_output_dir / "private.mp3").write_bytes(b"audio")
    (runtime.log_dir / "application.log").write_text(
        "Authorization: Bearer secret-token-123456789\napi_key=sk-log-secret\nRuntime error",
        encoding="utf-8",
    )
    service = CrashRecoveryService(runtime)
    service.capture_message("token=runtime-secret", source="test")
    receipt = service.export_bundle()
    ok, detail = service.verify_bundle(receipt.path)
    assert ok, detail
    assert receipt.status == "verified"

    with zipfile.ZipFile(receipt.path) as archive:
        names = archive.namelist()
        content = b"\n".join(archive.read(name) for name in names).decode("utf-8", errors="ignore")
    lowered = "\n".join(names).casefold()
    assert "api-profiles" not in lowered
    assert "credentials" not in lowered
    assert "settings.json" not in lowered
    assert "private.mp3" not in lowered
    assert "sk-log-secret" not in content
    assert "secret-token" not in content
    assert "[REDACTED]" in content


def test_phase56_snapshot_detects_recovery_evidence_and_healthy_database(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    connection = sqlite3.connect(runtime.database_path)
    connection.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()
    (runtime.cache_dir / "generation-recovery.json").write_text(
        json.dumps({"version": 1, "jobs": []}), encoding="utf-8"
    )
    (runtime.cache_dir / "session-restore.json").write_text(
        json.dumps({"auto_restore_enabled": True}), encoding="utf-8"
    )

    snapshot = CrashRecoveryService(runtime).snapshot()
    assert snapshot.database_status == "healthy"
    assert snapshot.queue_recovery_available is True
    assert snapshot.session_restore_available is True
    assert snapshot.blocker_count == 0
    assert snapshot.status == "healthy"


def test_phase56_handler_lifecycle_restores_python_hooks(tmp_path: Path) -> None:
    service = CrashRecoveryService(_runtime(tmp_path))
    original_sys = sys.excepthook
    original_thread = threading.excepthook
    try:
        service.install_handlers()
        assert sys.excepthook == service._sys_excepthook
        assert threading.excepthook == service._threading_excepthook
    finally:
        service.uninstall_handlers()
    assert sys.excepthook == original_sys
    assert threading.excepthook == original_thread


def test_phase56_frozen_cli_safe_mode_and_privacy_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    service = (root / "app" / "services" / "crash_recovery_service.py").read_text(encoding="utf-8")
    assert "--safe-mode" in frozen
    assert "--crash-recovery-snapshot" in frozen
    assert "--export-crash-diagnostics" in frozen
    assert "crash_recovery_service=crash_service" in frozen
    assert "project sources, generated audio, databases, settings" in service
    assert "qInstallMessageHandler" in service
    assert "source-code lines or local variables" in service


def test_phase56_dialog_mainwindow_and_bundle_manifest_contracts(qt_app, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    container = create_service_container(runtime)
    service = container.crash_recovery_service
    service.capture_message("controlled UI crash evidence", source="ui-test")
    dialog = CrashRecoveryDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "crashRecoveryDialog"
    assert dialog.report_table.rowCount() == 1
    assert dialog.gate_table.rowCount() >= 5
    receipt = dialog.export_bundle()
    assert receipt is not None and receipt.path.exists()
    with zipfile.ZipFile(receipt.path) as archive:
        manifest = json.loads(archive.read("diagnostics/manifest.json"))
        for name, evidence in manifest["files"].items():
            data = archive.read(name)
            assert len(data) == evidence["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == evidence["sha256"]
    dialog.close()

    window = MainWindow(create_application_context(container))
    assert "Crash Recovery & Diagnostics" in window.actions_by_name
    assert callable(window.open_crash_recovery)
    assert any(
        command.name == "Reports: Crash Recovery & Diagnostics"
        for command in window.command_palette_commands()
    )
    window.close()
