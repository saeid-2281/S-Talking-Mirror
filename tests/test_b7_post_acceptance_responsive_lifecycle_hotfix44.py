from __future__ import annotations

import inspect
import sys
import threading
import time
from pathlib import Path

from app.gui.main import MainWindow
from app.gui.worker import GenerationWorker
from app.models.domain import AppSettings, TTSJob


def test_h44_frozen_runtime_defaults_to_scalable_model_view(monkeypatch) -> None:
    monkeypatch.delenv("S_TALKING_QUEUE_MODEL_VIEW", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert MainWindow.queue_model_view_enabled(object()) is True

    monkeypatch.setenv("S_TALKING_QUEUE_MODEL_VIEW", "0")
    assert MainWindow.queue_model_view_enabled(object()) is False


def test_h44_project_transition_guard_never_waits_on_gui_thread() -> None:
    source = inspect.getsource(MainWindow._project_transition_ready)

    assert "wait_until_idle" not in source
    assert ".wait(" not in source
    assert "thread.isRunning()" in source
    assert "Stop the active generation before closing or switching projects." in source


def test_h44_project_reset_does_not_reenter_qt_event_loop() -> None:
    source = inspect.getsource(MainWindow._reset_project_runtime_state)

    assert "QApplication.processEvents" not in source
    assert "self.generation_controller.clear_jobs()" in source
    assert "self.monitor_service.reset()" in source


def test_h44_stop_dispatches_provider_cancellation_off_caller_thread(tmp_path: Path) -> None:
    worker = GenerationWorker(
        [TTSJob(row_number=1, text="Hej", filename="001.wav")],
        AppSettings(provider="mock"),
        tmp_path / "out",
        tmp_path / "jobs.sqlite3",
        "project",
    )
    cancelled = threading.Event()
    cancel_thread_ids: list[int] = []
    caller_thread_id = threading.get_ident()

    class SlowProvider:
        def cancel(self) -> None:
            cancel_thread_ids.append(threading.get_ident())
            time.sleep(0.35)
            cancelled.set()

    worker._provider = SlowProvider()

    started = time.perf_counter()
    worker.stop()
    elapsed = time.perf_counter() - started

    assert worker.stop_requested is True
    assert elapsed < 0.15
    assert cancelled.wait(2.0)
    assert cancel_thread_ids
    assert cancel_thread_ids[0] != caller_thread_id


def test_h44_stop_dispatch_is_single_shot(tmp_path: Path) -> None:
    worker = GenerationWorker(
        [TTSJob(row_number=1, text="Hej", filename="001.wav")],
        AppSettings(provider="mock"),
        tmp_path / "out",
        tmp_path / "jobs.sqlite3",
        "project",
    )
    calls = 0
    finished = threading.Event()

    class Provider:
        def cancel(self) -> None:
            nonlocal calls
            calls += 1
            finished.set()

    worker._provider = Provider()
    worker.stop()
    worker.stop()

    assert finished.wait(1.0)
    assert calls == 1
