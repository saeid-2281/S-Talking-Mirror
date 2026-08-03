from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.gui.dialogs.generation_launch_dialog import GenerationLaunchDialog
from app.models import AppSettings
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightIssue, PreflightState
from app.services.generation_confirmation_service import (
    GenerationConfirmationCoordinator,
    GenerationLaunchCheck,
)
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService
from app.services.unified_preflight_decision_service import UnifiedPreflightDecisionService


def _dispose_dialog(qt_app: QApplication, dialog: QDialog | None) -> None:
    if dialog is None:
        return
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def _plan(*, risk: str = "low") -> BatchGenerationPlan:
    return BatchGenerationPlan(
        provider="mock",
        model="model-a",
        files=2,
        characters=2_000,
        provider_requests=2,
        estimated_cost=0.2,
        currency="USD",
        price_per_million_characters=100.0,
        pricing_source="phase42-test",
        estimated_duration_seconds=20.0,
        estimated_completion_at="2026-08-03T12:00:00+00:00",
        throughput_confidence="high",
        limiting_factor="characters",
        historical_session_count=4,
        quota_remaining=10_000,
        quota_shortfall=0,
        quota_usage_percent=20.0,
        max_queue_cost=1.0,
        budget_usage_percent=20.0,
        risk_level=risk,
        reasons=("Ready",) if risk == "low" else ("Elevated retry exposure",),
        scenarios=(
            GenerationPlanScenario("base", "Base", 0, 2, 2_000, 2, 0.2, 20.0),
            GenerationPlanScenario("expected", "Expected", 10, 2, 2_200, 2, 0.22, 22.0),
            GenerationPlanScenario("stress", "Stress", 25, 2, 2_500, 3, 0.25, 25.0),
        ),
    )


def _state(
    *,
    issues: list[PreflightIssue] | None = None,
    warnings: int = 0,
    blocking_errors: int = 0,
    provider_ready: bool = True,
    output_ready: bool = True,
    existing_outputs: list[str] | None = None,
    revision: str = "phase42-preflight",
) -> PreflightState:
    return PreflightState(
        total_jobs=2,
        valid_jobs=2,
        blocking_errors=blocking_errors,
        warnings=warnings,
        estimated_files=2,
        estimated_characters=2_000,
        estimated_provider_requests=2,
        estimated_duration_seconds=20.0,
        estimated_cost=0.2,
        provider_ready=provider_ready,
        output_directory_ready=output_ready,
        can_start=not blocking_errors and provider_ready and output_ready,
        existing_outputs=existing_outputs or [],
        issues=issues or [],
        revision=revision,
        settings_revision="phase42-settings",
        generation_plan=_plan(),
    )


def _settings(*, model_id: str = "model-a") -> AppSettings:
    return AppSettings(
        provider="mock",
        api_key="must-never-be-serialized",
        model_id=model_id,
        voice_id="voice-a",
        language_code="da",
        file_extension=".mp3",
        max_retries=3,
        delay_seconds=0.5,
        skip_existing=True,
        overwrite_existing=False,
        generation_scope="pending",
        execution_order="source",
    )


def test_phase42_ready_decision_is_deterministic_and_explainable() -> None:
    service = UnifiedPreflightDecisionService()
    checks = (
        GenerationLaunchCheck("scope", "Generation scope", "2 files", "success"),
        GenerationLaunchCheck("provider", "Provider and model", "mock · model-a", "success"),
    )

    first = service.evaluate(_state(), _settings(), checks=checks)
    second = service.evaluate(_state(), _settings(), checks=checks)

    assert first.status == "ready"
    assert first.allowed is True
    assert first.headline == "Ready"
    assert first.trace_id == second.trace_id
    assert first.recommendations == ("Start generation with the reviewed plan.",)


def test_phase42_preparation_warning_becomes_ready_with_warnings() -> None:
    issue = PreflightIssue(
        severity="warning",
        row=2,
        filename="lesson-2.mp3",
        message="Duplicate text appears in the batch.",
        suggested_action="Confirm this repeated text is intentional.",
        code="duplicate_text",
    )
    decision = UnifiedPreflightDecisionService().evaluate(
        _state(issues=[issue], warnings=1),
        _settings(),
    )

    assert decision.status == "ready_with_warnings"
    assert decision.warning_count == 1
    assert decision.signals[0].source == "Source preparation"
    assert "Confirm this repeated text" in decision.recommendations[0]


def test_phase42_acknowledgement_and_cost_uncertainty_require_approval() -> None:
    check = GenerationLaunchCheck(
        "pricing_unavailable",
        "Cost estimate is unavailable",
        "No pricing rate is configured.",
        "warning",
        True,
    )
    decision = UnifiedPreflightDecisionService().evaluate(
        _state(),
        _settings(),
        checks=(check,),
        required_acknowledgements=("pricing_unavailable",),
        base_status="confirmation_required",
    )

    assert decision.status == "approval_required"
    assert decision.allowed is True
    assert decision.approval_count == 1
    assert "Configure provider pricing" in decision.recommendations[0]


def test_phase42_blockers_override_warnings_and_approvals() -> None:
    issue = PreflightIssue(
        severity="hard_error",
        row=1,
        filename="bad:name.mp3",
        message="Filename is invalid on Windows.",
        suggested_action="Sanitize the filename.",
        code="invalid_filename",
    )
    decision = UnifiedPreflightDecisionService().evaluate(
        _state(
            issues=[issue],
            blocking_errors=1,
            provider_ready=False,
        ),
        _settings(),
        checks=(
            GenerationLaunchCheck(
                "preflight_warnings",
                "Preflight warnings",
                "One warning remains.",
                "warning",
                True,
            ),
        ),
        base_allowed=False,
        required_acknowledgements=("preflight_warnings",),
        base_status="blocked",
    )

    assert decision.status == "blocked"
    assert decision.allowed is False
    assert decision.blocker_count >= 2
    assert decision.recommendations[0] in {
        "Open Provider Workspace and resolve account, model, or voice readiness.",
        "Sanitize the filename.",
    }


def test_phase42_decision_trace_changes_when_launch_inputs_change() -> None:
    service = UnifiedPreflightDecisionService()

    first = service.evaluate(_state(revision="revision-a"), _settings(model_id="model-a"))
    changed_revision = service.evaluate(_state(revision="revision-b"), _settings(model_id="model-a"))
    changed_model = service.evaluate(_state(revision="revision-a"), _settings(model_id="model-b"))

    assert first.trace_id != changed_revision.trace_id
    assert first.trace_id != changed_model.trace_id


def test_phase42_guard_block_and_exception_map_to_one_decision_contract() -> None:
    service = UnifiedPreflightDecisionService()
    blocked = service.evaluate(
        _state(),
        _settings(),
        checks=(
            GenerationLaunchCheck(
                "baseline_drift_blocked",
                "Project baseline guard blocked launch",
                "Provider changed from the protected baseline.",
                "error",
            ),
        ),
        base_allowed=False,
        base_status="baseline_guard_blocked",
    )
    approved = service.evaluate(
        _state(),
        _settings(),
        checks=(
            GenerationLaunchCheck(
                "baseline_drift_exception",
                "Approved baseline guard exception",
                "Time-bound approval is active.",
                "warning",
                True,
            ),
        ),
        required_acknowledgements=("baseline_drift_exception",),
        base_status="confirmation_required",
    )

    assert blocked.status == "blocked"
    assert blocked.signals[0].source == "Baseline guard"
    assert approved.status == "approval_required"
    assert "Verify the approver" in approved.recommendations[0]


def test_phase42_receipt_persists_decision_trace_and_remains_secret_free(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    receipt_service = GenerationLaunchReceiptService(reports)
    coordinator = GenerationConfirmationCoordinator()
    confirmation = coordinator.evaluate(
        _state(),
        _settings(),
        receipt_service=receipt_service,
        project_name="Decision Project",
        output_dir=tmp_path / "audio",
    )
    path = coordinator.write_receipt(
        confirmation,
        _state(),
        _settings(),
        reports_dir=reports,
        project_name="Decision Project",
        output_dir=tmp_path / "audio",
        receipt_service=receipt_service,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    receipt = receipt_service.load(path)

    assert confirmation.unified_decision is not None
    assert payload["unified_decision"]["status"] == "ready"
    assert receipt.decision_status == "ready"
    assert receipt.decision_trace_id == confirmation.unified_decision.trace_id
    assert receipt.integrity_status == "verified"
    assert "must-never-be-serialized" not in path.read_text(encoding="utf-8")


def test_phase42_launch_dialog_renders_decision_and_recommendations(
    qt_app: QApplication,
) -> None:
    state = _state(existing_outputs=["C:/audio/existing.mp3"])
    confirmation = GenerationConfirmationCoordinator().evaluate(state, _settings())
    dialog = GenerationLaunchDialog(confirmation, state)
    dialog.show()
    qt_app.processEvents()

    assert confirmation.unified_decision is not None
    assert confirmation.unified_decision.status == "approval_required"
    assert dialog.decision_card.objectName() == "generationUnifiedDecisionStatus"
    assert "Recommended next actions" in dialog.decision_recommendations.text()
    assert dialog.start_button.isEnabled() is False
    for box in dialog.acknowledgement_boxes.values():
        box.setChecked(True)
    qt_app.processEvents()
    assert dialog.start_button.isEnabled() is True
    _dispose_dialog(qt_app, dialog)
