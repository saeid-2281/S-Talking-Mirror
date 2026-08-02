from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.gui.dialogs.generation_launch_receipt_dialog import GenerationLaunchReceiptDialog
from app.gui.dialogs.generation_launch_receipt_drift_dialog import (
    GenerationLaunchReceiptDriftDialog,
)
from app.models import AppSettings
from app.models.generation_launch_receipt import GenerationLaunchReceipt
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


def _dispose_dialog(qt_app: QApplication, dialog: QDialog | None) -> None:
    """Flush WA_DeleteOnClose while QApplication is still fully alive."""
    if dialog is None:
        return
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def _plan(**overrides) -> BatchGenerationPlan:
    values = dict(
        provider="elevenlabs",
        model="model-a",
        files=10,
        characters=10_000,
        provider_requests=10,
        estimated_cost=1.0,
        currency="USD",
        price_per_million_characters=100.0,
        pricing_source="test-rate",
        estimated_duration_seconds=120.0,
        estimated_completion_at="2026-08-02T12:02:00+00:00",
        throughput_confidence="high",
        limiting_factor="characters",
        historical_session_count=6,
        quota_remaining=20_000,
        quota_shortfall=0,
        quota_usage_percent=50.0,
        max_queue_cost=2.0,
        budget_usage_percent=50.0,
        risk_level="low",
        reasons=("All checks are within limits.",),
        scenarios=(
            GenerationPlanScenario("base", "Base", 0, 10, 10_000, 10, 1.0, 120.0),
            GenerationPlanScenario(
                "expected", "Expected retries", 20, 10, 12_000, 12, 1.2, 144.0
            ),
            GenerationPlanScenario(
                "stress", "Stress test", 25, 10, 12_500, 12, 1.25, 150.0
            ),
        ),
    )
    values.update(overrides)
    return BatchGenerationPlan(**values)


def _state(**overrides) -> PreflightState:
    values = dict(
        total_jobs=10,
        valid_jobs=10,
        estimated_files=10,
        estimated_characters=10_000,
        estimated_provider_requests=10,
        estimated_duration_seconds=120.0,
        estimated_cost=1.0,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="preflight-revision",
        settings_revision="settings-revision",
        generation_plan=_plan(),
    )
    values.update(overrides)
    return PreflightState(**values)


def _write_receipt(
    reports_dir: Path,
    *,
    project_name: str = "Phase 37 Project",
    provider: str = "elevenlabs",
    model: str = "model-a",
    voice: str = "voice-a",
    output_name: str = "output-a",
    overwrite_existing: bool = False,
    skip_existing: bool = True,
    state: PreflightState | None = None,
) -> Path:
    coordinator = GenerationConfirmationCoordinator()
    current_state = state or _state(
        generation_plan=_plan(provider=provider, model=model)
    )
    settings = AppSettings(
        provider=provider,
        api_key="must-never-be-serialized",
        model_id=model,
        voice_id=voice,
        language_code="da",
        file_extension=".mp3",
        max_retries=3,
        delay_seconds=0.5,
        skip_existing=skip_existing,
        overwrite_existing=overwrite_existing,
        generation_scope="pending",
        execution_order="source",
    )
    confirmation = coordinator.evaluate(current_state, settings)
    return coordinator.write_receipt(
        confirmation,
        current_state,
        settings,
        reports_dir=reports_dir,
        project_name=project_name,
        output_dir=reports_dir / output_name,
        acknowledged_codes=confirmation.required_acknowledgements,
    )


def test_phase37_project_baseline_persists_and_resolves(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    path = _write_receipt(reports_dir)
    service = GenerationLaunchReceiptService(reports_dir)
    receipt = service.load(path)

    index_path = service.set_baseline(receipt)
    resolved = service.baseline(receipt.project_name)

    assert index_path.exists()
    assert resolved is not None
    assert resolved.receipt_id == receipt.receipt_id
    assert service.is_baseline(receipt) is True
    index_text = index_path.read_text(encoding="utf-8")
    assert "must-never-be-serialized" not in index_text
    assert service.clear_baseline(receipt.project_name) is True
    assert service.baseline(receipt.project_name) is None


def test_phase37_integrity_mismatch_cannot_become_baseline(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    path = _write_receipt(reports_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scope"]["characters"] = 999_999
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    service = GenerationLaunchReceiptService(reports_dir)
    receipt = service.load(path)

    assert receipt.integrity_status == "mismatch"
    with pytest.raises(ValueError):
        service.set_baseline(receipt)


def test_phase37_matching_receipts_have_no_drift(tmp_path: Path) -> None:
    path = _write_receipt(tmp_path / "reports")
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    receipt = service.load(path)

    comparison = service.compare(receipt, receipt)

    assert comparison.status == "matching"
    assert comparison.changed_count == 0
    assert comparison.critical_count == 0
    assert comparison.safe_to_reuse is True


def test_phase37_compare_classifies_critical_launch_drift(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    baseline = GenerationLaunchReceipt(
        Path("baseline.json"),
        Path("baseline.md"),
        project_name="Project",
        integrity_status="verified",
        provider="elevenlabs",
        model_id="model-a",
        voice_id="voice-a",
        output_directory="D:/audio-a",
        overwrite_existing=False,
        skip_existing=True,
        risk_level="low",
        files=10,
        characters=10_000,
        provider_requests=10,
    )
    candidate = replace(
        baseline,
        path=Path("candidate.json"),
        provider="openai",
        output_directory="D:/audio-b",
        overwrite_existing=True,
        risk_level="high",
    )

    comparison = service.compare(baseline, candidate)
    keys = {item.key for item in comparison.changes}

    assert comparison.status == "critical_drift"
    assert comparison.critical_count >= 4
    assert {"provider", "output_directory", "overwrite_existing", "risk_level"} <= keys
    assert comparison.safe_to_reuse is False


def test_phase37_compare_tracks_scope_cost_and_execution_changes(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    baseline = GenerationLaunchReceipt(
        Path("baseline.json"),
        Path("baseline.md"),
        project_name="Project",
        integrity_status="verified",
        model_id="model-a",
        max_retries=2,
        delay_seconds=0.2,
        generation_scope="pending",
        execution_order="source",
        files=10,
        characters=10_000,
        provider_requests=10,
        estimated_cost=1.0,
    )
    candidate = replace(
        baseline,
        path=Path("candidate.json"),
        max_retries=5,
        delay_seconds=1.0,
        generation_scope="all",
        execution_order="priority",
        files=20,
        characters=25_000,
        provider_requests=25,
        estimated_cost=2.5,
    )

    comparison = service.compare(baseline, candidate)
    keys = {item.key for item in comparison.changes}

    assert comparison.status == "drift"
    assert comparison.warning_count >= 4
    assert {
        "max_retries",
        "delay_seconds",
        "generation_scope",
        "execution_order",
        "files",
        "characters",
        "provider_requests",
        "estimated_cost",
    } <= keys


def test_phase37_drift_export_is_secret_free(tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    first = _write_receipt(reports_dir, output_name="baseline-output")
    second = _write_receipt(
        reports_dir,
        provider="openai",
        model="model-b",
        output_name="candidate-output",
    )
    service = GenerationLaunchReceiptService(reports_dir)
    comparison = service.compare(service.load(first), service.load(second))

    json_path, markdown_path = service.export_comparison(
        comparison, tmp_path / "exports"
    )
    exported = json_path.read_text(encoding="utf-8") + markdown_path.read_text(
        encoding="utf-8"
    )

    assert json_path.exists() and markdown_path.exists()
    assert "critical_drift" in exported
    assert "must-never-be-serialized" not in exported
    assert "api_key" not in exported


def test_phase37_drift_dialog_renders_metrics_copy_and_export(
    qt_app, tmp_path: Path
) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    baseline = GenerationLaunchReceipt(
        Path("baseline.json"),
        Path("baseline.md"),
        receipt_id="baseline-id",
        project_name="Project",
        integrity_status="verified",
        provider="elevenlabs",
        output_directory="D:/one",
    )
    candidate = replace(
        baseline,
        path=Path("candidate.json"),
        receipt_id="candidate-id",
        provider="openai",
        output_directory="D:/two",
    )
    comparison = service.compare(baseline, candidate)
    dialog = GenerationLaunchReceiptDriftDialog(
        service,
        comparison,
        export_dir=tmp_path / "exports",
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.objectName() == "generationLaunchReceiptDriftDialog"
    assert dialog.table.rowCount() == comparison.changed_count
    assert dialog.metric_values["critical"].text() == str(comparison.critical_count)
    copied = dialog.copy_summary()
    assert "baseline-id" in copied
    assert QApplication.clipboard().text() == copied
    exported = dialog.export_report()
    assert all(path.exists() for path in exported)
    _dispose_dialog(qt_app, dialog)


def test_phase37_receipt_dialog_sets_baseline_and_opens_drift_view(
    qt_app, tmp_path: Path
) -> None:
    reports_dir = tmp_path / "reports"
    first = _write_receipt(reports_dir, project_name="Current Project")
    second = _write_receipt(
        reports_dir,
        project_name="Current Project",
        model="model-b",
        output_name="output-b",
    )
    service = GenerationLaunchReceiptService(reports_dir)
    service.set_baseline(service.load(first))
    dialog = GenerationLaunchReceiptDialog(
        service,
        project_name="Current Project",
        export_dir=tmp_path / "exports",
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.table.rowCount() == 2
    assert "Baseline for Current Project" in dialog.baseline_label.text()
    candidate = service.load(second)
    row = next(
        row
        for row in range(dialog.table.rowCount())
        if dialog.filtered_receipts[row].receipt_id == candidate.receipt_id
    )
    dialog.table.selectRow(row)
    qt_app.processEvents()
    assert dialog.compare_baseline_button.isEnabled() is True
    drift_dialog = dialog.compare_selected_to_baseline()
    qt_app.processEvents()
    assert drift_dialog is not None
    assert drift_dialog.table.rowCount() > 0
    _dispose_dialog(qt_app, drift_dialog)
    assert drift_dialog not in dialog.drift_dialogs
    _dispose_dialog(qt_app, dialog)
