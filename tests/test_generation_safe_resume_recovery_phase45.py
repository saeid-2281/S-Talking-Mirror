from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent

from app.gui.dialogs.generation_safe_resume_dialog import GenerationSafeResumeDialog
from app.models import AppSettings, JobStatus, TTSJob
from app.models.generation_execution_receipt import (
    GenerationExecutionReceipt,
    GenerationOutputManifestEntry,
)
from app.services.generation_execution_receipt_service import GenerationExecutionReceiptService
from app.services.generation_execution_session_service import GenerationExecutionSessionService
from app.services.generation_safe_resume_service import GenerationSafeResumeService


def _settings(*, skip: bool = True, overwrite: bool = False) -> AppSettings:
    return AppSettings(
        provider="mock",
        api_key="sk_phase45_must_not_leak",
        model_id="model-a",
        voice_id="voice-a",
        file_extension=".mp3",
        skip_existing=skip,
        overwrite_existing=overwrite,
        generation_scope="selected",
        execution_order="csv",
    )


def _jobs() -> list[TTSJob]:
    return [
        TTSJob(row_number=1, text="Completed source text", filename="completed.mp3"),
        TTSJob(row_number=2, text="Failed source text", filename="failed.mp3", status=JobStatus.FAILED),
        TTSJob(row_number=3, text="Missing source text", filename="missing.mp3", status=JobStatus.COMPLETED),
        TTSJob(row_number=4, text="Incomplete source text", filename="incomplete.mp3", status=JobStatus.PENDING),
        TTSJob(row_number=5, text="Skipped source text", filename="skipped.mp3", status=JobStatus.SKIPPED),
    ]


def _parent_receipt(tmp_path: Path, *, integrity: str = "verified") -> GenerationExecutionReceipt:
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    completed = output / "completed.mp3"
    skipped = output / "skipped.mp3"
    completed.write_bytes(b"done")
    skipped.write_bytes(b"existing")
    entries = (
        GenerationOutputManifestEntry(1, "completed.mp3", str(completed), str(completed), "created", "completed", False, True),
        GenerationOutputManifestEntry(2, "failed.mp3", str(output / "failed.mp3"), disposition="failed", job_status="failed"),
        GenerationOutputManifestEntry(3, "missing.mp3", str(output / "missing.mp3"), disposition="missing", job_status="completed"),
        GenerationOutputManifestEntry(4, "incomplete.mp3", str(output / "incomplete.mp3"), disposition="incomplete", job_status="pending"),
        GenerationOutputManifestEntry(5, "skipped.mp3", str(skipped), str(skipped), "skipped_existing", "skipped", True, True),
        GenerationOutputManifestEntry(0, "unexpected.mp3", "", str(output / "unexpected.mp3"), "unexpected", "unexpected"),
    )
    return GenerationExecutionReceipt(
        path=tmp_path / "reports" / "Demo" / "runs" / "parent" / "generation-execution-receipt.json",
        markdown_path=tmp_path / "reports" / "Demo" / "runs" / "parent" / "generation-execution-receipt.md",
        manifest_csv_path=tmp_path / "reports" / "Demo" / "runs" / "parent" / "output-manifest.csv",
        receipt_id="execution-parent",
        run_id="run-parent",
        status="partial",
        project_name="Demo",
        project_id=7,
        project_key="demo-key",
        provider="mock",
        model_id="model-a",
        voice_id="voice-a",
        output_directory=str(output),
        failed_outputs=1,
        missing_outputs=1,
        incomplete_outputs=1,
        unexpected_outputs=1,
        entries=entries,
        integrity_status=integrity,
    )


def test_phase45_unresolved_preview_selects_only_failed_missing_and_incomplete(tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path)

    preview = service.preview(
        receipt=receipt,
        current_jobs=_jobs(),
        settings=_settings(),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
    )

    assert preview.allowed is True
    assert preview.selected_rows == (2, 3, 4)
    selected = {item.filename for item in preview.candidates if item.selected}
    assert selected == {"failed.mp3", "missing.mp3", "incomplete.mp3"}
    assert "unexpected.mp3" not in {item.filename for item in preview.candidates}


def test_phase45_blocks_tampered_or_incompatible_parent_run(tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path, integrity="mismatch")
    settings = _settings().model_copy(update={"provider": "other", "model_id": "model-b", "voice_id": "voice-b"})

    preview = service.preview(
        receipt=receipt,
        current_jobs=_jobs(),
        settings=settings,
        output_directory=tmp_path / "different-output",
        project_name="Other",
    )

    assert preview.allowed is False
    detail = " ".join(preview.blockers)
    assert "integrity" in detail.casefold()
    assert "different project" in detail.casefold()
    assert "provider changed" in detail.casefold()
    assert "output directory" in detail.casefold()


def test_phase45_entire_run_requires_safe_existing_file_policy(tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path)

    blocked = service.preview(
        receipt=receipt,
        current_jobs=_jobs(),
        settings=_settings(skip=False, overwrite=False),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
        scope="entire_run",
    )
    protected = service.preview(
        receipt=receipt,
        current_jobs=_jobs(),
        settings=_settings(skip=True),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
        scope="entire_run",
    )

    assert blocked.allowed is False
    assert any("neither Skip existing nor Overwrite" in item for item in blocked.blockers)
    assert protected.allowed is True
    assert protected.selected_rows == (1, 2, 3, 4, 5)
    assert any("protected by Skip existing" in item for item in protected.warnings)


def test_phase45_resume_receipt_is_integrity_protected_and_secret_free(tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path)
    preview = service.preview(
        receipt=receipt,
        current_jobs=_jobs(),
        settings=_settings(),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
    )

    recovery = service.create_receipt(preview)
    exported = recovery.path.read_text(encoding="utf-8") + recovery.markdown_path.read_text(encoding="utf-8")

    assert recovery.integrity_status == "verified"
    assert recovery.parent_run_id == "run-parent"
    assert recovery.selected_rows == (2, 3, 4)
    assert "sk_phase45_must_not_leak" not in exported
    assert "Failed source text" not in exported


def test_phase45_prepare_jobs_resets_only_selected_rows(tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path)
    jobs = _jobs()
    preview = service.preview(
        receipt=receipt,
        current_jobs=jobs,
        settings=_settings(),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
        scope="failed_only",
    )
    recovery = service.create_receipt(preview)
    jobs[1].error = "api_key=sk_never_export"
    jobs[1].error_code = "provider_error"
    jobs[0].status = JobStatus.COMPLETED

    prepared, rows = service.prepare_jobs(recovery, jobs)

    assert rows == (2,)
    assert prepared[1].status == JobStatus.PENDING
    assert prepared[1].error is None
    assert prepared[1].error_code is None
    assert prepared[0].status == JobStatus.COMPLETED
    assert service.compatibility_issues(
        recovery,
        current_jobs=prepared,
        settings=_settings(),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
    ) == ()
    changed = _settings().model_copy(update={"voice_id": "voice-b"})
    assert "voice" in service.compatibility_issues(
        recovery,
        current_jobs=prepared,
        settings=changed,
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
    )
    prepared[1].text = "Changed source after the recovery plan was created"
    assert "source changed for row 2" in service.compatibility_issues(
        recovery,
        current_jobs=prepared,
        settings=_settings(),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
    )


def test_phase45_mark_started_links_new_run_and_detects_tampering(tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path)
    preview = service.preview(
        receipt=receipt,
        current_jobs=_jobs(),
        settings=_settings(),
        output_directory=Path(receipt.output_directory),
        project_name="Demo",
    )
    recovery = service.create_receipt(preview)

    started = service.mark_started(recovery, new_run_id="run-child")
    finished = service.mark_finished(
        started,
        result="partial",
        execution_receipt_id="execution-child",
        execution_receipt_path=tmp_path / "execution-child.json",
    )
    payload = json.loads(finished.path.read_text(encoding="utf-8"))
    payload["new_run_id"] = "run-tampered"
    finished.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    changed = service.load(finished.path)

    assert started.status == "started"
    assert started.new_run_id == "run-child"
    assert finished.status == "partial"
    assert finished.execution_receipt_id == "execution-child"
    assert changed.integrity_status == "mismatch"


def test_phase45_execution_session_and_receipt_preserve_parent_recovery_links(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    output = tmp_path / "output"
    output.mkdir()
    settings = _settings()
    jobs = [TTSJob(row_number=2, text="Retry", filename="failed.mp3", status=JobStatus.COMPLETED)]
    (output / "failed.mp3").write_bytes(b"recovered")
    session_service = GenerationExecutionSessionService(reports)
    session = session_service.start_session(
        run_id="run-child",
        project_name="Demo",
        project_id=7,
        project_key="demo-key",
        launch_receipt_path=None,
        launch_receipt_id="launch-child",
        launch_fingerprint="a" * 64,
        decision_trace_id="decision-child",
        guard_approval_id="",
        settings=settings,
        jobs=jobs,
        output_directory=output,
        parent_run_id="run-parent",
        resume_receipt_id="resume-1",
        resume_receipt_path=reports / "Demo" / "recoveries" / "resume-1" / "generation-resume.json",
        resume_scope="failed_only",
    )
    session = session_service.finish_session(
        session.run_id,
        jobs,
        project_name="Demo",
        settings=settings,
        output_directory=output,
        result="completed",
    )
    execution = GenerationExecutionReceiptService(reports).create_receipt(
        session=session,
        jobs=jobs,
        settings=settings,
        output_directory=output,
        discover_unexpected=False,
    )

    assert session.parent_run_id == "run-parent"
    assert session.resume_receipt_id == "resume-1"
    assert execution.parent_run_id == "run-parent"
    assert execution.resume_receipt_id == "resume-1"
    assert execution.resume_scope == "failed_only"


def test_phase45_dialog_updates_scope_and_cleans_up(qt_app, tmp_path: Path) -> None:
    service = GenerationSafeResumeService(tmp_path / "reports")
    receipt = _parent_receipt(tmp_path)
    dialog = GenerationSafeResumeDialog(
        service,
        receipt,
        _jobs(),
        _settings(),
        Path(receipt.output_directory),
        "Demo",
    )

    assert dialog.preview is not None and dialog.preview.selected_rows == (2, 3, 4)
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("failed_only"))
    assert dialog.preview is not None and dialog.preview.selected_rows == (2,)
    assert dialog.prepare_button.isEnabled()

    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
