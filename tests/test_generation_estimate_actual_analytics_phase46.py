from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QTableWidget

from app.gui.dialogs.generation_estimate_actual_dialog import GenerationEstimateActualDialog
from app.models.generation_execution_receipt import GenerationExecutionReceipt
from app.models.generation_execution_session import (
    GenerationExecutionJob,
    GenerationExecutionSession,
)
from app.models.generation_launch_receipt import GenerationLaunchReceipt
from app.services.generation_estimate_actual_service import GenerationEstimateActualService
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class _LaunchService:
    def __init__(self, receipt: GenerationLaunchReceipt | None) -> None:
        self.receipt = receipt

    def load(self, _path: Path) -> GenerationLaunchReceipt:
        assert self.receipt is not None
        return self.receipt


class _ExecutionReceiptService:
    def __init__(self, receipts: list[GenerationExecutionReceipt]) -> None:
        self.receipts = receipts

    def list_receipts(self, *, limit: int = 1000) -> list[GenerationExecutionReceipt]:
        return self.receipts[:limit]


class _ExecutionSessionService:
    def __init__(self, session: GenerationExecutionSession | None) -> None:
        self.session = session

    def load(self, _path: Path) -> GenerationExecutionSession:
        assert self.session is not None
        return self.session


def _evidence(tmp_path: Path) -> tuple[GenerationLaunchReceipt, GenerationExecutionSession, GenerationExecutionReceipt]:
    launch_path = tmp_path / "generation-launch-receipt.json"
    session_path = tmp_path / "generation-execution.json"
    execution_path = tmp_path / "generation-execution-receipt.json"
    launch_path.write_text("{}", encoding="utf-8")
    session_path.write_text("{}", encoding="utf-8")
    execution_path.write_text("{}", encoding="utf-8")
    launch = GenerationLaunchReceipt(
        path=launch_path,
        markdown_path=launch_path.with_suffix(".md"),
        receipt_id="launch-1",
        project_name="Alpha",
        provider="elevenlabs",
        model_id="turbo",
        voice_id="voice-a",
        files=2,
        characters=1000,
        provider_requests=2,
        estimated_duration_seconds=10.0,
        estimated_cost=1.0,
        currency="USD",
        integrity_status="verified",
    )
    jobs = (
        GenerationExecutionJob(
            row_number=1,
            filename="a.mp3",
            character_count=500,
            status="completed",
            retry_count=1,
        ),
        GenerationExecutionJob(
            row_number=2,
            filename="b.mp3",
            character_count=400,
            status="completed",
        ),
    )
    session = GenerationExecutionSession(
        path=session_path,
        markdown_path=session_path.with_suffix(".md"),
        run_id="run-1",
        status="completed",
        project_name="Alpha",
        completed_jobs=2,
        total_jobs=2,
        total_characters=1000,
        processed_characters=900,
        retry_events=1,
        elapsed_seconds=20.0,
        jobs=jobs,
        integrity_status="verified",
    )
    receipt = GenerationExecutionReceipt(
        path=execution_path,
        markdown_path=execution_path.with_suffix(".md"),
        manifest_csv_path=tmp_path / "output-manifest.csv",
        receipt_id="execution-1",
        run_id="run-1",
        status="completed",
        project_name="Alpha",
        launch_receipt_id="launch-1",
        launch_receipt_path=str(launch_path),
        execution_session_path=str(session_path),
        provider="elevenlabs",
        model_id="turbo",
        voice_id="voice-a",
        finished_at="2026-08-03T10:00:00+00:00",
        elapsed_seconds=20.0,
        planned_files=2,
        planned_characters=1000,
        planned_requests=2,
        actual_outputs=2,
        created_outputs=2,
        integrity_status="verified",
    )
    return launch, session, receipt


def _service(
    tmp_path: Path,
    launch: GenerationLaunchReceipt | None,
    session: GenerationExecutionSession | None,
    receipts: list[GenerationExecutionReceipt],
) -> GenerationEstimateActualService:
    return GenerationEstimateActualService(
        tmp_path,
        launch_receipt_service=_LaunchService(launch),
        execution_receipt_service=_ExecutionReceiptService(receipts),
        execution_session_service=_ExecutionSessionService(session),
    )


def test_run_analysis_compares_estimates_with_actual_execution(tmp_path: Path) -> None:
    launch, session, receipt = _evidence(tmp_path)
    record = _service(tmp_path, launch, session, [receipt]).analyze_receipt(receipt)

    assert record.estimated_characters == 1000
    assert record.actual_characters == 900
    assert record.retry_characters == 500
    assert record.actual_requests == 3
    assert record.actual_duration_seconds == 20.0
    assert record.actual_cost == 1.4
    assert record.cost_source == "derived_from_launch_rate"
    assert record.estimate_accuracy_score == 60.0
    assert record.duration_multiplier == 2.0
    assert record.cost_multiplier == 1.4
    assert record.requires_attention is True


def test_summary_reports_overruns_accuracy_and_retries(tmp_path: Path) -> None:
    launch, session, receipt = _evidence(tmp_path)
    service = _service(tmp_path, launch, session, [receipt])
    summary = service.summary(service.list_runs())

    assert summary.total_runs == 1
    assert summary.completed_runs == 1
    assert summary.estimated_cost == 1.0
    assert summary.actual_cost == 1.4
    assert summary.duration_overrun_count == 1
    assert summary.cost_overrun_count == 1
    assert summary.total_retry_events == 1


def test_provider_calibration_groups_runs_and_recommends_adjustments(tmp_path: Path) -> None:
    launch, session, receipt = _evidence(tmp_path)
    service = _service(tmp_path, launch, session, [receipt])
    records = [service.analyze_receipt(receipt)] * 3
    providers = service.provider_summaries(records)

    assert len(providers) == 1
    summary = providers[0]
    assert summary.provider == "elevenlabs"
    assert summary.run_count == 3
    assert summary.duration_multiplier == 2.0
    assert summary.cost_multiplier == 1.4
    assert any("Increase ETA calibration" in item for item in summary.recommendations)
    assert any("Increase cost calibration" in item for item in summary.recommendations)


def test_list_runs_filters_project_provider_status_and_search(tmp_path: Path) -> None:
    launch, session, receipt = _evidence(tmp_path)
    service = _service(tmp_path, launch, session, [receipt])

    assert len(service.list_runs(project_name="Alpha")) == 1
    assert len(service.list_runs(provider="elevenlabs")) == 1
    assert len(service.list_runs(status="completed")) == 1
    assert len(service.list_runs(search="turbo")) == 1
    assert service.list_runs(project_name="Other") == []


def test_export_writes_secret_free_run_and_calibration_files(tmp_path: Path) -> None:
    launch, session, receipt = _evidence(tmp_path)
    service = _service(tmp_path, launch, session, [receipt])
    record = service.analyze_receipt(receipt)
    json_path, csv_path, calibration_path = service.export(
        [record],
        tmp_path / "exports",
        project_name="Alpha",
    )

    assert json_path.is_file()
    assert csv_path.is_file()
    assert calibration_path.is_file()
    combined = "\n".join(
        path.read_text(encoding="utf-8-sig") for path in (json_path, csv_path, calibration_path)
    )
    assert "run-1" in combined
    assert "advisory" in combined.casefold()
    assert "api_key" not in combined.casefold()
    assert "sk_" not in combined.casefold()


def test_missing_launch_or_session_evidence_is_low_confidence(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    receipt = GenerationExecutionReceipt(
        path=tmp_path / "generation-execution-receipt.json",
        markdown_path=tmp_path / "generation-execution-receipt.md",
        manifest_csv_path=tmp_path / "output-manifest.csv",
        run_id="run-missing",
        project_name="Alpha",
        status="partial",
        launch_receipt_path=str(missing),
        execution_session_path=str(missing),
        planned_files=4,
        actual_outputs=2,
        elapsed_seconds=4.0,
    )
    service = _service(tmp_path, None, None, [receipt])
    record = service.analyze_receipt(receipt)

    assert record.confidence == "low"
    assert record.estimated_files == 4
    assert record.actual_files == 2
    assert record.cost_source == "unavailable"
    assert record.requires_attention is True


def test_launch_receipt_loader_exposes_estimated_duration(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path)
    path = tmp_path / "Alpha" / "launch-receipts" / "one" / service.FILE_NAME
    path.parent.mkdir(parents=True)
    payload: dict[str, object] = {
        "schema_version": 2,
        "receipt_id": "launch-duration",
        "project_name": "Alpha",
        "settings": {"provider": "elevenlabs"},
        "scope": {"files": 2, "characters": 1000, "provider_requests": 2},
        "generation_plan": {
            "estimated_cost": 1.25,
            "estimated_duration_seconds": 42.5,
            "currency": "USD",
        },
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "digest": service.canonical_digest(payload),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    receipt = service.load(path)

    assert receipt.estimated_duration_seconds == 42.5
    assert receipt.estimated_cost == 1.25
    assert receipt.integrity_status == "verified"


def test_analytics_dialog_is_scroll_safe_and_releases_qt_widgets(
    qt_app,
    tmp_path: Path,
) -> None:
    launch, session, receipt = _evidence(tmp_path)
    service = _service(tmp_path, launch, session, [receipt])
    dialog = GenerationEstimateActualDialog(
        service,
        project_name="Alpha",
        export_dir=tmp_path / "exports",
    )

    assert dialog.objectName() == "generationEstimateActualDialog"
    assert dialog.run_table.rowCount() == 1
    assert dialog.provider_table.rowCount() == 1
    assert dialog.minimumWidth() >= 800
    assert dialog.current_project_only.isChecked() is True
    assert dialog.run_table.selectionBehavior() == QTableWidget.SelectRows

    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
