from __future__ import annotations

import csv
import gc
import hashlib
import json
import os
import re
import sys
import threading
import time
import tracemalloc
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import app
from app.config.runtime import RuntimeConfig
from app.models.performance_stability import (
    PerformanceGate,
    PerformanceObservationRun,
    PerformanceSample,
    PerformanceStabilityPolicy,
    PerformanceStabilitySnapshot,
)


class PerformanceStabilityService:
    """Measure startup and long-run resource stability with bounded, private evidence.

    Metrics contain process counters only. The privacy contract excludes project text, filenames, API profiles,
    credentials, database rows and generated audio are never copied into samples or
    exports. Sampling is bounded and intentionally low frequency.
    """

    SCHEMA_VERSION = 1
    _SAFE_LABEL_RE = re.compile(r"[^0-9A-Za-z _.:+/-]+")
    _LABEL_AUTH_RE = re.compile(r"(?i)\bauthorization\b\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?[^\s,;]+")
    _LABEL_SECRET_RE = re.compile(r"(?i)\b(api[_-]?key|token|secret|password|credential)\b\s*[:=]\s*[^\s,;]+")
    _LABEL_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        metric_provider: Callable[[], dict[str, int]] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.runtime = runtime
        self.root = runtime.artifacts_dir / "performance-stability"
        self.samples_path = self.root / "samples.jsonl"
        self.runs_path = self.root / "runs.json"
        self.latest_snapshot_path = self.root / "latest-snapshot.json"
        self.policy_path = runtime.settings_path.parent / "performance-stability.json"
        self.exports_dir = self.root / "exports"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.perf_counter
        self._metric_provider = metric_provider
        self._sleep = sleeper or time.sleep
        self._process_started_at = self._monotonic()
        self._startup_elapsed_ms: int | None = None
        self._startup_ready_at = ""
        self._active_run: dict[str, Any] | None = None
        self._owns_tracemalloc = False
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def startup_ready(self) -> bool:
        return self._startup_elapsed_ms is not None

    @property
    def active_run_id(self) -> str:
        return str((self._active_run or {}).get("run_id") or "")

    def load_policy(self) -> PerformanceStabilityPolicy:
        try:
            payload = json.loads(self.policy_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            payload = None
        return PerformanceStabilityPolicy.from_dict(payload)

    def save_policy(self, policy: PerformanceStabilityPolicy) -> PerformanceStabilityPolicy:
        normalized = policy.normalized()
        self._write_json(self.policy_path, normalized.to_dict())
        return normalized

    def mark_startup_ready(self) -> PerformanceSample:
        with self._lock:
            if self._startup_elapsed_ms is None:
                self._startup_elapsed_ms = max(
                    0,
                    int(round((self._monotonic() - self._process_started_at) * 1000)),
                )
                self._startup_ready_at = self._now()
        return self.collect_sample(label="startup-ready", persist=True)

    def collect_sample(
        self,
        *,
        label: str = "manual",
        queue_total: int = 0,
        generation_active: bool = False,
        persist: bool = True,
        deep_metrics: bool = True,
    ) -> PerformanceSample:
        metrics = self._sample_metrics(deep=deep_metrics)
        sample = PerformanceSample(
            captured_at=self._now(),
            monotonic_seconds=float(self._monotonic()),
            label=self._safe_label(label),
            startup_elapsed_ms=self._startup_elapsed_ms,
            rss_bytes=max(0, int(metrics.get("rss_bytes", 0))),
            python_heap_bytes=max(0, int(metrics.get("python_heap_bytes", 0))),
            python_peak_bytes=max(0, int(metrics.get("python_peak_bytes", 0))),
            process_thread_count=max(0, int(metrics.get("process_thread_count", 0))),
            qt_active_thread_count=max(0, int(metrics.get("qt_active_thread_count", 0))),
            qt_widget_count=max(0, int(metrics.get("qt_widget_count", 0))),
            qt_top_level_count=max(0, int(metrics.get("qt_top_level_count", 0))),
            gc_object_count=max(0, int(metrics.get("gc_object_count", 0))),
            open_file_count=max(0, int(metrics.get("open_file_count", 0))),
            process_handle_count=max(0, int(metrics.get("process_handle_count", 0))),
            queue_total=max(0, int(queue_total)),
            generation_active=bool(generation_active),
        )
        if persist:
            with self._lock:
                self._append_sample(sample)
                if self._active_run is not None:
                    self._active_run["sample_count"] = int(self._active_run.get("sample_count", 0)) + 1
                    self._active_run["peak_rss_bytes"] = max(
                        int(self._active_run.get("peak_rss_bytes", 0)),
                        sample.rss_bytes,
                    )
        return sample

    def collect_background_sample(
        self,
        *,
        queue_total: int = 0,
        generation_active: bool = False,
    ) -> PerformanceSample:
        """Collect the periodic sample without expensive full-object enumeration.

        Background samples are used to track RSS/thread/handle growth. Full Qt widget
        and GC object counts remain available from manual samples, snapshots and
        managed observations where their diagnostic value justifies the extra work.
        """

        return self.collect_sample(
            label="background-light",
            queue_total=queue_total,
            generation_active=generation_active,
            persist=True,
            deep_metrics=False,
        )

    def start_observation(
        self,
        label: str = "long-run observation",
        *,
        expected_minutes: int | None = None,
    ) -> str:
        with self._lock:
            if self._active_run is not None:
                return str(self._active_run["run_id"])
            policy = self.load_policy()
            if not tracemalloc.is_tracing():
                tracemalloc.start(10)
                self._owns_tracemalloc = True
            first = self.collect_sample(label="observation-start", persist=True)
            run_id = f"perf-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
            self._active_run = {
                "run_id": run_id,
                "label": self._safe_label(label),
                "started_at": first.captured_at,
                "started_monotonic": first.monotonic_seconds,
                "expected_minutes": max(1, int(expected_minutes or policy.default_soak_minutes)),
                "sample_count": 1,
                "start_rss_bytes": first.rss_bytes,
                "start_python_heap_bytes": first.python_heap_bytes,
                "peak_rss_bytes": first.rss_bytes,
            }
            return run_id

    def finish_observation(self, *, status: str = "completed") -> PerformanceObservationRun | None:
        with self._lock:
            if self._active_run is None:
                return None
            final = self.collect_sample(label="observation-finish", persist=True)
            active = dict(self._active_run)
            duration = max(0.0, final.monotonic_seconds - float(active["started_monotonic"]))
            rss_growth = final.rss_bytes - int(active["start_rss_bytes"])
            python_growth = final.python_heap_bytes - int(active["start_python_heap_bytes"])
            growth_mb_per_hour = (
                (rss_growth / 1024**2) * (3600.0 / duration)
                if duration >= 1.0
                else 0.0
            )
            run_id = str(active["run_id"])
            report_path = self.root / "runs" / f"{run_id}.json"
            run = PerformanceObservationRun(
                run_id=run_id,
                label=str(active["label"]),
                started_at=str(active["started_at"]),
                finished_at=final.captured_at,
                status=self._safe_label(status),
                expected_minutes=int(active["expected_minutes"]),
                duration_seconds=round(duration, 3),
                sample_count=int(active["sample_count"]),
                start_rss_bytes=int(active["start_rss_bytes"]),
                end_rss_bytes=final.rss_bytes,
                peak_rss_bytes=max(int(active["peak_rss_bytes"]), final.rss_bytes),
                rss_growth_bytes=rss_growth,
                python_heap_growth_bytes=python_growth,
                growth_mb_per_hour=round(growth_mb_per_hour, 3),
                report_path=report_path,
            )
            report_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json(report_path, run.to_dict())
            runs = self.list_runs()
            runs.insert(0, run)
            self._write_json(self.runs_path, [item.to_dict() for item in runs[:100]])
            self._active_run = None
            if self._owns_tracemalloc and tracemalloc.is_tracing():
                tracemalloc.stop()
                self._owns_tracemalloc = False
            return run

    def run_soak(
        self,
        *,
        duration_seconds: float,
        sample_interval_seconds: float = 15.0,
        label: str = "soak",
        max_samples: int | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> PerformanceObservationRun:
        if self.active_run_id:
            raise RuntimeError("Finish the active performance observation before starting a soak run")
        duration_seconds = max(0.0, float(duration_seconds))
        interval = max(0.01, float(sample_interval_seconds))
        expected_minutes = max(1, int(round(duration_seconds / 60.0)))
        self.start_observation(label, expected_minutes=expected_minutes)
        start = self._monotonic()
        samples = 0
        status = "completed"
        try:
            while self._monotonic() - start < duration_seconds:
                if callable(cancel) and cancel():
                    status = "cancelled"
                    break
                # Small deterministic workload catches object/allocator growth without
                # touching projects, providers, queues or output files.
                digest = hashlib.sha256()
                for number in range(256):
                    digest.update(f"{number}:{app.__version__}".encode("utf-8"))
                digest.digest()
                self.collect_sample(label="soak-sample", persist=True)
                samples += 1
                if max_samples is not None and samples >= max(1, int(max_samples)):
                    break
                remaining = duration_seconds - (self._monotonic() - start)
                if remaining > 0:
                    self._sleep(min(interval, remaining))
        except BaseException:
            status = "failed"
            raise
        finally:
            run = self.finish_observation(status=status)
        if run is None:
            raise RuntimeError("Performance observation did not produce a run record")
        return run

    def snapshot(
        self,
        *,
        queue_total: int = 0,
        generation_active: bool = False,
    ) -> PerformanceStabilitySnapshot:
        policy = self.load_policy()
        current = self.collect_sample(
            label="snapshot",
            queue_total=queue_total,
            generation_active=generation_active,
            persist=False,
        )
        samples = self.list_samples(limit=min(policy.history_limit, 120))
        runs = self.list_runs()
        gates = tuple(self._evaluate(current, samples, runs, policy))
        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        status = "blocked" if blockers else "attention" if warnings else "healthy"
        summary = (
            f"{blockers} blocker(s) and {warnings} warning(s)"
            if blockers or warnings
            else "Performance budgets are within the configured limits"
        )
        snapshot = PerformanceStabilitySnapshot(
            captured_at=self._now(),
            status=status,
            summary=summary,
            policy=policy,
            current_sample=current,
            startup_ready=self.startup_ready,
            background_sampling_enabled=policy.background_sampling_enabled,
            active_run_id=self.active_run_id,
            active_run_label=str((self._active_run or {}).get("label") or ""),
            recent_samples=tuple(samples[-30:]),
            runs=tuple(runs[:20]),
            gates=gates,
        )
        self._write_json(self.latest_snapshot_path, snapshot.to_dict())
        return snapshot

    def export_snapshot(self) -> tuple[Path, Path]:
        snapshot = self.snapshot()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        json_path = self.exports_dir / f"performance-stability-{stamp}.json"
        csv_path = self.exports_dir / f"performance-samples-{stamp}.csv"
        self._write_json(json_path, snapshot.to_dict())
        fieldnames = list(PerformanceSample.__dataclass_fields__)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for sample in snapshot.recent_samples:
                writer.writerow(sample.to_dict())
        return json_path, csv_path

    def list_samples(self, *, limit: int | None = None) -> list[PerformanceSample]:
        if not self.samples_path.exists():
            return []
        result: list[PerformanceSample] = []
        for line in self.samples_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                payload = json.loads(line)
                result.append(PerformanceSample(**payload))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result[-limit:] if limit is not None else result

    def list_runs(self) -> list[PerformanceObservationRun]:
        try:
            payload = json.loads(self.runs_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return []
        result: list[PerformanceObservationRun] = []
        for item in payload if isinstance(payload, list) else []:
            try:
                normalized = dict(item)
                report_path = str(normalized.get("report_path") or "")
                normalized["report_path"] = (self.root / "runs" / Path(report_path).name) if report_path else None
                result.append(PerformanceObservationRun(**normalized))
            except (TypeError, ValueError):
                continue
        return result

    def _append_sample(self, sample: PerformanceSample) -> None:
        policy = self.load_policy()
        samples = self.list_samples()
        samples.append(sample)
        samples = samples[-policy.history_limit :]
        content = "".join(
            json.dumps(item.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            for item in samples
        )
        self._atomic_write_text(self.samples_path, content)

    def _evaluate(
        self,
        current: PerformanceSample,
        samples: list[PerformanceSample],
        runs: list[PerformanceObservationRun],
        policy: PerformanceStabilityPolicy,
    ) -> list[PerformanceGate]:
        gates: list[PerformanceGate] = []
        gates.append(
            self._threshold_gate(
                "startup",
                "Application startup",
                current.startup_elapsed_ms,
                policy.startup_warning_ms,
                policy.startup_blocker_ms,
                "ms",
                "Profile startup services and defer nonessential work until after the first window is visible.",
            )
        )
        gates.append(
            self._threshold_gate(
                "rss",
                "Process working set",
                self._mb(current.rss_bytes),
                policy.rss_warning_mb,
                policy.rss_blocker_mb,
                "MB",
                "Close stale dialogs, inspect retained Qt objects and review provider/media caches.",
            )
        )
        heap_value: float | None = self._mb(current.python_heap_bytes) if current.python_heap_bytes else None
        gates.append(
            self._threshold_gate(
                "python_heap",
                "Python traced heap",
                heap_value,
                policy.python_heap_warning_mb,
                policy.python_heap_blocker_mb,
                "MB",
                "Run an observation with tracemalloc enabled and inspect growing allocation groups.",
            )
        )
        gates.append(
            self._threshold_gate(
                "threads",
                "Process threads",
                current.process_thread_count,
                policy.process_thread_warning,
                policy.process_thread_blocker,
                "thread(s)",
                "Stop orphan workers and ensure completed generation tasks release their executors.",
            )
        )
        qt_value: int | None = current.qt_widget_count if current.qt_widget_count else None
        gates.append(
            self._threshold_gate(
                "qt_widgets",
                "Live Qt widgets",
                qt_value,
                policy.qt_widget_warning,
                policy.qt_widget_blocker,
                "widget(s)",
                "Flush deferred deletes and inspect report/dialog lifecycle registrations.",
            )
        )
        handle_value: int | None = current.process_handle_count if current.process_handle_count else None
        gates.append(
            self._threshold_gate(
                "handles",
                "Process handles",
                handle_value,
                policy.handle_warning,
                policy.handle_blocker,
                "handle(s)",
                "Release files, media sources, subprocess pipes and Windows handles after each operation.",
            )
        )
        growth = self._growth_mb_per_hour(samples, runs)
        gates.append(
            self._threshold_gate(
                "memory_growth",
                "Long-run RSS growth",
                growth,
                policy.growth_warning_mb_per_hour,
                policy.growth_blocker_mb_per_hour,
                "MB/hour",
                "Run the soak workflow, identify retained objects and compare the first and final samples.",
            )
        )
        return gates

    @staticmethod
    def _threshold_gate(
        gate_id: str,
        label: str,
        value: float | int | None,
        warning: float | int,
        blocker: float | int,
        unit: str,
        remediation: str,
    ) -> PerformanceGate:
        if value is None:
            return PerformanceGate(
                gate_id,
                label,
                "not_measured",
                "info",
                "Not measured in the current runtime.",
                remediation,
            )
        display = f"{value:.2f}" if isinstance(value, float) and not float(value).is_integer() else f"{value:g}"
        if value >= blocker:
            return PerformanceGate(
                gate_id,
                label,
                "block",
                "blocker",
                f"{display} {unit}; blocker budget is {blocker:g} {unit}.",
                remediation,
            )
        if value >= warning:
            return PerformanceGate(
                gate_id,
                label,
                "warn",
                "warning",
                f"{display} {unit}; warning budget is {warning:g} {unit}.",
                remediation,
            )
        return PerformanceGate(
            gate_id,
            label,
            "pass",
            "info",
            f"{display} {unit}; within the {warning:g} {unit} warning budget.",
            remediation,
        )

    @staticmethod
    def _growth_mb_per_hour(
        samples: list[PerformanceSample],
        runs: list[PerformanceObservationRun],
    ) -> float | None:
        completed = [run for run in runs if run.status == "completed" and run.duration_seconds >= 60]
        if completed:
            return max(0.0, completed[0].growth_mb_per_hour)
        if len(samples) < 2:
            return None
        first, last = samples[0], samples[-1]
        duration = last.monotonic_seconds - first.monotonic_seconds
        if duration < 60:
            return None
        growth = max(0, last.rss_bytes - first.rss_bytes) / 1024**2
        return round(growth * 3600.0 / duration, 3)

    def _sample_metrics(self, *, deep: bool) -> dict[str, int]:
        if self._metric_provider is not None:
            return self._metric_provider()
        return self._default_metrics(deep=deep)

    def _default_metrics(self, *, deep: bool = True) -> dict[str, int]:
        current_heap = peak_heap = 0
        if tracemalloc.is_tracing():
            current_heap, peak_heap = tracemalloc.get_traced_memory()
        metrics = {
            "rss_bytes": self._rss_bytes(),
            "python_heap_bytes": current_heap,
            "python_peak_bytes": peak_heap,
            "process_thread_count": threading.active_count(),
            "qt_active_thread_count": 0,
            "qt_widget_count": 0,
            "qt_top_level_count": 0,
            "gc_object_count": len(gc.get_objects()) if deep else 0,
            "open_file_count": 0,
            "process_handle_count": self._handle_count(),
        }
        try:
            from PySide6.QtCore import QCoreApplication, QThreadPool
            from PySide6.QtWidgets import QApplication

            if QCoreApplication.instance() is not None:
                metrics["qt_active_thread_count"] = QThreadPool.globalInstance().activeThreadCount()
                qt_app = QApplication.instance()
                if qt_app is not None and deep:
                    metrics["qt_widget_count"] = len(qt_app.allWidgets())
                    metrics["qt_top_level_count"] = len(qt_app.topLevelWidgets())
        except Exception:
            pass
        return metrics

    @staticmethod
    def _rss_bytes() -> int:
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]

                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                process = ctypes.windll.kernel32.GetCurrentProcess()
                if ctypes.windll.psapi.GetProcessMemoryInfo(
                    process,
                    ctypes.byref(counters),
                    counters.cb,
                ):
                    return int(counters.WorkingSetSize)
            except Exception:
                return 0
        proc_statm = Path("/proc/self/statm")
        try:
            resident_pages = int(proc_statm.read_text().split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError, AttributeError):
            return 0

    @staticmethod
    def _handle_count() -> int:
        if sys.platform != "win32":
            return 0
        try:
            import ctypes
            from ctypes import wintypes

            count = wintypes.DWORD()
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.kernel32.GetProcessHandleCount(process, ctypes.byref(count)):
                return int(count.value)
        except Exception:
            pass
        return 0

    @staticmethod
    def _mb(value: int) -> float:
        return round(max(0, int(value)) / 1024**2, 2)

    def _safe_label(self, value: object) -> str:
        text = str(value or "")
        text = self._LABEL_AUTH_RE.sub("Authorization=[REDACTED]", text)
        text = self._LABEL_SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        text = self._LABEL_BEARER_RE.sub("Bearer [REDACTED]", text)
        text = self._SAFE_LABEL_RE.sub("-", text).strip(" .-/")
        return (text[:80] or "performance")

    def _now(self) -> str:
        return self._now_provider().astimezone(timezone.utc).isoformat()

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    def _write_json(self, path: Path, payload: object) -> None:
        self._atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
