from __future__ import annotations

import inspect
from pathlib import Path

from app.gui.main import MainWindow
from app.models.domain import AppSettings, TTSJob
from app.services.generation_execution_session_service import GenerationExecutionSessionService
from app.services.generation_monitor_service import GenerationMonitorService


def test_h45_pause_resume_use_lightweight_dashboard_and_lifecycle_persistence() -> None:
    source = inspect.getsource(MainWindow.pause)

    assert "dashboard(runtime_lightweight=True)" in source
    assert "sync_execution_lifecycle_status('paused')" in source
    assert "sync_execution_lifecycle_status('running')" in source
    assert "sync_execution_session(" not in source


def test_h45_stop_uses_lightweight_lifecycle_persistence() -> None:
    source = inspect.getsource(MainWindow.stop)

    assert "dashboard(runtime_lightweight=True)" in source
    assert "sync_execution_lifecycle_status('stopping')" in source
    assert "sync_execution_session(" not in source


def test_h45_monitor_lifecycle_actions_do_not_rescan_queue() -> None:
    for method in (
        GenerationMonitorService.pause,
        GenerationMonitorService.resume,
        GenerationMonitorService.stop_requested,
    ):
        source = inspect.getsource(method)
        assert "_rebuild(" not in source
        assert "_publish_lifecycle_state" in source


def test_h45_running_transition_after_start_does_not_rewrite_full_execution_session() -> None:
    source = inspect.getsource(MainWindow.start)
    assert "sync_execution_lifecycle_status('running')" in source
    assert "self.sync_execution_session('running')" not in source


def test_h45_lifecycle_helper_avoids_full_job_manifest_sync() -> None:
    source = inspect.getsource(MainWindow.sync_execution_lifecycle_status)

    assert "record_lifecycle_status(" in source
    assert "sync_intelligent_tts_run_ledger(status,metrics)" in source
    assert "generation_execution_session_service.sync_session" not in source
    assert "generation_controller.generation_jobs()" not in source


def test_h45_execution_lifecycle_sidecar_overlays_status_without_rewriting_jobs(tmp_path: Path) -> None:
    service = GenerationExecutionSessionService(tmp_path / "reports")
    settings = AppSettings(provider="mock", model_id="model", voice_id="voice")
    job = TTSJob(row_number=1, text="Hej", filename="001.wav")
    session = service.start_session(
        run_id="run-h45",
        project_name="Project",
        project_id=1,
        project_key="project-key",
        launch_receipt_path=None,
        launch_receipt_id="",
        launch_fingerprint="fingerprint",
        decision_trace_id="",
        guard_approval_id="",
        settings=settings,
        jobs=[job],
        output_directory=tmp_path / "out",
        initial_status="starting",
    )
    original_bytes = session.path.read_bytes()

    sidecar = service.record_lifecycle_status(
        "run-h45",
        project_name="Project",
        status="paused",
        elapsed_seconds=12.5,
        retry_events=2,
    )

    assert sidecar.exists()
    assert session.path.read_bytes() == original_bytes
    loaded = service.load(session.path)
    assert loaded.status == "paused"
    assert loaded.elapsed_seconds == 12.5
    assert loaded.retry_events == 2
    assert len(loaded.jobs) == 1


def test_h45_terminal_session_clears_transient_lifecycle_overlay(tmp_path: Path) -> None:
    service = GenerationExecutionSessionService(tmp_path / "reports")
    settings = AppSettings(provider="mock", model_id="model", voice_id="voice")
    job = TTSJob(row_number=1, text="Hej", filename="001.wav")
    service.start_session(
        run_id="run-h45-final",
        project_name="Project",
        project_id=1,
        project_key="project-key",
        launch_receipt_path=None,
        launch_receipt_id="",
        launch_fingerprint="fingerprint",
        decision_trace_id="",
        guard_approval_id="",
        settings=settings,
        jobs=[job],
        output_directory=tmp_path / "out",
        initial_status="starting",
    )
    sidecar = service.record_lifecycle_status(
        "run-h45-final",
        project_name="Project",
        status="stopping",
    )
    assert sidecar.exists()

    finished = service.finish_session(
        "run-h45-final",
        [job],
        project_name="Project",
        settings=settings,
        output_directory=tmp_path / "out",
        result="cancelled",
    )

    assert not sidecar.exists()
    assert finished.status == "cancelled"
