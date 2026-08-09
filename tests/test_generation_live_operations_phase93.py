from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.generation_live_operations import GenerationLiveOperationsWidget
from app.models.domain import JobStatus, TTSJob
from app.services.generation_live_operations_service import GenerationLiveOperationsService

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/gui/main.py"
DOC = ROOT / "docs/GENERATION_LIVE_OPERATIONS_PHASE93.md"


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, text="a" * 100, filename="one.wav", status=JobStatus.COMPLETED),
        TTSJob(row_number=2, text="b" * 200, filename="two.wav", status=JobStatus.COMPLETED),
        TTSJob(row_number=3, text="c" * 300, filename="three.wav", status=JobStatus.FAILED),
        TTSJob(row_number=4, text="d" * 400, filename="four.wav", status=JobStatus.PENDING),
    ]


def _monitor(**overrides):
    values = dict(
        total=4,
        processed=3,
        retries=2,
        remaining_eta_seconds=90.0,
        average_seconds_per_completed_job=12.5,
        current_filename="four.wav",
        current_status="Running",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_phase93_snapshot_derives_counts_without_mutating_jobs() -> None:
    jobs = _jobs()
    before = [(job.row_number, job.status) for job in jobs]
    snapshot = GenerationLiveOperationsService().snapshot(
        jobs,
        monitor_state=_monitor(),
        active=True,
        paused=False,
        run_id="run-93",
        failure_summary={"retryable": 1},
    )
    assert snapshot.total == 4
    assert snapshot.processed == 3
    assert snapshot.completed == 2
    assert snapshot.failed == 1
    assert snapshot.pending == 1
    assert snapshot.state == "Running"
    assert [(job.row_number, job.status) for job in jobs] == before


def test_phase93_snapshot_pause_and_stop_state_are_read_only() -> None:
    service = GenerationLiveOperationsService()
    paused = service.snapshot(_jobs(), monitor_state=_monitor(), active=True, paused=True)
    stopping = service.snapshot(
        _jobs(), monitor_state=_monitor(current_status="Stopping"), active=True, paused=False
    )
    assert paused.state == "Paused"
    assert paused.can_pause and paused.can_stop
    assert stopping.state == "Stopping"


def test_phase93_snapshot_completion_handoff_and_failure_attention(tmp_path: Path) -> None:
    output = tmp_path / "latest.wav"
    output.write_bytes(b"RIFF")
    service = GenerationLiveOperationsService()
    jobs = [
        TTSJob(row_number=1, text="a", filename="one.wav", status=JobStatus.COMPLETED),
        TTSJob(row_number=2, text="b", filename="two.wav", status=JobStatus.COMPLETED),
        TTSJob(row_number=3, text="c", filename="three.wav", status=JobStatus.FAILED),
        TTSJob(row_number=4, text="d", filename="four.wav", status=JobStatus.COMPLETED),
    ]
    snapshot = service.snapshot(
        jobs,
        monitor_state=_monitor(processed=4, remaining_eta_seconds=0),
        active=False,
        paused=False,
        latest_output=output,
        failure_summary={"retryable": 1},
    )
    assert snapshot.state == "Needs attention"
    assert snapshot.can_open_output
    assert snapshot.can_retry
    assert snapshot.can_review_failures


def test_phase93_eta_confidence_is_sample_based_only() -> None:
    service = GenerationLiveOperationsService()
    jobs = _jobs()
    low = service.snapshot(jobs, monitor_state=_monitor(), active=True, paused=False)
    assert low.eta_confidence == "low"
    for index in range(3, 11):
        jobs.append(
            TTSJob(
                row_number=index + 2,
                text="x",
                filename=f"done-{index}.wav",
                status=JobStatus.COMPLETED,
            )
        )
    high = service.snapshot(jobs, monitor_state=_monitor(total=len(jobs)), active=True, paused=False)
    assert high.eta_confidence == "high"


def test_phase93_retry_is_disabled_during_active_run() -> None:
    service = GenerationLiveOperationsService()
    active = service.snapshot(
        _jobs(), monitor_state=_monitor(), active=True, paused=False, failure_summary={"retryable": 1}
    )
    inactive = service.snapshot(
        _jobs(), monitor_state=_monitor(), active=False, paused=False, failure_summary={"retryable": 1}
    )
    assert not active.can_retry
    assert inactive.can_retry


def test_phase93_widget_routes_only_existing_operator_actions(qt_app, tmp_path: Path) -> None:
    widget = GenerationLiveOperationsWidget()
    output = tmp_path / "latest.wav"
    output.write_bytes(b"RIFF")
    snapshot = GenerationLiveOperationsService().snapshot(
        _jobs(),
        monitor_state=_monitor(),
        active=False,
        paused=False,
        run_id="run-93",
        latest_output=output,
        failure_summary={"retryable": 1},
    )
    events: list[str] = []
    widget.retryRequested.connect(lambda: events.append("retry"))
    widget.outputRequested.connect(lambda: events.append("output"))
    widget.failureReviewRequested.connect(lambda: events.append("failures"))
    widget.update_snapshot(snapshot)
    widget.retry_button.click()
    widget.output_button.click()
    widget.failures_button.click()
    assert events == ["retry", "output", "failures"]
    assert "run-93" in widget.run_label.text()
    widget.close()


def test_phase93_widget_pause_button_becomes_resume(qt_app) -> None:
    widget = GenerationLiveOperationsWidget()
    snapshot = GenerationLiveOperationsService().snapshot(
        _jobs(), monitor_state=_monitor(), active=True, paused=True
    )
    widget.update_snapshot(snapshot)
    assert widget.pause_button.text() == "Resume"
    assert widget.pause_button.isEnabled()
    assert not widget.retry_button.isEnabled()
    widget.close()


def test_phase93_main_integrates_live_operations_into_existing_monitor() -> None:
    source = MAIN.read_text(encoding="utf-8")
    ast.parse(source)
    assert "GenerationLiveOperationsWidget" in source
    assert "GenerationLiveOperationsService" in source
    assert "root.addWidget(self.live_operations)" in source
    assert "def refresh_generation_live_operations(self):" in source
    assert "self.live_operations.pauseRequested.connect(self.pause)" in source
    assert "self.live_operations.stopRequested.connect(self.stop)" in source
    assert "self.live_operations.retryRequested.connect(self.retry_transient)" in source
    assert "self.live_operations.outputRequested.connect(self.play_latest_completed_output)" in source


def test_phase93_main_exposes_shortcut_palette_and_no_new_start_path() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert "Ctrl+Alt+R" in source
    assert "Generation: Live Operations" in source
    assert "Generation Live Operations" in source
    block = source[source.index("def refresh_generation_live_operations"):source.index("def render_failure_summary")]
    assert "self.start(" not in block
    assert "generation_controller.start" not in block


def test_phase93_mainwindow_hosts_live_run_focus(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    assert window.live_operations is not None
    assert window.actions_by_name["Generation Live Operations"].shortcut().toString() == "Ctrl+Alt+R"
    assert window.monitor_scroll.widget().layout().indexOf(window.live_operations) >= 0
    window.close()


def test_phase93_compact_workspace_does_not_consume_queue_height(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    window.show()
    window.setGeometry(0, 0, 1366, 768)
    window.apply_workspace_preset("Compact")
    qt_app.processEvents()
    assert window.queue_batch_operations.isHidden()
    assert window.generation_journey.isHidden()
    assert window.live_operations.parent() is window.monitor_scroll.widget()
    window.close()



def test_phase93_provider_status_does_not_change_workspace_dock_size_hint(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    before = window.left_dock.sizeHint().width()
    window.set_provider_status(
        "Connected · A very long account status with quota and catalog details"
    )
    qt_app.processEvents()
    assert window.left_dock.sizeHint().width() == before
    window.close()

def test_phase93_documentation_preserves_live_run_safety_contracts() -> None:
    text = DOC.read_text(encoding="utf-8")
    for phrase in (
        "no new generation launch path",
        "no automatic retry",
        "no change to billing",
        "Ctrl+Alt+R",
        "read-only",
    ):
        assert phrase in text
