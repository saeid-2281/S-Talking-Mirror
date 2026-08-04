from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.performance_stability_dialog import PerformanceStabilityDialog
from app.gui.main import MainWindow
from app.models.performance_stability import PerformanceStabilityPolicy
from app.services.performance_stability_service import PerformanceStabilityService


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(0.0, float(seconds))

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


class _Metrics:
    def __init__(self, *, rss_mb: int = 128, heap_mb: int = 16) -> None:
        self.rss_mb = rss_mb
        self.heap_mb = heap_mb
        self.threads = 6
        self.widgets = 25
        self.handles = 120

    def __call__(self) -> dict[str, int]:
        return {
            "rss_bytes": self.rss_mb * 1024**2,
            "python_heap_bytes": self.heap_mb * 1024**2,
            "python_peak_bytes": (self.heap_mb + 2) * 1024**2,
            "process_thread_count": self.threads,
            "qt_active_thread_count": 1,
            "qt_widget_count": self.widgets,
            "qt_top_level_count": 2,
            "gc_object_count": 1000,
            "open_file_count": 4,
            "process_handle_count": self.handles,
        }


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _service(tmp_path: Path, clock: _Clock | None = None, metrics: _Metrics | None = None) -> PerformanceStabilityService:
    clock = clock or _Clock()
    return PerformanceStabilityService(
        _runtime(tmp_path),
        now=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
        monotonic=clock.monotonic,
        metric_provider=metrics or _Metrics(),
        sleeper=clock.sleep,
    )


def test_phase57_policy_round_trip_normalizes_budgets(tmp_path: Path) -> None:
    service = _service(tmp_path)
    policy = service.save_policy(
        PerformanceStabilityPolicy(
            sample_interval_seconds=2,
            history_limit=3,
            startup_warning_ms=5000,
            startup_blocker_ms=1000,
            rss_warning_mb=256,
            rss_blocker_mb=128,
        )
    )
    assert policy.sample_interval_seconds == 15
    assert policy.history_limit == 20
    assert policy.startup_blocker_ms > policy.startup_warning_ms
    assert policy.rss_blocker_mb > policy.rss_warning_mb
    assert service.load_policy() == policy
    serialized = service.policy_path.read_text(encoding="utf-8")
    assert "credential" not in serialized.casefold()
    assert "api_key" not in serialized.casefold()


def test_phase57_samples_are_bounded_and_labels_are_redacted(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save_policy(replace(service.load_policy(), history_limit=20))
    for index in range(27):
        service.collect_sample(label=f"sample {index} token=secret-{index}")
    samples = service.list_samples()
    assert len(samples) == 20
    assert samples[0].label.startswith("sample 7")
    serialized = service.samples_path.read_text(encoding="utf-8")
    assert "secret-" not in serialized
    assert "REDACTED" in serialized


def test_phase57_startup_and_resource_budgets_are_deterministic(tmp_path: Path) -> None:
    clock = _Clock()
    metrics = _Metrics(rss_mb=1600, heap_mb=800)
    metrics.threads = 60
    metrics.widgets = 1900
    metrics.handles = 6500
    service = _service(tmp_path, clock, metrics)
    clock.advance(11.0)
    service.mark_startup_ready()
    snapshot = service.snapshot()
    assert snapshot.status == "blocked"
    statuses = {gate.gate_id: gate.status for gate in snapshot.gates}
    assert statuses["startup"] == "block"
    assert statuses["rss"] == "block"
    assert statuses["python_heap"] == "block"
    assert statuses["threads"] == "block"
    assert statuses["qt_widgets"] == "block"
    assert statuses["handles"] == "block"


def test_phase57_observation_records_growth_and_report(tmp_path: Path) -> None:
    clock = _Clock()
    metrics = _Metrics(rss_mb=200, heap_mb=20)
    service = _service(tmp_path, clock, metrics)
    run_id = service.start_observation("provider soak", expected_minutes=60)
    metrics.rss_mb = 350
    metrics.heap_mb = 45
    clock.advance(3600)
    run = service.finish_observation()
    assert run is not None
    assert run.run_id == run_id
    assert run.sample_count == 2
    assert run.rss_growth_bytes == 150 * 1024**2
    assert run.python_heap_growth_bytes == 25 * 1024**2
    assert run.growth_mb_per_hour == 150.0
    assert run.report_path is not None and run.report_path.exists()
    snapshot = service.snapshot()
    growth_gate = next(gate for gate in snapshot.gates if gate.gate_id == "memory_growth")
    assert growth_gate.status == "warn"


def test_phase57_quick_soak_is_bounded_and_does_not_touch_private_files(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.settings_path.write_text('{"api_key":"sk-private"}', encoding="utf-8")
    (runtime.default_output_dir / "private.mp3").write_bytes(b"audio")
    clock = _Clock()
    service = PerformanceStabilityService(
        runtime,
        now=lambda: datetime(2026, 8, 4, tzinfo=timezone.utc),
        monotonic=clock.monotonic,
        metric_provider=_Metrics(),
        sleeper=clock.sleep,
    )
    run = service.run_soak(
        duration_seconds=3,
        sample_interval_seconds=0.5,
        max_samples=4,
        label="quick soak password=private-value",
    )
    assert run.status == "completed"
    assert 2 <= run.sample_count <= 6
    assert runtime.settings_path.read_text(encoding="utf-8") == '{"api_key":"sk-private"}'
    assert (runtime.default_output_dir / "private.mp3").read_bytes() == b"audio"
    evidence = "\n".join(path.read_text(encoding="utf-8") for path in service.root.rglob("*.json"))
    assert "private-value" not in evidence
    assert "sk-private" not in evidence


def test_phase57_export_is_structured_and_secret_free(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.mark_startup_ready()
    service.collect_sample(label="Authorization: Bearer private-token")
    json_path, csv_path = service.export_snapshot()
    assert json_path.exists() and csv_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["status"] in {"healthy", "attention", "blocked"}
    assert payload["gates"]
    content = json_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8")
    assert "private-token" not in content
    assert "Authorization" in content
    assert "REDACTED" in content


def test_phase57_frozen_cli_script_and_privacy_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    service = (root / "app" / "services" / "performance_stability_service.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "performance-soak.ps1").read_text(encoding="utf-8")
    assert "--performance-snapshot" in frozen
    assert "--performance-soak-minutes" in frozen
    assert "--performance-export" in frozen
    assert "project text, filenames, API profiles" in service
    assert "--performance-max-samples" in script
    assert "app.frozen_main" in script
    assert "Invoke-Expression" not in script


def test_phase57_dialog_mainwindow_and_background_timer_contracts(qt_app, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    container = create_service_container(runtime)
    service = container.performance_stability_service
    dialog = PerformanceStabilityDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "performanceStabilityDialog"
    assert dialog.gate_table.rowCount() == 7
    assert dialog.metrics_table.rowCount() >= 8
    assert dialog.capture_sample().label == "manual-ui"
    run_id = dialog.start_observation()
    assert run_id
    assert dialog.finish_observation() is not None
    dialog.close()

    window = MainWindow(create_application_context(container))
    window.show()
    qt_app.processEvents()
    assert "Performance & Stability" in window.actions_by_name
    assert window.performance_sample_timer.interval() >= 15_000
    assert any(
        command.name == "Reports: Performance & Stability"
        for command in window.command_palette_commands()
    )
    opened = window.open_performance_stability()
    assert opened.objectName() == "performanceStabilityDialog"
    window.close()
