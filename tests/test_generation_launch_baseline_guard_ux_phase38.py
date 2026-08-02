from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.gui.dialogs.generation_launch_guard_policy_dialog import (
    GenerationLaunchGuardPolicyDialog,
)
from app.gui.dialogs.generation_launch_receipt_dialog import GenerationLaunchReceiptDialog
from app.models import AppSettings
from app.models.generation_launch_receipt import GenerationLaunchReceipt
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


def _dispose_dialog(qt_app: QApplication, dialog: QDialog | None) -> None:
    if dialog is None:
        return
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def _plan(provider: str = "mock", model: str = "model-a") -> BatchGenerationPlan:
    return BatchGenerationPlan(
        provider=provider,
        model=model,
        files=10,
        characters=10_000,
        provider_requests=10,
        estimated_cost=1.0,
        currency="USD",
        price_per_million_characters=100.0,
        pricing_source="phase38-test",
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


def _state(provider: str = "mock", model: str = "model-a") -> PreflightState:
    return PreflightState(
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
        generation_plan=_plan(provider, model),
    )


def _settings(
    provider: str = "mock",
    model: str = "model-a",
    *,
    overwrite_existing: bool = False,
) -> AppSettings:
    return AppSettings(
        provider=provider,
        api_key="must-never-be-serialized",
        model_id=model,
        voice_id="voice-a",
        language_code="da",
        file_extension=".mp3",
        max_retries=3,
        delay_seconds=0.5,
        skip_existing=not overwrite_existing,
        overwrite_existing=overwrite_existing,
        generation_scope="pending",
        execution_order="source",
    )


def _baseline(
    reports_dir: Path,
    *,
    project_name: str = "Phase 38 Project",
    provider: str = "mock",
    model: str = "model-a",
    output_dir: Path | None = None,
) -> tuple[GenerationLaunchReceiptService, GenerationLaunchReceipt]:
    service = GenerationLaunchReceiptService(reports_dir)
    coordinator = GenerationConfirmationCoordinator()
    state = _state(provider, model)
    settings = _settings(provider, model)
    output = output_dir or reports_dir / "audio"
    confirmation = coordinator.evaluate(state, settings)
    path = coordinator.write_receipt(
        confirmation,
        state,
        settings,
        reports_dir=reports_dir,
        project_name=project_name,
        output_dir=output,
        acknowledged_codes=confirmation.required_acknowledgements,
    )
    receipt = service.load(path)
    service.set_baseline(receipt)
    return service, receipt


def _candidate(
    baseline: GenerationLaunchReceipt,
    *,
    provider: str | None = None,
    model: str | None = None,
    files: int | None = None,
) -> GenerationLaunchReceipt:
    return GenerationLaunchReceipt(
        path=Path("candidate.json"),
        markdown_path=Path("candidate.md"),
        project_name=baseline.project_name,
        integrity_status="verified",
        provider=provider or baseline.provider,
        model_id=model or baseline.model_id,
        voice_id=baseline.voice_id,
        language_code=baseline.language_code,
        file_extension=baseline.file_extension,
        max_retries=baseline.max_retries,
        delay_seconds=baseline.delay_seconds,
        skip_existing=baseline.skip_existing,
        overwrite_existing=baseline.overwrite_existing,
        generation_scope=baseline.generation_scope,
        execution_order=baseline.execution_order,
        output_directory=baseline.output_directory,
        files=files if files is not None else baseline.files,
        characters=baseline.characters,
        provider_requests=baseline.provider_requests,
        existing_outputs=baseline.existing_outputs,
        risk_level=baseline.risk_level,
        estimated_cost=baseline.estimated_cost,
        currency=baseline.currency,
        preflight_status=baseline.preflight_status,
        review_status=baseline.review_status,
        required_acknowledgements=baseline.required_acknowledgements,
        acknowledged_codes=baseline.acknowledged_codes,
    )


def test_phase38_guard_policy_defaults_to_warn_and_all_categories(tmp_path: Path) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")

    policy = service.guard_policy("New Project")

    assert policy.mode == "warn"
    assert policy.enabled is True
    assert policy.protected_categories == service.GUARD_CATEGORIES


def test_phase38_guard_policy_persists_secret_free_project_configuration(
    tmp_path: Path,
) -> None:
    service = GenerationLaunchReceiptService(tmp_path / "reports")

    path = service.set_guard_policy(
        "Protected Project",
        mode="enforce",
        protected_categories=("Provider", "Output policy", "Integrity"),
    )
    policy = service.guard_policy("Protected Project")
    text = path.read_text(encoding="utf-8")

    assert policy.mode == "enforce"
    assert policy.blocks_critical_drift is True
    assert policy.protected_categories == (
        "Provider",
        "Output policy",
        "Integrity",
    )
    assert "must-never-be-serialized" not in text
    assert "api_key" not in text


def test_phase38_enforce_mode_blocks_critical_protected_drift(tmp_path: Path) -> None:
    service, baseline = _baseline(tmp_path / "reports")
    service.set_guard_policy(
        baseline.project_name,
        mode="enforce",
        protected_categories=("Provider", "Integrity"),
    )

    decision = service.evaluate_guard(_candidate(baseline, provider="openai"))

    assert decision.status == "blocked"
    assert decision.allowed is False
    assert decision.critical_count == 1
    assert {item.key for item in decision.protected_changes} == {"provider"}


def test_phase38_warn_mode_requires_acknowledgement_for_protected_drift(
    tmp_path: Path,
) -> None:
    service, baseline = _baseline(tmp_path / "reports")
    service.set_guard_policy(
        baseline.project_name,
        mode="warn",
        protected_categories=("Provider",),
    )

    decision = service.evaluate_guard(_candidate(baseline, model="model-b"))

    assert decision.status == "review_required"
    assert decision.allowed is True
    assert decision.requires_acknowledgement is True
    assert decision.warning_count == 1


def test_phase38_unprotected_drift_does_not_interrupt_launch(tmp_path: Path) -> None:
    service, baseline = _baseline(tmp_path / "reports")
    service.set_guard_policy(
        baseline.project_name,
        mode="enforce",
        protected_categories=("Scope",),
    )

    decision = service.evaluate_guard(_candidate(baseline, provider="openai"))

    assert decision.status == "matching"
    assert decision.allowed is True
    assert decision.protected_changes == ()


def test_phase38_confirmation_coordinator_blocks_enforced_provider_change(
    tmp_path: Path,
) -> None:
    reports_dir = tmp_path / "reports"
    output_dir = reports_dir / "audio"
    service, baseline = _baseline(reports_dir, output_dir=output_dir)
    service.set_guard_policy(
        baseline.project_name,
        mode="enforce",
        protected_categories=("Provider",),
    )

    confirmation = GenerationConfirmationCoordinator().evaluate(
        _state("openai", "model-b"),
        _settings("openai", "model-b"),
        receipt_service=service,
        project_name=baseline.project_name,
        output_dir=output_dir,
    )

    assert confirmation.allowed is False
    assert confirmation.status == "baseline_guard_blocked"
    assert any(item.code == "baseline_drift_blocked" for item in confirmation.checks)


def test_phase38_confirmation_coordinator_marks_matching_baseline_ready(
    tmp_path: Path,
) -> None:
    reports_dir = tmp_path / "reports"
    output_dir = reports_dir / "audio"
    service, baseline = _baseline(reports_dir, output_dir=output_dir)
    service.set_guard_policy(
        baseline.project_name,
        mode="enforce",
        protected_categories=service.GUARD_CATEGORIES,
    )

    confirmation = GenerationConfirmationCoordinator().evaluate(
        _state(),
        _settings(),
        receipt_service=service,
        project_name=baseline.project_name,
        output_dir=output_dir,
    )

    assert confirmation.allowed is True
    assert "baseline_drift_guard" not in confirmation.required_acknowledgements
    assert any(item.code == "baseline_guard_matching" for item in confirmation.checks)


def test_phase38_guard_policy_dialog_and_receipt_center_manage_policy(
    qt_app: QApplication, tmp_path: Path
) -> None:
    reports_dir = tmp_path / "reports"
    service, baseline = _baseline(reports_dir)
    policy_dialog = GenerationLaunchGuardPolicyDialog(
        service,
        baseline.project_name,
    )
    policy_dialog.show()
    qt_app.processEvents()

    enforce_index = policy_dialog.mode_combo.findData("enforce")
    policy_dialog.mode_combo.setCurrentIndex(enforce_index)
    policy_dialog.category_boxes["Scope"].setChecked(False)
    saved = policy_dialog.save_policy()

    assert policy_dialog.objectName() == "generationLaunchGuardPolicyDialog"
    assert saved is not None and saved.mode == "enforce"
    assert "Scope" not in saved.protected_categories
    _dispose_dialog(qt_app, policy_dialog)

    receipt_dialog = GenerationLaunchReceiptDialog(
        service,
        project_name=baseline.project_name,
    )
    receipt_dialog.show()
    qt_app.processEvents()
    receipt_dialog.table.selectRow(0)
    qt_app.processEvents()
    child = receipt_dialog.open_guard_policy()
    qt_app.processEvents()

    assert child is not None
    assert child in receipt_dialog.guard_policy_dialogs
    assert "Enforce critical drift" in receipt_dialog.guard_policy_label.text()
    _dispose_dialog(qt_app, child)
    _dispose_dialog(qt_app, receipt_dialog)
