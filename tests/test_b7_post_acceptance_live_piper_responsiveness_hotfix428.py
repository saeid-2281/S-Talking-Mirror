from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.gui.widgets.application_shell import GenerationStatusStrip
from app.gui.worker import GenerationWorker
from app.models import AppSettings, TTSJob
from app.services.generation_monitor_service import GenerationMonitorService


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class _Recovery:
    def __init__(self) -> None:
        self.saved = 0
        self.discarded = 0

    def save(self, **_kwargs) -> None:
        self.saved += 1

    def discard(self) -> None:
        self.discarded += 1


def test_h428_minimal_daily_stop_has_stable_visible_home(qt_app) -> None:
    strip = GenerationStatusStrip(
        start=lambda: None,
        pause=lambda: None,
        stop=lambda: None,
        show_preflight=lambda: None,
    )
    strip.show()
    strip.set_minimal_daily_mode(True)
    qt_app.processEvents()

    assert strip.stop_button.isVisible()
    assert not strip.stop_button.isEnabled()

    strip.stop_button.setEnabled(True)
    strip.set_runtime_active(True)
    qt_app.processEvents()

    assert strip.stop_button.isVisible()
    assert strip.stop_button.isEnabled()


def test_h428_piper_forces_serial_local_scheduling(tmp_path: Path) -> None:
    jobs = [
        TTSJob(row_number=2, filename="a.wav", text="a"),
        TTSJob(row_number=3, filename="b.wav", text="b"),
    ]
    plan = SimpleNamespace(scheduling_enabled=True, maximum_concurrency=8, candidates=())

    piper = GenerationWorker(
        jobs,
        AppSettings(provider="piper"),
        tmp_path / "out",
        tmp_path / "jobs.sqlite3",
        "project",
        orchestration_plan=plan,
    )
    cloud = GenerationWorker(
        jobs,
        AppSettings(provider="elevenlabs"),
        tmp_path / "out2",
        tmp_path / "jobs2.sqlite3",
        "project2",
        orchestration_plan=plan,
    )

    assert piper._concurrent_scheduling() is False
    assert cloud._concurrent_scheduling() is True


def test_h428_recovery_snapshot_is_rate_limited_for_large_batch_progress(tmp_path: Path) -> None:
    clock = _Clock()
    recovery = _Recovery()
    service = GenerationMonitorService(clock=clock, recovery_service=recovery)
    jobs = [
        TTSJob(row_number=index, filename=f"{index}.wav", text="hej")
        for index in range(2, 102)
    ]
    settings = AppSettings(provider="piper")

    service.start_run(
        jobs,
        provider="piper",
        output_dir=tmp_path,
        settings=settings,
        project_key="project",
    )
    assert recovery.saved == 1

    for offset in (0.1, 0.2, 0.3, 0.9, 1.5):
        clock.value = 100.0 + offset
        service.handle_progress(
            jobs,
            status="running",
            name="2.wav",
            duration=0.0,
            retry=1,
            error="",
        )
    assert recovery.saved == 1

    clock.value = 102.1
    service.handle_progress(
        jobs,
        status="completed",
        name="2.wav",
        duration=0.5,
        retry=1,
        error="",
    )
    assert recovery.saved == 2

    clock.value = 102.2
    service.finish({"stopped": True})
    assert recovery.saved == 3


def test_h428_main_progress_path_is_incremental_and_throttled() -> None:
    import app.gui.main as main_module

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    refresh_block = source[
        source.index("    def refresh_progress_row"):
        source.index("    def set_generation_controls")
    ]
    start_block = source[
        source.index("    def start(self):"):
        source.index("    def begin_intelligent_tts_artifact_plan")
    ]

    assert "self.queue_adapter.refresh_rows([job])" in refresh_block
    assert "self.schedule_generation_dashboard_refresh()" in refresh_block
    assert "QTimer.singleShot(350,self.flush_generation_dashboard_refresh)" in refresh_block
    assert "self.render_queue(); return" not in refresh_block.split(
        "if hasattr(self,'queue_adapter') and self.queue_adapter.is_model_view:", 1
    )[1].split(
        "if self.queue_filter.currentText()", 1
    )[0]
    assert start_block.index("self.set_generation_controls(active=True)") < start_block.index(
        "self.generation_controller.start("
    )
    assert start_block.index("QApplication.processEvents()") < start_block.index(
        "self.generation_controller.start("
    )


def test_h428_activity_log_is_bounded_for_long_batches() -> None:
    from app.gui.widgets import application_shell

    source = Path(application_shell.__file__).read_text(encoding="utf-8")
    assert "setMaximumBlockCount(2000)" in source
