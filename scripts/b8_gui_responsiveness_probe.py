"""External, privacy-minimal GUI heartbeat probe for the accepted S-Talking Portable.

This script is intentionally *not* imported or launched by S-Talking. It observes
only whether the Windows GUI event loop responds to a WM_NULL message.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


@dataclass
class StallTracker:
    """Count consecutive missed Win32 heartbeats; no source content is recorded."""

    threshold: int = 2
    misses: int = 0
    stall_events: int = 0
    max_consecutive_misses: int = 0
    samples: int = 0
    responsive_samples: int = 0
    unresponsive_samples: int = 0
    in_stall: bool = False

    def sample(self, responsive: bool | None) -> str:
        """None means no visible app window; do not infer a GUI hang from that."""
        if responsive is None:
            # An absent window interrupts an unconfirmed missed-heartbeat streak.
            if not self.in_stall:
                self.misses = 0
            return "no_window"
        self.samples += 1
        if responsive:
            self.responsive_samples += 1
            self.misses = 0
            if self.in_stall:
                self.in_stall = False
                return "recovered"
            return "responsive"
        self.unresponsive_samples += 1
        self.misses += 1
        self.max_consecutive_misses = max(self.max_consecutive_misses, self.misses)
        if self.misses >= self.threshold and not self.in_stall:
            self.in_stall = True
            self.stall_events += 1
            return "stall_detected"
        return "stall_active" if self.in_stall else "single_miss"

    def summary(self, *, process_exited: bool, elapsed_seconds: float) -> dict[str, object]:
        return {
            "schema_version": 1,
            "process_exited": process_exited,
            "elapsed_seconds": round(max(0.0, elapsed_seconds), 3),
            "samples": self.samples,
            "responsive_samples": self.responsive_samples,
            "unresponsive_samples": self.unresponsive_samples,
            "stall_events": self.stall_events,
            "max_consecutive_misses": self.max_consecutive_misses,
            "final_stall_active": self.in_stall,
            "automated_result": (
                "STALL_OBSERVED" if self.stall_events else
                "NO_WINDOW_OBSERVED" if self.samples == 0 else
                "NO_CONFIRMED_STALL_OBSERVED"
            ),
            "manual_acceptance_required": True,
        }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def find_visible_main_window(process_id: int) -> int | None:
    """Find a visible top-level window for a PID without reading its title/content."""
    if sys.platform != "win32":
        raise RuntimeError("This probe requires Microsoft Windows.")
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    windows: list[int] = []

    @callback_type
    def visit(hwnd: int, _lparam: int) -> bool:
        owner = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(hwnd):
            windows.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(visit, 0)
    return windows[0] if windows else None


def probe_window(hwnd: int, *, timeout_ms: int) -> bool:
    """WM_NULL tests GUI dispatch; timeout indicates *possible* event-loop blocking."""
    if sys.platform != "win32":
        raise RuntimeError("This probe requires Microsoft Windows.")
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    result = ctypes.c_size_t(0)
    # WM_NULL=0, SMTO_ABORTIFHUNG=0x0002. Never send clicks or key events.
    return bool(user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, timeout_ms, ctypes.byref(result)))


def run_probe(
    process: subprocess.Popen[bytes],
    *,
    out_dir: Path,
    interval_seconds: float,
    timeout_ms: int,
    hang_after: int,
    window_wait_seconds: float,
    find_window: Callable[[int], int | None] = find_visible_main_window,
    ping: Callable[..., bool] = probe_window,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    event_file = out_dir / f"S-Talking-B8-GUI-Heartbeat-{stamp}.jsonl"
    summary_file = out_dir / f"S-Talking-B8-GUI-Heartbeat-{stamp}.json"
    last_summary = out_dir / "S-Talking-B8-GUI-Heartbeat-last-run.json"
    tracker = StallTracker(threshold=hang_after)
    started = clock()
    seen_window = False
    last_event = ""
    print("GUI_HEARTBEAT_MONITOR=STARTED", flush=True)
    print("Probe records only timestamps, heartbeat responses, and aggregate counters.", flush=True)
    print("Use the app normally; exit S-Talking to finish and save the report.", flush=True)
    try:
        with event_file.open("w", encoding="utf-8", newline="\n") as stream:
            while process.poll() is None:
                hwnd = find_window(process.pid)
                if hwnd is None:
                    state = tracker.sample(None)
                    if not seen_window and clock() - started > window_wait_seconds:
                        state = "startup_window_timeout"
                        print("GUI_HEARTBEAT_WINDOW_TIMEOUT=1", flush=True)
                        break
                else:
                    seen_window = True
                    state = tracker.sample(ping(hwnd, timeout_ms=timeout_ms))
                # The report does not include project, CSV, voice, account, title,
                # command line, environment, window text, or credential contents.
                stream.write(json.dumps({"time_utc": utc_timestamp(), "state": state}, separators=(",", ":")) + "\n")
                stream.flush()
                if state != last_event and state in {"stall_detected", "recovered", "startup_window_timeout"}:
                    print(f"GUI_HEARTBEAT_EVENT={state}", flush=True)
                last_event = state
                sleep(interval_seconds)
    except KeyboardInterrupt:
        print("GUI_HEARTBEAT_INTERRUPTED=1", flush=True)
    finally:
        result = tracker.summary(process_exited=process.poll() is not None, elapsed_seconds=clock() - started)
        result["events_file"] = event_file.name
        summary_file.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        last_summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("GUI_HEARTBEAT_RESULT=" + str(result["automated_result"]), flush=True)
        print("GUI_HEARTBEAT_REPORT=" + str(summary_file), flush=True)
        print("GUI_HEARTBEAT_LAST_RUN=" + str(last_summary), flush=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in external S-Talking GUI responsiveness probe")
    parser.add_argument("--exe", required=True, type=Path, help="Explicit frozen S-Talking.exe path")
    parser.add_argument("--output", type=Path, default=Path("C:/zip-for-GPT"))
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--timeout-ms", type=int, default=250)
    parser.add_argument("--hang-after", type=int, default=2)
    parser.add_argument("--window-wait", type=float, default=60.0)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows is required; this script does not modify the S-Talking source.")
    if args.interval <= 0 or args.timeout_ms <= 0 or args.hang_after < 2 or args.window_wait <= 0:
        parser.error("All timing arguments must be positive; hang-after must be at least 2.")
    exe = args.exe.resolve()
    if exe.name.casefold() != "s-talking.exe" or not exe.is_file():
        parser.error("--exe must point to an existing S-Talking.exe; nothing was launched.")
    process = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    report = run_probe(
        process, out_dir=args.output, interval_seconds=args.interval,
        timeout_ms=args.timeout_ms, hang_after=args.hang_after,
        window_wait_seconds=args.window_wait,
    )
    # This exit status concerns monitor operation, NOT a B8 release gate.
    return 2 if report["automated_result"] in {"STALL_OBSERVED", "NO_WINDOW_OBSERVED"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
