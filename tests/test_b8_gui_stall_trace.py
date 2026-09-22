"""B8.2 metadata-only GUI trace contract; standard-library deterministic tests."""
from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path

import pytest

# Import this pure standard-library module directly so the diagnostic unit lane
# also runs on build hosts without the full PySide6 application environment.
source = Path(__file__).resolve().parents[1] / "app/services/gui_stall_trace.py"
spec = importlib.util.spec_from_file_location("b82_stall_trace_under_test", source)
trace_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace_module)
GuiStallTrace = trace_module.GuiStallTrace
trace_gui_action = trace_module.trace_gui_action


def _clock():
    value = [0.0]
    return value, lambda: value[0]


def _events(tracer):
    return [json.loads(line) for line in tracer.path.read_text(encoding="utf-8").splitlines()]


def test_trace_records_long_action_without_argument_values(tmp_path):
    tick, clock = _clock()
    tracer = GuiStallTrace(tmp_path, perf=clock, start_worker=False)
    with tracer.span("close_project"):
        tick[0] = 0.42
    tracer.close()
    events = _events(tracer)
    assert any(e["event"] == "action_finished" and e["action"] == "close_project"
               and e["duration_ms"] == 420 for e in events)
    assert "project_file" not in tracer.path.read_text(encoding="utf-8")


def test_trace_differentiates_stall_and_recovery(tmp_path, monkeypatch):
    tick, clock = _clock()
    tracer = GuiStallTrace(tmp_path, perf=clock, start_worker=False)
    monkeypatch.setattr(tracer, "_sample_gui_stack", lambda: [])
    tick[0] = 1.8
    tracer.poll()
    tracer.poll()
    tick[0] = 1.9
    tracer.pulse()
    tracer.close()
    events = _events(tracer)
    assert [e["event"] for e in events].count("gui_stall") == 1
    assert [e["event"] for e in events].count("gui_recovered") == 1


def test_trace_nested_spans_report_outermost_action(tmp_path, monkeypatch):
    tick, clock = _clock()
    tracer = GuiStallTrace(tmp_path, perf=clock, start_worker=False)
    monkeypatch.setattr(tracer, "_sample_gui_stack", lambda: [])
    with tracer.span("_open_project_path"):
        with tracer.span("load_csv"):
            tick[0] = 2.0
            tracer.poll()
    tracer.close()
    stalls = [event for event in _events(tracer) if event["event"] == "gui_stall"]
    assert len(stalls) == 1
    assert stalls[0]["action"] == "_open_project_path"


def test_wrapper_is_noop_when_tracer_not_enabled():
    class Window:
        @trace_gui_action("pause")
        def pause(self, token):
            return token
    assert Window().pause("unchanged") == "unchanged"


def test_trace_rejects_dynamic_action_and_never_logs_locals(tmp_path):
    with pytest.raises(ValueError):
        trace_gui_action("/path/private.csv")
    tracer = GuiStallTrace(tmp_path, start_worker=False)
    sensitive = "very-private-project-name"
    @trace_gui_action("start")
    def task(self, payload):
        return payload
    class Window:
        _b82_gui_trace = tracer
    assert task(Window(), sensitive) == sensitive
    tracer.close()
    assert sensitive not in tracer.path.read_text(encoding="utf-8")


def test_trace_stack_uses_module_function_and_line_only(tmp_path, monkeypatch):
    tracer = GuiStallTrace(tmp_path, start_worker=False)
    class Code:
        co_name = "safe_function"
    class Frame:
        f_globals = {"__name__": "app.gui.main"}
        f_code = Code()
        f_lineno = 123
        f_back = None
        f_locals = {"secret": "not-for-evidence"}
    monkeypatch.setattr(trace_module.sys, "_current_frames",
                        lambda: {threading.get_ident(): Frame()})
    assert tracer._sample_gui_stack() == [{"module": "app.gui.main", "function": "safe_function", "line": 123}]
    tracer.close()
    assert "not-for-evidence" not in tracer.path.read_text(encoding="utf-8")


def test_trace_opt_in_off_does_not_create_file(tmp_path, monkeypatch):
    monkeypatch.delenv("S_TALKING_B82_GUI_TRACE", raising=False)
    monkeypatch.setenv("S_TALKING_B82_TRACE_DIR", str(tmp_path))
    assert trace_module.start_gui_stall_trace(object()) is None
    assert not list(tmp_path.glob("S-Talking-B82-GUI-Trace-*.jsonl"))
