from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from app.models import AppSettings, TTSJob
from app.services.generation_live_operations_service import GenerationLiveOperationsService
from app.services.generation_monitor_service import GenerationMonitorService


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/gui/main.py"
PREFLIGHT = ROOT / "app/services/preflight_service.py"
RECOVERY = ROOT / "app/services/generation_recovery_service.py"


class _ThreadRecordingRecovery:
    def __init__(self) -> None:
        self.saved_on_thread: int | None = None
        self.saved = threading.Event()
        self.discarded = 0

    def save(self, **_kwargs) -> None:
        self.saved_on_thread = threading.get_ident()
        self.saved.set()

    def discard(self) -> None:
        self.discarded += 1


def test_h429_preflight_duplicate_text_detection_is_linearized() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")
    block = source[
        source.index("        duplicate_names ="):
        source.index("        pending_characters =")
    ]

    assert "text_counts = Counter(text_hashes)" in block
    assert "duplicate_text_values" in block
    assert "text_hashes.count(" not in block
    assert "next(item for item in jobs" not in block
    assert "jobs_by_row = {job.row_number: job for job in jobs}" in source
    assert "next(job for job in jobs if job.row_number == item.row)" not in source


def test_h429_large_queue_recovery_snapshot_leaves_gui_thread(tmp_path: Path) -> None:
    recovery = _ThreadRecordingRecovery()
    service = GenerationMonitorService(recovery_service=recovery)
    jobs = [
        TTSJob(row_number=index + 1, filename=f"{index + 1}.wav", text="hej")
        for index in range(service.large_queue_recovery_threshold + 10)
    ]
    gui_thread = threading.get_ident()

    service.start_run(
        jobs,
        provider="piper",
        output_dir=tmp_path,
        settings=AppSettings(provider="piper"),
        project_key="large-project",
    )

    assert recovery.saved.wait(2.0)
    assert recovery.saved_on_thread is not None
    assert recovery.saved_on_thread != gui_thread
    service.finish({"stopped": False})


def test_h429_live_operations_reuses_monitor_counts_for_active_run() -> None:
    jobs = [
        TTSJob(row_number=1, filename="1.wav", text="one"),
        TTSJob(row_number=2, filename="2.wav", text="two"),
    ]
    monitor = SimpleNamespace(
        total=21_805,
        processed=123,
        pending=21_680,
        running=1,
        completed=120,
        failed=2,
        skipped=1,
        retries=4,
        remaining_eta_seconds=90.0,
        average_seconds_per_completed_job=1.5,
        current_filename="124.wav",
        current_status="Running",
    )

    snapshot = GenerationLiveOperationsService().snapshot(
        jobs,
        monitor_state=monitor,
        active=True,
        paused=False,
        failure_summary={"retryable": 2},
    )

    assert snapshot.total == 21_805
    assert snapshot.completed == 120
    assert snapshot.failed == 2
    assert snapshot.pending == 21_680
    assert snapshot.running == 1
    assert snapshot.skipped == 1


def test_h429_monitor_render_and_dashboard_have_event_backpressure() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert "self.monitor_service.updated.connect(self.schedule_monitor_render)" in source
    assert "QTimer.singleShot(delay,self.flush_monitor_render)" in source
    assert "delay=250 if self.generation_controller.is_active else 0" in source
    assert "QTimer.singleShot(750,self.flush_generation_dashboard_refresh)" in source

    dashboard = source[
        source.index("    def dashboard(self, *, runtime_lightweight: bool = False):"):
        source.index(
            "    def create_report",
            source.index("    def dashboard(self, *, runtime_lightweight: bool = False):"),
        )
    ]
    assert "runtime_lightweight and self.generation_controller.is_active and monitor_state.total" in dashboard
    assert "characters=monitor_state.total_characters" in dashboard
    assert "eta_seconds=monitor_state.remaining_eta_seconds" in dashboard


def test_h429_progress_path_uses_cached_job_lookup_and_latest_output() -> None:
    source = MAIN.read_text(encoding="utf-8")
    progress_block = source[
        source.index("    def refresh_progress_row"):
        source.index("    def set_generation_controls")
    ]

    assert "self._generation_job_lookup.get(target)" in progress_block
    assert "self._latest_completed_output_cache=completed_path" in progress_block
    assert "self._latest_completed_output_cache if self.generation_controller.is_active" in source


def test_h429_large_launch_yields_and_reverifies_before_worker_start() -> None:
    source = MAIN.read_text(encoding="utf-8")
    block = source[
        source.index("    def start(self):"):
        source.index("    def begin_intelligent_tts_artifact_plan")
    ]

    final_comment = "User input is processed between large evidence stages"
    assert final_comment in block
    final_verify = block.index(final_comment)
    worker_start = block.index("self.generation_controller.start(")
    assert final_verify < worker_start
    assert "QApplication.processEvents()" in block[:final_verify]
    assert "launch_context_changed_during_preparation" in block[final_verify:worker_start]


def test_h429_recovery_file_write_avoids_second_pretty_sorted_dump() -> None:
    source = RECOVERY.read_text(encoding="utf-8")
    write_block = source[
        source.index("        temporary.write_text("):
        source.index("        temporary.replace(self.path)")
    ]

    assert 'separators=(",", ":")' in write_block
    assert "indent=2" not in write_block
    assert "sort_keys=True" not in write_block
