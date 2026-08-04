from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PerformanceStabilityPolicy:
    schema_version: int = 1
    background_sampling_enabled: bool = True
    sample_interval_seconds: int = 60
    history_limit: int = 720
    startup_warning_ms: int = 4_000
    startup_blocker_ms: int = 10_000
    rss_warning_mb: int = 900
    rss_blocker_mb: int = 1_500
    python_heap_warning_mb: int = 320
    python_heap_blocker_mb: int = 700
    process_thread_warning: int = 28
    process_thread_blocker: int = 56
    qt_widget_warning: int = 1_000
    qt_widget_blocker: int = 1_800
    handle_warning: int = 2_500
    handle_blocker: int = 6_000
    growth_warning_mb_per_hour: int = 96
    growth_blocker_mb_per_hour: int = 256
    default_soak_minutes: int = 30

    def normalized(self) -> "PerformanceStabilityPolicy":
        warning_startup = max(250, int(self.startup_warning_ms))
        blocker_startup = max(warning_startup + 250, int(self.startup_blocker_ms))
        warning_rss = max(64, int(self.rss_warning_mb))
        blocker_rss = max(warning_rss + 64, int(self.rss_blocker_mb))
        warning_heap = max(32, int(self.python_heap_warning_mb))
        blocker_heap = max(warning_heap + 32, int(self.python_heap_blocker_mb))
        warning_threads = max(4, int(self.process_thread_warning))
        blocker_threads = max(warning_threads + 2, int(self.process_thread_blocker))
        warning_widgets = max(50, int(self.qt_widget_warning))
        blocker_widgets = max(warning_widgets + 50, int(self.qt_widget_blocker))
        warning_handles = max(100, int(self.handle_warning))
        blocker_handles = max(warning_handles + 100, int(self.handle_blocker))
        warning_growth = max(1, int(self.growth_warning_mb_per_hour))
        blocker_growth = max(warning_growth + 1, int(self.growth_blocker_mb_per_hour))
        return PerformanceStabilityPolicy(
            schema_version=1,
            background_sampling_enabled=bool(self.background_sampling_enabled),
            sample_interval_seconds=min(3_600, max(15, int(self.sample_interval_seconds))),
            history_limit=min(10_000, max(20, int(self.history_limit))),
            startup_warning_ms=warning_startup,
            startup_blocker_ms=blocker_startup,
            rss_warning_mb=warning_rss,
            rss_blocker_mb=blocker_rss,
            python_heap_warning_mb=warning_heap,
            python_heap_blocker_mb=blocker_heap,
            process_thread_warning=warning_threads,
            process_thread_blocker=blocker_threads,
            qt_widget_warning=warning_widgets,
            qt_widget_blocker=blocker_widgets,
            handle_warning=warning_handles,
            handle_blocker=blocker_handles,
            growth_warning_mb_per_hour=warning_growth,
            growth_blocker_mb_per_hour=blocker_growth,
            default_soak_minutes=min(24 * 60, max(1, int(self.default_soak_minutes))),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PerformanceStabilityPolicy":
        if not isinstance(payload, dict):
            return cls()
        values = {field_name: payload[field_name] for field_name in cls.__dataclass_fields__ if field_name in payload}
        try:
            return cls(**values).normalized()
        except (TypeError, ValueError):
            return cls()


@dataclass(frozen=True)
class PerformanceSample:
    captured_at: str
    monotonic_seconds: float
    label: str
    startup_elapsed_ms: int | None
    rss_bytes: int
    python_heap_bytes: int
    python_peak_bytes: int
    process_thread_count: int
    qt_active_thread_count: int
    qt_widget_count: int
    qt_top_level_count: int
    gc_object_count: int
    open_file_count: int
    process_handle_count: int
    queue_total: int = 0
    generation_active: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceGate:
    gate_id: str
    label: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "not_measured"}

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class PerformanceObservationRun:
    run_id: str
    label: str
    started_at: str
    finished_at: str
    status: str
    expected_minutes: int
    duration_seconds: float
    sample_count: int
    start_rss_bytes: int
    end_rss_bytes: int
    peak_rss_bytes: int
    rss_growth_bytes: int
    python_heap_growth_bytes: int
    growth_mb_per_hour: float
    report_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["report_path"] = self.report_path.name if self.report_path else ""
        return payload


@dataclass(frozen=True)
class PerformanceStabilitySnapshot:
    captured_at: str
    status: str
    summary: str
    policy: PerformanceStabilityPolicy
    current_sample: PerformanceSample
    startup_ready: bool
    background_sampling_enabled: bool
    active_run_id: str = ""
    active_run_label: str = ""
    recent_samples: tuple[PerformanceSample, ...] = field(default_factory=tuple)
    runs: tuple[PerformanceObservationRun, ...] = field(default_factory=tuple)
    gates: tuple[PerformanceGate, ...] = field(default_factory=tuple)

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates)

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates)

    def to_dict(self) -> dict[str, object]:
        return {
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "policy": self.policy.to_dict(),
            "current_sample": self.current_sample.to_dict(),
            "startup_ready": self.startup_ready,
            "background_sampling_enabled": self.background_sampling_enabled,
            "active_run_id": self.active_run_id,
            "active_run_label": self.active_run_label,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "recent_samples": [sample.to_dict() for sample in self.recent_samples],
            "runs": [run.to_dict() for run in self.runs],
            "gates": [gate.to_dict() for gate in self.gates],
        }
