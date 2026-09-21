"""B8.1: the external heartbeat probe is privacy-safe and fail-observable."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "b8_gui_responsiveness_probe.py"
spec = importlib.util.spec_from_file_location("b8_gui_responsiveness_probe", MODULE)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def test_b8_stall_tracker_requires_two_misses_and_recovers() -> None:
    tracker = probe.StallTracker(threshold=2)
    assert tracker.sample(None) == "no_window"
    assert tracker.sample(False) == "single_miss"
    assert tracker.sample(False) == "stall_detected"
    assert tracker.sample(False) == "stall_active"
    assert tracker.sample(True) == "recovered"
    assert tracker.sample(True) == "responsive"
    summary = tracker.summary(process_exited=True, elapsed_seconds=3)
    assert summary["stall_events"] == 1
    assert summary["max_consecutive_misses"] == 3
    assert summary["samples"] == 5
    assert summary["automated_result"] == "STALL_OBSERVED"
    assert summary["manual_acceptance_required"] is True


def test_b8_no_window_is_not_misreported_as_a_gui_freeze() -> None:
    tracker = probe.StallTracker()
    assert tracker.sample(None) == "no_window"
    assert tracker.sample(None) == "no_window"
    assert tracker.summary(process_exited=False, elapsed_seconds=2)["automated_result"] == "NO_WINDOW_OBSERVED"
    assert tracker.stall_events == 0
    assert tracker.sample(False) == "single_miss"
    assert tracker.sample(None) == "no_window"
    assert tracker.sample(False) == "single_miss"
    assert tracker.stall_events == 0


def test_b8_clean_heartbeat_does_not_claim_manual_acceptance() -> None:
    tracker = probe.StallTracker()
    for _ in range(10):
        assert tracker.sample(True) == "responsive"
    report = tracker.summary(process_exited=True, elapsed_seconds=5)
    assert report["automated_result"] == "NO_CONFIRMED_STALL_OBSERVED"
    assert report["manual_acceptance_required"] is True


def test_b8_observer_emits_redacted_only_metadata(tmp_path: Path) -> None:
    ticks = iter([0.0, 0.25, 0.75, 1.0, 1.25, 1.5, 1.75])

    class FakeProcess:
        pid = 1234

        def __init__(self) -> None:
            self.polls = 0

        def poll(self) -> int | None:
            self.polls += 1
            return None if self.polls < 4 else 0

    ping_results = iter([True, False, False])
    report = probe.run_probe(
        FakeProcess(), out_dir=tmp_path, interval_seconds=0.01,
        timeout_ms=250, hang_after=2, window_wait_seconds=60,
        find_window=lambda _pid: 99,
        ping=lambda _hwnd, **_kw: next(ping_results),
        clock=lambda: next(ticks), sleep=lambda _seconds: None,
    )
    assert report["automated_result"] == "STALL_OBSERVED"
    assert report["events_file"].endswith(".jsonl")
    events = (tmp_path / str(report["events_file"])).read_text(encoding="utf-8")
    assert "stall_detected" in events
    assert "time_utc" in events
    assert "1234" not in events  # PID not persisted; no identifying metadata.
    assert "project" not in events.casefold()
    assert "credential" not in events.casefold()
    assert json.loads((tmp_path / "S-Talking-B8-GUI-Heartbeat-last-run.json").read_text())["stall_events"] == 1


def test_b8_probe_is_separate_and_does_not_modify_frozen_runtime() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert "WM_NULL" in source
    assert "GetWindowText" not in source
    assert "quality-gate.ps1" not in source
    assert "git push" not in source
    assert "os.environ" not in source
    assert "api-profiles.json" not in source
    assert "workspace-profiles.json" not in source
