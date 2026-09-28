"""B8.2B Stage 3B: cancellable/age-gated startup sweep and Qt-thread boundary."""
from __future__ import annotations

import ast
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SERVICE_FILE = ROOT / "app/services/startup_recovery_service.py"
GUI_FILE = ROOT / "app/gui/main.py"


def _isolated_service():
    """Load the real class without importing Qt-only package initializer in CI."""
    source = ast.parse(SERVICE_FILE.read_text(encoding="utf-8"))
    node = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "StartupRecoveryService")
    namespace = {
        "Path": Path,
        "time": time,
        "Event": threading.Event,
        "StartupRecoveryState": lambda: SimpleNamespace(temporary_files_removed=0),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SERVICE_FILE), "exec"), namespace)
    return namespace["StartupRecoveryService"]


def _service(tmp_path):
    cls = _isolated_service()
    service = cls.__new__(cls)
    service.runtime = SimpleNamespace(
        default_output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        artifacts_dir=tmp_path / "artifacts",
    )
    return service


def test_stage3b_background_cleanup_preserves_recent_temp_and_all_audio(tmp_path):
    service = _service(tmp_path)
    root = service.runtime.default_output_dir
    root.mkdir()
    old_temp = root / "old" / "part.partial"
    old_temp.parent.mkdir()
    old_temp.write_bytes(b"old partial")
    old_audio = root / "old" / "s_talking_demo.wav"
    old_audio.write_bytes(b"this might be a finished output")
    new_temp = root / "live.part"
    new_temp.write_bytes(b"an active generation")
    old_time = time.time() - 3 * 86400
    os.utime(old_temp, (old_time, old_time))
    os.utime(old_audio, (old_time, old_time))

    removed = service.clean_stale_temporary_audio(
        min_age_seconds=86400, include_audio=False, stop_event=threading.Event(),
    )
    assert removed == 1
    assert not old_temp.exists()
    assert old_audio.read_bytes() == b"this might be a finished output"
    assert new_temp.read_bytes() == b"an active generation"


def test_stage3b_cancelled_cleanup_never_deletes_files(tmp_path):
    service = _service(tmp_path)
    root = service.runtime.default_output_dir
    root.mkdir()
    temp = root / "stale.tmp"
    temp.write_bytes(b"leave intact")
    event = threading.Event()
    event.set()
    assert service.clean_stale_temporary_audio(stop_event=event) == 0
    assert temp.read_bytes() == b"leave intact"


def test_stage3b_legacy_recover_still_cleans_and_deferred_recover_does_not(tmp_path):
    service = _service(tmp_path)
    output = service.runtime.default_output_dir
    output.mkdir()
    temp = output / "stale.partial"
    temp.write_bytes(b"old")
    service.database = SimpleNamespace(initialize=lambda: None)
    service.job_repository = SimpleNamespace(reset_all_interrupted=lambda: 0)
    service.project_repository = SimpleNamespace(list_recent=lambda _: [])
    service.runtime.settings_path = tmp_path / "missing_settings.json"
    deferred = service.recover(defer_temporary_cleanup=True)
    assert deferred.temporary_files_removed == 0 and temp.exists()
    normal = service.recover()
    assert normal.temporary_files_removed == 1 and not temp.exists()


def test_stage3b_gui_schedules_background_sweep_without_qt_or_db_in_worker():
    tree = ast.parse(GUI_FILE.read_text(encoding="utf-8"))
    window = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    funcs = {n.name: ast.get_source_segment(GUI_FILE.read_text(encoding="utf-8"), n)
             for n in window.body if isinstance(n, ast.FunctionDef)}
    startup = funcs["run_startup_recovery"]
    worker = funcs["_start_background_startup_cleanup"]
    assert "recover(defer_temporary_cleanup=True)" in startup
    assert "self._start_background_startup_cleanup()" in startup
    assert "threading.Thread(target=sweep" in worker
    assert "daemon=True" in worker
    assert "min_age_seconds=86400, include_audio=False" in worker
    assert "ready.emit(outcome)" in worker
    assert "self._startup_cleanup_stop.set()" in funcs["closeEvent"]
    # No UI, repositories, or session restore may run in the worker closure.
    sweep = worker.split("        def sweep():", 1)[1].split("        threading.Thread", 1)[0]
    assert "self." not in sweep and "database" not in sweep and "QApplication" not in sweep


def test_stage3b_background_worker_returns_without_waiting_for_filesystem():
    """Execute the actual MainWindow method with a blocked filesystem fake."""
    source = GUI_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    window = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    method = next(n for n in window.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_start_background_startup_cleanup")
    namespace = {"threading": threading}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                 str(GUI_FILE), "exec"), namespace)
    unblock = threading.Event()
    completed = threading.Event()
    received = []

    def slow_clean(**options):
        assert options["min_age_seconds"] == 86400
        assert options["include_audio"] is False
        assert options["stop_event"] is stop_event
        assert unblock.wait(2)
        return 7

    def receive(value):
        received.append(value)
        completed.set()

    stop_event = threading.Event()
    fake_window = SimpleNamespace(
        context=SimpleNamespace(startup_recovery_service=SimpleNamespace(
            clean_stale_temporary_audio=slow_clean,
        )),
        _startup_cleanup_stop=stop_event,
        _startup_cleanup_ready=SimpleNamespace(emit=receive),
    )
    try:
        start = time.monotonic()
        namespace["_start_background_startup_cleanup"](fake_window)
        assert time.monotonic() - start < 0.2
        assert not completed.is_set()
        unblock.set()
        assert completed.wait(3)
        assert received == [7]
    finally:
        unblock.set()
