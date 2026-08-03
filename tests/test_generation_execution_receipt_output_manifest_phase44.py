from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent

from app.gui.dialogs.generation_execution_receipt_dialog import (
    GenerationExecutionReceiptDialog,
)
from app.models import AppSettings, JobStatus, TTSJob
from app.services.generation_execution_receipt_service import (
    GenerationExecutionReceiptService,
)
from app.services.generation_execution_session_service import (
    GenerationExecutionSessionService,
)


def _settings(*, overwrite: bool = False, skip: bool = False) -> AppSettings:
    return AppSettings(
        provider="mock",
        api_key="sk_phase44_must_not_leak",
        model_id="model-a",
        voice_id="voice-a",
        language_code="da",
        file_extension=".mp3",
        generation_scope="entire_queue",
        execution_order="csv",
        skip_existing=skip,
        overwrite_existing=overwrite,
    )


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, text="Created text", filename="created.mp3"),
        TTSJob(row_number=2, text="Overwritten text", filename="overwritten.mp3"),
        TTSJob(row_number=3, text="Skipped text", filename="skipped.mp3"),
        TTSJob(row_number=4, text="Missing text", filename="missing.mp3"),
        TTSJob(row_number=5, text="Failed text", filename="failed.mp3"),
    ]


def _final_session(tmp_path: Path):
    reports = tmp_path / "reports"
    output = tmp_path / "output"
    output.mkdir()
    settings = _settings(overwrite=True)
    jobs = _jobs()
    overwritten = output / "overwritten.mp3"
    skipped = output / "skipped.mp3"
    overwritten.write_bytes(b"old")
    skipped.write_bytes(b"existing")
    launch = reports / "Demo" / "launches" / "launch" / "generation-launch.json"
    launch.parent.mkdir(parents=True, exist_ok=True)
    launch.write_text(
        json.dumps(
            {
                "scope": {
                    "files": 5,
                    "characters": sum(job.character_count for job in jobs),
                    "provider_requests": 4,
                    "existing_outputs": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    session_service = GenerationExecutionSessionService(reports)
    run_id = session_service.new_run_id("a" * 64)
    session_service.start_session(
        run_id=run_id,
        project_name="Demo",
        project_id=7,
        project_key="demo-key",
        launch_receipt_path=launch,
        launch_receipt_id="launch-1",
        launch_fingerprint="a" * 64,
        decision_trace_id="decision-1",
        guard_approval_id="approval-1",
        settings=settings,
        jobs=jobs,
        output_directory=output,
        planned_existing_outputs=(str(overwritten), str(skipped)),
    )
    (output / "created.mp3").write_bytes(b"created-output")
    overwritten.write_bytes(b"replacement-output")
    jobs[0].status = JobStatus.COMPLETED
    jobs[0].generated_output_path = str(output / "created.mp3")
    jobs[1].status = JobStatus.COMPLETED
    jobs[1].generated_output_path = str(overwritten)
    jobs[2].status = JobStatus.SKIPPED
    jobs[3].status = JobStatus.COMPLETED
    jobs[4].status = JobStatus.FAILED
    jobs[4].error = "api_key=sk_never_export"
    jobs[4].error_code = "provider_error"
    jobs[4].error_fingerprint = "failure-fp"
    report = reports / "Demo" / "report.html"
    report.write_text("report", encoding="utf-8")
    session = session_service.finish_session(
        run_id,
        jobs,
        project_name="Demo",
        settings=settings,
        output_directory=output,
        result="partial",
        report_path=report,
        monitor_metrics={"elapsed_seconds": 12.5, "retry_events": 1},
    )
    return session_service, session, settings, jobs, output, report


def test_phase44_receipt_classifies_created_overwritten_skipped_failed_and_missing(
    tmp_path: Path,
) -> None:
    _session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    service = GenerationExecutionReceiptService(tmp_path / "reports")

    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
        discover_unexpected=False,
    )
    dispositions = {item.filename: item.disposition for item in receipt.entries}

    assert receipt.status == "partial"
    assert dispositions["created.mp3"] == "created"
    assert dispositions["overwritten.mp3"] == "overwritten"
    assert dispositions["skipped.mp3"] == "skipped_existing"
    assert dispositions["missing.mp3"] == "missing"
    assert dispositions["failed.mp3"] == "failed"
    assert receipt.created_outputs == 1
    assert receipt.overwritten_outputs == 1
    assert receipt.skipped_outputs == 1
    assert receipt.missing_outputs == 1
    assert receipt.failed_outputs == 1


def test_phase44_manifest_hashes_existing_outputs_and_preserves_plan_metrics(tmp_path: Path) -> None:
    _session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    service = GenerationExecutionReceiptService(tmp_path / "reports")

    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
        discover_unexpected=False,
    )
    created = next(item for item in receipt.entries if item.filename == "created.mp3")

    assert receipt.planned_files == 5
    assert receipt.planned_requests == 4
    assert receipt.planned_existing_outputs == 2
    assert created.size_bytes == len(b"created-output")
    assert len(created.sha256) == 64
    assert receipt.manifest_csv_path.exists()
    assert "created.mp3" in receipt.manifest_csv_path.read_text(encoding="utf-8-sig")


def test_phase44_detects_unexpected_output_created_during_run(tmp_path: Path) -> None:
    _session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    unexpected = output / "unexpected.mp3"
    unexpected.write_bytes(b"unexpected")
    service = GenerationExecutionReceiptService(tmp_path / "reports")

    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
    )

    assert receipt.unexpected_outputs == 1
    assert any(item.filename == "unexpected.mp3" and item.disposition == "unexpected" for item in receipt.entries)


def test_phase44_integrity_detects_receipt_tampering(tmp_path: Path) -> None:
    _session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    service = GenerationExecutionReceiptService(tmp_path / "reports")
    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
        discover_unexpected=False,
    )
    payload = json.loads(receipt.path.read_text(encoding="utf-8"))
    payload["actual"]["created_outputs"] = 99
    receipt.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    changed = service.load(receipt.path)

    assert changed.integrity_status == "mismatch"
    assert changed.requires_attention is True


def test_phase44_session_links_execution_receipt_and_manifest(tmp_path: Path) -> None:
    session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    receipt_service = GenerationExecutionReceiptService(tmp_path / "reports")
    receipt = receipt_service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
        discover_unexpected=False,
    )

    linked = session_service.link_execution_receipt(
        session.run_id,
        project_name="Demo",
        receipt_id=receipt.receipt_id,
        receipt_path=receipt.path,
        manifest_path=receipt.manifest_csv_path,
    )

    assert linked.execution_receipt_id == receipt.receipt_id
    assert linked.execution_receipt_path == str(receipt.path)
    assert linked.output_manifest_path == str(receipt.manifest_csv_path)
    assert linked.integrity_status == "verified"


def test_phase44_filter_summary_and_export_are_secret_free(tmp_path: Path) -> None:
    _session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    service = GenerationExecutionReceiptService(tmp_path / "reports")
    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
        discover_unexpected=False,
    )

    listed = service.list_receipts(project_name="Demo", status="partial", search=receipt.run_id)
    summary = service.summary(listed)
    json_path, csv_path = service.export(listed, tmp_path / "export", project_name="Demo")
    exported = json_path.read_text(encoding="utf-8") + csv_path.read_text(encoding="utf-8-sig")

    assert listed == [receipt]
    assert summary.total_count == 1
    assert summary.missing_outputs == 1
    assert receipt.run_id in exported
    assert "sk_phase44_must_not_leak" not in exported
    assert "sk_never_export" not in exported
    assert "Created text" not in exported


def test_phase44_completed_receipt_has_zero_variance_and_no_attention(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    output = tmp_path / "output"
    output.mkdir()
    settings = _settings()
    jobs = [TTSJob(row_number=1, text="Text", filename="done.mp3", status=JobStatus.COMPLETED)]
    (output / "done.mp3").write_bytes(b"done")
    session_service = GenerationExecutionSessionService(reports)
    run_id = session_service.new_run_id("b" * 64)
    session_service.start_session(
        run_id=run_id,
        project_name="Demo",
        project_id=1,
        project_key="demo",
        launch_receipt_path=None,
        launch_receipt_id="",
        launch_fingerprint="b" * 64,
        decision_trace_id="trace",
        guard_approval_id="",
        settings=settings,
        jobs=jobs,
        output_directory=output,
    )
    session = session_service.finish_session(
        run_id,
        jobs,
        project_name="Demo",
        settings=settings,
        output_directory=output,
        result="completed",
    )
    service = GenerationExecutionReceiptService(reports)

    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        discover_unexpected=False,
    )

    assert receipt.status == "completed"
    assert receipt.planned_files == 1
    assert receipt.actual_outputs == 1
    assert receipt.variance_files == 0
    assert receipt.requires_attention is False


def test_phase44_execution_receipt_dialog_lists_manifest_and_releases_cleanly(
    qt_app,
    tmp_path: Path,
) -> None:
    _session_service, session, settings, jobs, output, report = _final_session(tmp_path)
    service = GenerationExecutionReceiptService(tmp_path / "reports")
    receipt = service.create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        report_path=report,
        discover_unexpected=False,
    )
    dialog = GenerationExecutionReceiptDialog(
        service,
        project_name="Demo",
        export_dir=tmp_path / "export",
    )
    try:
        assert dialog.table.rowCount() == 1
        assert dialog.filtered_receipts[0].receipt_id == receipt.receipt_id
        assert dialog.manifest.rowCount() == len(receipt.entries)
        assert "Planned files" in dialog.details.toPlainText()
        assert dialog.open_manifest_button.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qt_app.processEvents()
