"""B8.2B Stage 2: control lifecycle evidence cannot hold up the GUI."""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / "app/services/run_ledger_dispatcher.py"
spec = importlib.util.spec_from_file_location("b82b_ledger_dispatcher_under_test", source)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
RunLedgerDispatcher = module.RunLedgerDispatcher


class _Ledger:
    def __init__(self):
        self.calls = []
        self.block = threading.Event()
        self.block.set()
        self.lock = threading.Lock()

    def record_status(self, path, status, *, metrics=None):
        self.block.wait(5)
        with self.lock:
            self.calls.append(("status", str(path), status, dict(metrics or {}), threading.get_ident()))
        return SimpleNamespace(path=path, status=status)

    def finalize(self, path, result, **evidence):
        with self.lock:
            self.calls.append(("finalize", str(path), result, dict(evidence), threading.get_ident()))
        return SimpleNamespace(path=path, status=result, run_id="run", ledger_digest="abcd" * 16)


def test_status_enqueue_returns_while_disk_io_is_blocked():
    service = _Ledger()
    service.block.clear()
    dispatcher = RunLedgerDispatcher(service)
    received = []
    called_on_gui = threading.get_ident()
    start = time.perf_counter()
    future = dispatcher.status(Path("ledger.json"), "paused", {"retry_events": 1}, lambda *args: received.append(args))
    elapsed = time.perf_counter() - start
    try:
        assert elapsed < 0.35
        assert not future.done()
        service.block.set()
        assert future.result(timeout=5).status == "paused"
        assert service.calls[0][-1] != called_on_gui
        assert received[0][0] == "status" and received[0][3] == ""
    finally:
        service.block.set()
        dispatcher.close()


def test_terminal_write_follows_every_nonterminal_status_in_fifo_order():
    service = _Ledger()
    service.block.clear()
    dispatcher = RunLedgerDispatcher(service)
    def callback(*args):
        return None

    futures = [dispatcher.status(Path("run-a.json"), status, {}, callback) for status in ("running", "paused", "running", "stopping")]
    final = dispatcher.finalize(Path("run-a.json"), "cancelled", callback, summary={"stopped": True})
    try:
        service.block.set()
        for future in futures + [final]:
            future.result(timeout=5)
        assert [(entry[0], entry[2]) for entry in service.calls] == [
            ("status", "running"), ("status", "paused"), ("status", "running"),
            ("status", "stopping"), ("finalize", "cancelled"),
        ]
        assert {entry[1] for entry in service.calls} == {"run-a.json"}
        assert len({entry[-1] for entry in service.calls}) == 1
    finally:
        service.block.set()
        dispatcher.close()


def test_mutable_metrics_are_snapshotted_before_crossing_thread_boundary():
    service = _Ledger()
    service.block.clear()
    dispatcher = RunLedgerDispatcher(service)
    metrics = {"retry_events": 3}
    try:
        future = dispatcher.status(Path("ledger.json"), "paused", metrics, lambda *args: None)
        metrics["retry_events"] = 99
        service.block.set()
        future.result(timeout=5)
        assert service.calls[0][3] == {"retry_events": 3}
    finally:
        service.block.set()
        dispatcher.close()


def test_worker_errors_are_reported_without_leaking_exception_contents():
    class Broken:
        def record_status(self, *args, **kwargs):
            raise ValueError("secret=never-log-this")

    dispatcher = RunLedgerDispatcher(Broken())
    results = []
    try:
        future = dispatcher.status(Path("ledger.json"), "paused", {}, lambda *args: results.append(args))
        try:
            future.result(timeout=5)
        except ValueError:
            pass
        assert results and results[0][2] is None
        assert results[0][3] == "ValueError"
        assert "never-log-this" not in repr(results)
    finally:
        dispatcher.close()


def test_close_preserves_pending_evidence_and_does_not_wait_for_disk():
    service = _Ledger()
    service.block.clear()
    dispatcher = RunLedgerDispatcher(service)
    outcomes = []
    future = dispatcher.status(Path("ledger.json"), "paused", {}, lambda *args: outcomes.append(args))
    start = time.perf_counter()
    dispatcher.close()
    assert time.perf_counter() - start < 0.35
    service.block.set()
    future.result(timeout=5)
    assert service.calls[0][2] == "paused"
    assert not outcomes  # A destroyed Qt window cannot receive callbacks.


def test_mainwindow_keeps_durable_sidecar_and_deferred_fifo_terminal_evidence():
    source_text = (Path(__file__).resolve().parents[1] / "app/gui/main.py").read_text(encoding="utf-8")
    sync = source_text.split("    def sync_execution_lifecycle_status(", 1)[1].split("    def sync_execution_session(", 1)[0]
    lifecycle = source_text.split("    def sync_intelligent_tts_run_ledger(", 1)[1].split("    def finalize_intelligent_tts_run_ledger(", 1)[0]
    terminal = source_text.split("    def finalize_intelligent_tts_run_ledger(", 1)[1].split('    @trace_gui_action("sync_execution_lifecycle_status")', 1)[0]
    assert "generation_execution_session_service.record_lifecycle_status(" in sync
    assert "self.sync_intelligent_tts_run_ledger(status,metrics)" in sync
    assert "self._run_ledger_dispatcher.status(" in lifecycle
    assert "self._run_ledger_dispatcher.finalize(" in terminal
    assert "self.generation_controller.start(" not in lifecycle + terminal
    assert "self.provider.setCurrent" not in lifecycle + terminal
