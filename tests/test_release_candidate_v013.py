from __future__ import annotations

from pathlib import Path
import sys

import pytest
from PySide6.QtWidgets import QApplication

import app
from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.csv_loader import diagnose_csv
from app.models import AppSettings, JobStatus, TTSJob


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def _context(tmp_path: Path):
    return create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))


def test_version_identity_and_release_channel() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert app.__version__ == "0.18.2-rc1"
    assert app.__release_channel__ == "rc"
    assert 'version = "0.18.2rc1"' in pyproject


def test_startup_recovery_cleans_temp_malformed_settings_and_running_jobs(tmp_path: Path) -> None:
    context = _context(tmp_path)
    project = context.container.project_repository.create(name="Recover", provider="mock", settings=AppSettings(provider="mock"))
    job = TTSJob(row_number=2, filename="one.wav", text="Hej", status=JobStatus.RUNNING)
    context.container.job_repository.upsert_jobs(project.id, [job], output_dir=tmp_path / "output", extension=".wav")
    temp = tmp_path / "output" / "stale.partial"
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(b"partial")
    context.container.runtime.settings_path.write_text("{bad", encoding="utf-8")

    state = context.startup_recovery_service.recover()
    restored = context.container.job_repository.restore_jobs(project.id)

    assert state.temporary_files_removed == 1
    assert state.running_jobs_recovered >= 1
    assert state.malformed_settings_recovered
    assert not temp.exists()
    assert restored[0].status == JobStatus.PENDING


def test_session_restore_roundtrip(tmp_path: Path) -> None:
    context = _context(tmp_path)
    project_path = tmp_path / "demo.stproj"

    context.session_restore_service.save(
        last_project_path=project_path,
        auto_restore_enabled=True,
        queue_filter="failed",
        selected_row=7,
    )
    state = context.session_restore_service.load()

    assert state.auto_restore_enabled
    assert state.last_project_path == project_path
    assert state.queue_filter == "failed"
    assert state.selected_row == 7


def test_release_readiness_redacts_and_reads_repaired_csv(tmp_path: Path) -> None:
    context = _context(tmp_path)
    csv_path = tmp_path / "input.repaired.csv"
    csv_path.write_text('"text","filename"\n"Hej","one.wav"\n', encoding="utf-8-sig")
    state = context.release_readiness_service.snapshot(
        csv_path=csv_path,
        jobs=[TTSJob(row_number=2, filename="one.wav", text="Hej")],
        settings=AppSettings(provider="mock"),
        output_dir=tmp_path / "output",
    )

    assert state.version == "0.18.2-rc1"
    assert state.release_channel == "rc"
    assert state.valid_rows == 1
    assert state.rejected_rows == 0
    assert state.provider_status.connection_state == "ready"
    assert state.secret_redaction_status == "passed"
    exported = context.release_readiness_service.export(state)
    assert exported.exists()
    assert "sk_test_secret" not in exported.read_text(encoding="utf-8")


def test_repaired_csv_project_replacement_reloads_queue_and_preflight(qt_app, tmp_path: Path) -> None:
    context = _context(tmp_path)
    source = tmp_path / "input.csv"
    repaired = tmp_path / "input.repaired.csv"
    source.write_text('"text","filename"\n"Hej","bad prose filename value"\n', encoding="utf-8")
    repaired.write_text('"text","filename"\n"Hej","one.wav"\n', encoding="utf-8-sig")
    project = context.project_controller.new_project("Demo", source, tmp_path / "output", AppSettings(provider="mock"))
    from app.gui.main import MainWindow

    window = MainWindow(context)
    window.apply_project_state(project)
    window.replace_project_csv_with_repaired(repaired)

    assert window.csv.text() == str(repaired)
    assert context.project_controller.current_project.csv_path == repaired
    assert len(window.generation_controller.jobs) == 1
    assert diagnose_csv(repaired).rejected_rows == 0
    assert context.preflight_service.latest is not None
    window.close()


def test_release_check_script_and_packaging_config_exist() -> None:
    script = Path("scripts/release-check.ps1").read_text(encoding="utf-8")
    spec = Path("packaging/S-Talking.spec").read_text(encoding="utf-8")
    build = Path("scripts/build.ps1").read_text(encoding="utf-8")

    assert "artifacts\\release-check" in script
    assert "result.json" in script
    assert "release_smoke" in script
    assert "PyInstaller" in spec
    assert "Compress-Archive" in build
    assert "S-Talking.exe" in build
    assert "portable.mode" in build
    assert "build-result.json" in build
    assert "S_TALKING_SMOKE_EXIT_MS" in build


def test_app_closes_with_release_dialog_and_audio_service(qt_app, tmp_path: Path) -> None:
    context = _context(tmp_path)
    from app.gui.main import MainWindow

    window = MainWindow(context)
    context.audio_player_service.stop()
    window.developer_tools.show_release_readiness()
    window.close()

    assert context.audio_player_service.current_path is None or context.audio_player_service.state.playback_state == "stopped"


def test_frozen_path_resolution_portable_and_localappdata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe_dir = tmp_path / "package" / "S-Talking"
    meipass = tmp_path / "_MEI123"
    exe_dir.mkdir(parents=True)
    meipass.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "S-Talking.exe"))
    (exe_dir / "portable.mode").write_text("", encoding="utf-8")

    portable = RuntimeConfig.from_root()
    portable.ensure_directories()

    assert portable.bundled_root == meipass
    assert portable.data_dir == exe_dir / "S-Talking-Data" / "data"
    assert portable.settings_path == exe_dir / "S-Talking-Data" / "settings" / "settings.json"
    assert str(meipass) not in str(portable.data_dir)
    assert portable.log_dir.exists()

    (exe_dir / "portable.mode").unlink()
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    local_runtime = RuntimeConfig.from_root()

    assert local_runtime.data_dir == local / "S-Talking" / "data"
    assert str(meipass) not in str(local_runtime.settings_path)


def test_launcher_and_build_result_contract() -> None:
    build = Path("scripts/build.ps1").read_text(encoding="utf-8")
    assert "launcher-error.log" in build
    assert "mshta" in build
    assert "dist\\S-Talking\\S-Talking.exe" in build
    assert '"artifacts\\package"' in build
    assert '"S-Talking-$version-portable"' in build


def test_startup_exception_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe_dir = tmp_path / "portable"
    exe_dir.mkdir()
    (exe_dir / "portable.mode").write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_MEI"), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "S-Talking.exe"))
    from app.frozen_main import _write_crash

    try:
        raise RuntimeError(
            "startup boom; Authorization: Bearer startup-secret-token-123456789"
        )
    except RuntimeError as exc:
        _write_crash(type(exc), exc, exc.__traceback__)

    crash = exe_dir / "S-Talking-Data" / "logs" / "startup-crash.log"
    text = crash.read_text(encoding="utf-8")
    assert "startup boom" in text
    assert "startup-secret-token" not in text
    assert "Authorization=[REDACTED]" in text
    assert "0.18.2-rc1" in text
    assert "S-Talking-Data" in text


def test_audio_player_multimedia_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.audio_player_service as audio_module

    original = audio_module.AudioPlayerService._shared_instance
    monkeypatch.setattr(audio_module, "QAudioOutput", None)
    monkeypatch.setattr(audio_module, "QMediaPlayer", None)
    audio_module.AudioPlayerService._shared_instance = None
    try:
        service = audio_module.AudioPlayerService()
        state = service.play()
    finally:
        audio_module.AudioPlayerService._shared_instance = original

    assert state.playback_state == "stopped"
    assert "unavailable" in state.status.lower()
