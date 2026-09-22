"""Opt-in, metadata-only B8.2 GUI-stall evidence. Never serializes locals or file paths.

This module has no side effects on import; the frozen application enables it only
when S_TALKING_B82_GUI_TRACE=1 is set by the diagnostic launcher.
"""
from __future__ import annotations

import functools
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_ALLOWED_ACTIONS = frozenset({
    "_finish_deferred_startup", "new_project", "_reset_project_runtime_state",
    "_open_project_path", "open_project", "_continue_project_path",
    "open_project_continuity", "close_project", "load_csv", "render_queue",
    "refresh_monitor_queue", "refresh_generation_live_operations", "update_status_bar",
    "render_project_sources", "run_preflight", "start",
    "sync_execution_lifecycle_status", "finish_execution_session", "pause", "stop",
    "dashboard",
})


def trace_gui_action(action):
    """No-op wrapper unless an explicitly enabled tracer is present on window."""
    if action not in _ALLOWED_ACTIONS:
        raise ValueError("Unexpected GUI action label")

    def decorate(func):
        @functools.wraps(func)
        def wrapped(self, *args, **kwargs):
            tracer = getattr(self, "_b82_gui_trace", None)
            if tracer is None:
                return func(self, *args, **kwargs)
            with tracer.span(action):
                return func(self, *args, **kwargs)
        return wrapped
    return decorate


class GuiStallTrace:
    """All disk writes are short JSONL records, with no app data or stack locals."""

    def __init__(self, output_dir, *, now=None, perf=None, interval=0.25,
                 stall_threshold=1.5, start_worker=True):
        self._clock = perf or time.monotonic
        self._utc_now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        self._interval = float(interval)
        self._threshold = float(stall_threshold)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._main_thread_id = threading.get_ident()
        self._last_pulse = self._clock()
        self._active = []
        self._stalled = False
        self._last_sample = 0.0
        self._closed = False
        self._sequence = 0
        root = Path(output_dir).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.path = root / f"S-Talking-B82-GUI-Trace-{stamp}-{os.getpid()}.jsonl"
        # Output location never appears inside the diagnostic records.
        self._stream = self.path.open("x", encoding="utf-8", buffering=1)
        self._emit("trace_started", threshold_ms=int(self._threshold * 1000))
        self._worker = None
        if start_worker:
            self._worker = threading.Thread(target=self._watch, name="B82GUIWatchdog", daemon=True)
            self._worker.start()

    def _emit(self, event, **fields):
        with self._lock:
            if self._closed:
                return
            self._sequence += 1
            payload = {"schema": 1, "sequence": self._sequence, "timestamp_utc": self._utc_now(),
                       "event": event, **fields}
            try:
                self._stream.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n")
            except OSError:
                # Evidence loss must never interrupt an active generation.
                self._closed = True
                try:
                    self._stream.close()
                except OSError:
                    pass

    @contextmanager
    def span(self, action):
        if action not in _ALLOWED_ACTIONS:
            raise ValueError("Unknown trace action")
        before = self._clock()
        with self._lock:
            self._active.append(action)
            depth = len(self._active)
        if depth == 1:
            self._emit("action_started", action=action)
        try:
            yield
        finally:
            elapsed = max(0.0, self._clock() - before)
            with self._lock:
                if self._active and self._active[-1] == action:
                    self._active.pop()
                elif action in self._active:
                    self._active.remove(action)
            if depth == 1 or elapsed >= 0.1:
                self._emit("action_finished", action=action, depth=depth,
                           duration_ms=round(elapsed * 1000, 1))

    def pulse(self):
        """Must be called on the Qt GUI thread, never from the watchdog."""
        current = self._clock()
        with self._lock:
            if self._closed:
                return
            delay = max(0.0, current - self._last_pulse)
            was_stalled = self._stalled
            self._last_pulse = current
            if was_stalled:
                self._stalled = False
        if was_stalled:
            self._emit("gui_recovered", heartbeat_delay_ms=round(delay * 1000, 1))

    def _sample_gui_stack(self):
        """Function and line identifiers only; no paths, source code, args or locals."""
        frames = sys._current_frames()
        frame = frames.get(self._main_thread_id)
        result = []
        while frame is not None and len(result) < 16:
            module = str(frame.f_globals.get("__name__", ""))
            if module == "app" or module.startswith("app."):
                # Do not serialize filesystem paths, function arguments or values.
                result.append({"module": module, "function": frame.f_code.co_name,
                               "line": int(frame.f_lineno)})
            frame = frame.f_back
        return result

    def poll(self):
        """Worker entry point; tests can call this deterministically without a thread."""
        current = self._clock()
        with self._lock:
            if self._closed:
                return
            delay = max(0.0, current - self._last_pulse)
            if delay < self._threshold:
                return
            newly_stalled = not self._stalled
            if newly_stalled:
                self._stalled = True
            if not newly_stalled and current - self._last_sample < 2.5:
                return
            self._last_sample = current
            action = self._active[0] if self._active else "none"
        self._emit("gui_stall" if newly_stalled else "gui_stall_sample",
                   heartbeat_delay_ms=round(delay * 1000, 1), action=action,
                   gui_stack=self._sample_gui_stack())

    def _watch(self):
        while not self._stop.wait(self._interval):
            try:
                self.poll()
            except (OSError, RuntimeError):
                # Diagnostic failures must not take down the audio application.
                return

    def close(self):
        self._stop.set()
        with self._lock:
            if self._closed:
                return
            self._emit("trace_finished")
            self._closed = True
            self._stream.close()


def start_gui_stall_trace(window):
    """Attach one opt-in GUI pulse timer after MainWindow initialization."""
    if os.environ.get("S_TALKING_B82_GUI_TRACE", "").strip() != "1":
        return None
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    destination = os.environ.get("S_TALKING_B82_TRACE_DIR")
    if not destination:
        return None  # Never write evidence to an implicit or private directory.
    try:
        tracer = GuiStallTrace(destination)
    except OSError:
        return None  # Observability must never block ordinary app startup.
    timer = QTimer(window)
    timer.setInterval(250)
    timer.timeout.connect(tracer.pulse)
    timer.start()
    tracer._qt_timer = timer
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(tracer.close)
    return tracer
