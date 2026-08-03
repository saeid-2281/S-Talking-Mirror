from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent

from app.gui.dialogs.generation_execution_session_dialog import (
    GenerationExecutionSessionDialog,
)
from app.models import AppSettings, JobStatus, TTSJob
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import (
    GenerationConfirmation,
    GenerationConfirmationCoordinator,
)
from app.services.generation_execution_session_service import (
    GenerationExecutionSessionService,
)
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


def _settings() -> AppSettings:
    return AppSettings(
        provider="mock",
        api_key="sk_phase43_must_not_leak",
        model_id="model-a",
        voice_id="voice-a",
        language_code="da",
        file_extension=".mp3",
        generation_scope="row_range",
        execution_order="csv",
        skip_existing=True,
        overwrite_existing=False,
    )


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(
            row_number=1,
            text="Første tekst",
            filename="first.mp3",
            source_id="csv-1",
            source_display_name="input.csv",
            source_row=2,
        ),
        TTSJob(
            row_number=2,
            text="Anden tekst",
            filename="second.mp3",
            source_id="csv-1",
            source_display_name="input.csv",
            source_row=3,
        ),
    ]


def _start(tmp_path: Path):
    service = GenerationExecutionSessionService(tmp_path / "reports")
    settings = _settings()
    jobs = _jobs()
    run_id = service.new_run_id("a" * 64)
    receipt = tmp_path / "reports" / "Demo" / "launches" / "launch" / "generation-launch.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("{}", encoding="utf-8")
    session = service.start_session(
        run_id=run_id,
        project_name="Demo",
        project_id=7,
        project_key="demo-key",
        launch_receipt_path=receipt,
        launch_receipt_id="launch-1",
        launch_fingerprint="a" * 64,
        decision_trace_id="decision-1",
        guard_approval_id="approval-1",
        settings=settings,
        jobs=jobs,
        output_directory=tmp_path / "output",
    )
    return service, settings, jobs, session


def test_phase43_run_id_is_unique_and_traceable() -> None:
    first = GenerationExecutionSessionService.new_run_id("abc123")
    second = GenerationExecutionSessionService.new_run_id("abc123")

    assert first.startswith("run-")
    assert "-abc123-" in first
    assert first != second


def test_phase43_start_session_links_launch_queue_and_output_without_text_or_secret(
    tmp_path: Path,
) -> None:
    service, _settings_value, _jobs_value, session = _start(tmp_path)
    raw = session.path.read_text(encoding="utf-8")

    assert session.status == "running"
    assert session.project_id == 7
    assert session.launch_receipt_id == "launch-1"
    assert session.decision_trace_id == "decision-1"
    assert session.guard_approval_id == "approval-1"
    assert session.total_jobs == 2
    assert session.integrity_status == "verified"
    assert "Første tekst" not in raw
    assert "sk_phase43_must_not_leak" not in raw
    assert service.path_for("Demo", session.run_id) == session.path


def test_phase43_sync_updates_job_outcomes_retries_and_output_manifest(tmp_path: Path) -> None:
    service, settings, jobs, session = _start(tmp_path)
    output = tmp_path / "output"
    jobs[0].status = JobStatus.COMPLETED
    jobs[0].retry_count = 1
    jobs[0].duration_seconds = 2.5
    jobs[0].generated_output_path = str(output / "first.mp3")
    jobs[1].status = JobStatus.FAILED
    jobs[1].retry_count = 2
    jobs[1].error = "api_key=sk_should_be_redacted"
    jobs[1].error_code = "provider_error"
    jobs[1].error_fingerprint = "error-fp"

    updated = service.sync_session(
        session.run_id,
        jobs,
        project_name="Demo",
        settings=settings,
        output_directory=output,
        status="running",
        elapsed_seconds=8.0,
        retry_events=3,
    )
    raw = updated.path.read_text(encoding="utf-8")

    assert updated.completed_jobs == 1
    assert updated.failed_jobs == 1
    assert updated.retry_events == 3
    assert updated.processed_characters == sum(job.character_count for job in jobs)
    assert updated.jobs[0].output_path.endswith("first.mp3")
    assert updated.jobs[1].error_fingerprint == "error-fp"
    assert "sk_should_be_redacted" not in raw
    assert "[REDACTED]" in raw


def test_phase43_finish_session_records_partial_result_and_final_report(tmp_path: Path) -> None:
    service, settings, jobs, session = _start(tmp_path)
    jobs[0].status = JobStatus.COMPLETED
    jobs[1].status = JobStatus.FAILED
    report = tmp_path / "reports" / "Demo" / "report.html"
    report.write_text("report", encoding="utf-8")

    finished = service.finish_session(
        session.run_id,
        jobs,
        project_name="Demo",
        settings=settings,
        output_directory=tmp_path / "output",
        result="partial",
        report_path=report,
        monitor_metrics={"elapsed_seconds": 12.5, "retry_events": 2},
    )

    assert finished.status == "partial"
    assert finished.finished_at
    assert finished.report_path == str(report)
    assert finished.elapsed_seconds == 12.5
    assert finished.retry_events == 2
    assert finished.requires_attention is True


def test_phase43_integrity_detects_execution_session_tampering(tmp_path: Path) -> None:
    service, _settings_value, _jobs_value, session = _start(tmp_path)
    payload = json.loads(session.path.read_text(encoding="utf-8"))
    payload["status"] = "completed"
    session.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    changed = service.load(session.path)

    assert changed.integrity_status == "mismatch"
    assert changed.requires_attention is True


def test_phase43_filter_summary_and_export_are_secret_free(tmp_path: Path) -> None:
    service, settings, jobs, session = _start(tmp_path)
    jobs[0].status = JobStatus.COMPLETED
    completed = service.finish_session(
        session.run_id,
        jobs,
        project_name="Demo",
        settings=settings,
        output_directory=tmp_path / "output",
        result="completed",
    )

    listed = service.list_sessions(project_name="Demo", status="completed", search=completed.run_id)
    summary = service.summary(listed)
    json_path, csv_path = service.export(listed, tmp_path / "export", project_name="Demo")
    exported = json_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8-sig")

    assert listed == [completed]
    assert summary.completed_count == 1
    assert summary.total_jobs == 2
    assert completed.run_id in exported
    assert "sk_phase43_must_not_leak" not in exported
    assert "Første tekst" not in exported


def test_phase43_launch_receipt_persists_run_identity_and_session_link(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    receipt_service = GenerationLaunchReceiptService(reports)
    coordinator = GenerationConfirmationCoordinator()
    run_service = GenerationExecutionSessionService(reports)
    run_id = run_service.new_run_id("b" * 64)
    session_path = run_service.path_for("Demo", run_id)
    confirmation = GenerationConfirmation(
        allowed=True,
        title="Ready",
        status="ready",
        fingerprint="b" * 64,
    )
    state = PreflightState(
        total_jobs=2,
        valid_jobs=2,
        estimated_files=2,
        estimated_characters=24,
        estimated_provider_requests=2,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="phase43",
        settings_revision="phase43-settings",
    )

    path = coordinator.write_receipt(
        confirmation,
        state,
        _settings(),
        reports_dir=reports,
        project_name="Demo",
        output_dir=tmp_path / "output",
        receipt_service=receipt_service,
        run_id=run_id,
        execution_session_path=session_path,
    )
    receipt = receipt_service.load(path)

    assert receipt.run_id == run_id
    assert receipt.execution_session_path == str(session_path)
    assert receipt.integrity_status == "verified"
    assert run_id in path.read_text(encoding="utf-8")


def test_phase43_execution_session_dialog_lists_runs_and_releases_cleanly(
    qt_app,
    tmp_path: Path,
) -> None:
    service, _settings_value, _jobs_value, session = _start(tmp_path)
    dialog = GenerationExecutionSessionDialog(
        service,
        project_name="Demo",
        export_dir=tmp_path / "export",
    )
    try:
        assert dialog.table.rowCount() == 1
        assert dialog.filtered_sessions[0].run_id == session.run_id
        assert "Run ID" in dialog.details.toPlainText()
        assert dialog.copy_run_id_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qt_app.processEvents()
