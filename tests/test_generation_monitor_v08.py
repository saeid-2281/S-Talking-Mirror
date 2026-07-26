from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, JobStatus, TTSJob
from app.models.generation_monitor_state import GenerationMonitorState
from app.services.monitor_formatting import (
    elide_middle,
    format_characters_per_minute,
    format_duration,
    format_files_per_minute,
    status_color,
)
from app.services.generation_monitor_service import GenerationMonitorService


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def monitor_settings():
    settings = QSettings("S Talking", "S Talking")
    previous = {key: settings.value(key) for key in ["main_window/monitor_width", "main_window/monitor_visible", "main_window/state"] if settings.contains(key)}
    for key in ["main_window/monitor_width", "main_window/monitor_visible", "main_window/state"]:
        settings.remove(key)
    yield
    for key in ["main_window/monitor_width", "main_window/monitor_visible", "main_window/state"]:
        settings.remove(key)
    for key, value in previous.items():
        settings.setValue(key, value)


def sample_jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=2, filename="one.wav", text="one"),
        TTSJob(row_number=3, filename="two.wav", text="two two"),
        TTSJob(row_number=4, filename="three.wav", text="three"),
    ]


def test_monitor_initial_state() -> None:
    service = GenerationMonitorService(clock=FakeClock())

    assert service.state.current_status == "Ready"
    assert service.state.current_filename == "None"
    assert service.state.resource_usage == "Not available"


def test_duration_formatter() -> None:
    assert format_duration(42) == "42 s"
    assert format_duration(744) == "12 min 24 s"
    assert format_duration(12600) == "3 h 30 min"
    assert format_duration(0, empty_zero=True) == "—"


def test_rate_formatter() -> None:
    assert format_files_per_minute(1.234) == "1.23"
    assert format_files_per_minute(0) == "—"
    assert format_characters_per_minute(12345.2) == "12,345"
    assert format_characters_per_minute(0) == "—"


def test_long_filename_path_elision_and_status_mapping() -> None:
    text = r"D:\very\long\folder\with\many\segments\sample-output-file.wav"

    elided = elide_middle(text, 24)
    assert elided.startswith("D:\\very")
    assert elided.endswith("file.wav")
    assert "..." in elided
    assert len(elided) <= 24
    assert status_color("Running") == "#38BDF8"
    assert status_color("Stopped by user") == "#EF4444"


def test_current_and_next_job_tracking_and_full_queue_despite_filter() -> None:
    clock = FakeClock()
    service = GenerationMonitorService(clock=clock)
    jobs = sample_jobs()
    jobs[0].status = JobStatus.RUNNING

    state = service.start_run(jobs, provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))

    assert state.current_filename == "one.wav"
    assert state.next_filename == "two.wav"
    assert state.total == 3


def test_queue_counters_and_eta() -> None:
    clock = FakeClock()
    service = GenerationMonitorService(clock=clock)
    jobs = sample_jobs()
    jobs[0].status = JobStatus.COMPLETED
    jobs[0].duration_seconds = 4
    jobs[1].status = JobStatus.RUNNING

    state = service.start_run(jobs, provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    service.completed_durations = [4.0]
    state = service.tick()

    assert state.completed == 1
    assert state.running == 1
    assert state.pending == 1
    assert state.remaining_eta_seconds == 8.0


def test_elapsed_pause_resume_and_active_time() -> None:
    clock = FakeClock()
    service = GenerationMonitorService(clock=clock)
    service.start_run(sample_jobs(), provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    clock.advance(5)
    service.pause()
    clock.advance(10)
    paused = service.tick()
    service.resume()
    clock.advance(5)
    resumed = service.tick()

    assert paused.paused_seconds == 10
    assert resumed.total_elapsed_seconds == 20
    assert resumed.active_elapsed_seconds == 10


def test_rolling_average_files_per_min_chars_per_min() -> None:
    clock = FakeClock()
    service = GenerationMonitorService(clock=clock)
    jobs = sample_jobs()
    service.start_run(jobs, provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    clock.advance(30)
    jobs[0].status = JobStatus.COMPLETED

    state = service.handle_progress(jobs, status="completed", name="one.wav", duration=6, retry=1, error="")

    assert state.average_seconds_per_completed_job == 6
    assert state.files_per_minute == pytest.approx(2.0)
    assert state.characters_per_minute == pytest.approx(6.0)


def test_stop_state_and_final_state_persistence() -> None:
    clock = FakeClock()
    service = GenerationMonitorService(clock=clock)
    service.start_run(sample_jobs(), provider="mock", output_dir=Path("out"), settings=AppSettings(provider="mock"))
    clock.advance(2)

    service.stop_requested()
    state = service.finish({"stopped": True})
    clock.advance(3)

    assert state.current_status == "Stopped by user"
    assert service.state.stopped_by_user is True
    assert service.timer.isActive() is False


def test_monitor_panel_show_hide_action_and_command_palette(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    qt_app.processEvents()

    assert window.monitor_dock.windowTitle() == "Generation Monitor"
    assert 280 <= window.monitor_dock.minimumWidth() <= 300
    assert 290 <= window.monitor_dock.width() <= 340
    assert window.monitor_dock.widget().widgetResizable() is True
    assert window.monitor_dock.widget().horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert window.actions_by_name["Show/Hide Generation Monitor"].isCheckable()
    assert any(command.name == "Generation: Show/Hide Generation Monitor" for command in window.command_palette_commands())
    window.toggle_generation_monitor(False)
    assert window.monitor_dock.isVisible() is False


def test_idle_placeholders_and_progress_percentage(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    state = GenerationMonitorState(total=4, processed=1, current_status="Ready", next_filename="first.wav")

    window.render_monitor(state)

    assert window.monitor_status.text() == "Ready"
    assert window.monitor_labels["current_filename"].text() == "None"
    assert window.monitor_labels["next_filename"].text() == "first.wav"
    assert window.monitor_percent.text() == "1 / 4 · 25%"


def test_monitor_compact_mode_threshold_and_action_buttons(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    window.resize(1000, 700)
    qt_app.processEvents()
    window.apply_monitor_compact_mode()

    assert window.monitor_compact_mode() is True
    assert window.monitor_more_details.isVisible() is True
    assert window.monitor_labels["resource_usage"].isVisible() is False
    for button in [
        window.monitor_copy_path,
        window.monitor_open_output,
        window.monitor_play_output,
        window.monitor_play_latest,
        window.monitor_stop_audio,
    ]:
        assert button.isVisible() is True
        assert button.minimumWidth() == 0


def test_monitor_restored_oversized_width_is_clamped(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    QSettings("S Talking", "S Talking").setValue("main_window/monitor_width", 900)
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    window.resize(1000, 700)
    qt_app.processEvents()
    window.restore_layout_state()

    assert window.monitor_dock.width() <= window.safe_monitor_width(900)


def test_smaller_main_window_layout_remains_usable(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    window.resize(1000, 700)
    qt_app.processEvents()
    window.clamp_monitor_width()

    assert window.monitor_dock.width() <= window.safe_monitor_width(10_000)
    assert window.table.minimumSizeHint().width() < window.width()


def test_report_metrics(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    metrics = {
        "average_seconds_per_job": 3.5,
        "files_per_minute": 12.0,
        "characters_per_minute": 1200.0,
        "active_generation_time": 20.0,
        "paused_time": 5.0,
        "stopped_by_user": True,
        "peak_concurrent_jobs": 1,
        "final_queue_counts": {"pending": 1, "running": 0, "completed": 1, "failed": 0, "skipped": 0},
    }

    report = container.report_service.create_generation_report(
        project=None,
        settings=AppSettings(provider="mock"),
        jobs=[TTSJob(row_number=2, filename="one.wav", text="one", status=JobStatus.COMPLETED)],
        output_dir=tmp_path / "out",
        summary={"total": 1, "completed": 1, "failed": 0, "skipped": 0, "stopped": True},
        started_at=datetime.now(timezone.utc),
        monitor_metrics=metrics,
    )

    summary = json.loads(report.summary_json.read_text(encoding="utf-8"))
    assert summary["monitor_metrics"]["files_per_minute"] == 12.0
    markdown = report.summary_md.read_text(encoding="utf-8")
    html = report.report_html.read_text(encoding="utf-8")
    assert "Average job duration: 4 s" in markdown
    assert "Files/minute: 12" in markdown
    assert "Characters/minute: 1,200" in markdown
    assert "Monitor Metrics" in html
    assert "20 s" in html
