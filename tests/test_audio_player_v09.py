from __future__ import annotations

import os
import wave
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.widgets.audio_player import format_audio_time
from app.models import AppSettings, JobStatus, TTSJob
from app.services.audio_player_service import AudioPlayerService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def wav_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    return path


def test_initial_player_state(qt_app) -> None:
    service = AudioPlayerService()
    service.stop()

    assert service.state.playback_state == "stopped"
    assert service.state.volume == 70


def test_load_existing_file_and_reject_missing(qt_app, tmp_path: Path) -> None:
    service = AudioPlayerService()
    path = wav_file(tmp_path / "sample.wav")

    loaded = service.load(path)
    missing = service.load(tmp_path / "missing.wav")

    assert loaded.loaded is True
    assert loaded.current_path == path
    assert missing.loaded is False
    assert "missing" in missing.status.lower()


def test_play_pause_stop_seek_and_volume_state(qt_app, tmp_path: Path) -> None:
    service = AudioPlayerService()
    service.load(wav_file(tmp_path / "sample.wav"))

    assert service.play().playback_state == "playing"
    assert service.pause().playback_state == "paused"
    assert service.seek(250).position == 250
    assert service.set_volume(33).volume == 33
    assert service.stop().playback_state == "stopped"


def test_duration_formatting() -> None:
    assert format_audio_time(0) == "0:00"
    assert format_audio_time(65_000) == "1:05"
    assert format_audio_time(3_665_000) == "1:01:05"


def test_only_one_global_player_instance(qt_app) -> None:
    assert AudioPlayerService() is AudioPlayerService()


def test_voice_browser_preview_loads_player_and_cached_preview(qt_app, tmp_path: Path) -> None:
    from app.gui.voice_browser import VoiceBrowserDialog

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    settings = AppSettings(provider="mock")
    voices = context.voice_service.refresh(settings)
    dialog = VoiceBrowserDialog(
        service=context.voice_service,
        settings_provider=lambda: settings,
        desktop_service=context.desktop_service,
        audio_player_service=context.audio_player_service,
    )
    dialog.items = voices
    dialog._render_table()
    path = context.voice_service.preview(voices[0], dialog.preview_text.toPlainText(), settings)

    dialog._preview_ready(path)
    assert context.audio_player_service.current_path == path
    assert dialog.cached_preview_button.isEnabled() is True
    dialog.play_cached_preview()
    assert context.audio_player_service.current_path == path


def test_completed_queue_row_enables_playback_pending_failed_disable(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    output = wav_file(tmp_path / "out" / "done.wav")
    jobs = [
        TTSJob(row_number=2, filename="done.wav", text="done", status=JobStatus.COMPLETED, generated_output_path=str(output)),
        TTSJob(row_number=3, filename="pending.wav", text="pending"),
        TTSJob(row_number=4, filename="failed.wav", text="failed", status=JobStatus.FAILED),
    ]
    window.generation_controller.set_jobs(jobs)
    window.out.setText(str(output.parent))
    window.render_queue()

    window.table.selectRow(0)
    assert window.play_output_button.isEnabled() is True
    window.table.selectRow(1)
    assert window.play_output_button.isEnabled() is False
    window.table.selectRow(2)
    assert window.play_output_button.isEnabled() is False


def test_double_click_completed_output_and_close_stops_playback(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    output = wav_file(tmp_path / "out" / "done.wav")
    window.generation_controller.set_jobs([
        TTSJob(row_number=2, filename="done.wav", text="done", status=JobStatus.COMPLETED, generated_output_path=str(output))
    ])
    window.out.setText(str(output.parent))
    window.render_queue()
    window.table.selectRow(0)

    window.table.cellDoubleClicked.emit(0, 0)
    assert context.audio_player_service.current_path == output
    window.close()
    assert context.audio_player_service.playback_state == "stopped"
    assert context.audio_player_service.current_path is None
    assert context.audio_player_service.state.loaded is False


def test_reports_preserve_output_paths(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = wav_file(tmp_path / "out" / "done.wav")

    report = container.report_service.create_generation_report(
        project=None,
        settings=AppSettings(provider="mock"),
        jobs=[TTSJob(row_number=2, filename="done.wav", text="done", status=JobStatus.COMPLETED, generated_output_path=str(output))],
        output_dir=output.parent,
        summary={"total": 1, "completed": 1, "failed": 0, "skipped": 0},
        started_at=datetime.now(timezone.utc),
    )

    assert str(output) in report.summary_md.read_text(encoding="utf-8")
    assert output.as_uri() in report.report_html.read_text(encoding="utf-8")
