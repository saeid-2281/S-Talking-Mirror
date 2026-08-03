from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.gui.dialogs.generation_launch_guard_approval_dialog import (
    GenerationLaunchGuardApprovalDialog,
)
from app.gui.dialogs.generation_launch_receipt_dialog import GenerationLaunchReceiptDialog
from app.models import AppSettings
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import (
    GenerationConfirmation,
    GenerationConfirmationCoordinator,
)
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
        pricing_source="phase39-test",
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
        revision="phase39-preflight",
        settings_revision="phase39-settings",
        generation_plan=_plan(provider, model),
    )


def _settings(provider: str = "mock", model: str = "model-a") -> AppSettings:
    return AppSettings(
        provider=provider,
        api_key="must-never-be-serialized",
        model_id=model,
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


def _setup(
    tmp_path: Path,
) -> tuple[
    GenerationLaunchReceiptService,
    GenerationConfirmationCoordinator,
    Path,
    GenerationConfirmation,
]:
    reports_dir = tmp_path / "reports"
    output_dir = reports_dir / "audio"
    service = GenerationLaunchReceiptService(reports_dir)
    coordinator = GenerationConfirmationCoordinator()
    baseline_state = _state()
    baseline_settings = _settings()
    baseline_confirmation = coordinator.evaluate(baseline_state, baseline_settings)
    baseline_path = coordinator.write_receipt(
        baseline_confirmation,
        baseline_state,
        baseline_settings,
        reports_dir=reports_dir,
        project_name="Phase 39 Project",
        output_dir=output_dir,
    )
    baseline = service.load(baseline_path)
    service.set_baseline(baseline)
    service.set_guard_policy(
        baseline.project_name,
        mode="enforce",
        protected_categories=("Provider",),
    )
    blocked = coordinator.evaluate(
        _state("openai", "model-b"),
        _settings("openai", "model-b"),
        receipt_service=service,
        project_name=baseline.project_name,
        output_dir=output_dir,
    )
    assert blocked.status == "baseline_guard_blocked"
    return service, coordinator, output_dir, blocked


def _approve(
    service: GenerationLaunchReceiptService,
    blocked: GenerationConfirmation,
    *,
    duration_minutes: int = 60,
    max_uses: int = 1,
):
    return service.create_guard_approval(
        project_name="Phase 39 Project",
        launch_fingerprint=blocked.guard_candidate_fingerprint,
        baseline_receipt_id=blocked.guard_baseline_receipt_id,
        protected_change_keys=blocked.guard_change_keys,
        reason="Approved provider migration for this controlled batch.",
        approved_by="Release operator",
        duration_minutes=duration_minutes,
        max_uses=max_uses,
    )


def test_phase39_approval_persists_exact_scope_without_secrets(tmp_path: Path) -> None:
    service, _, _, blocked = _setup(tmp_path)

    approval = _approve(service, blocked)
    text = service._guard_approval_index_path.read_text(encoding="utf-8")

    assert approval.status == "approved"
    assert approval.launch_fingerprint == blocked.guard_candidate_fingerprint
    assert approval.protected_change_keys == blocked.guard_change_keys
    assert "must-never-be-serialized" not in text
    assert "api_key" not in text


def test_phase39_approval_only_matches_exact_launch_fingerprint(tmp_path: Path) -> None:
    service, coordinator, output_dir, blocked = _setup(tmp_path)
    approval = _approve(service, blocked)

    accepted = coordinator.evaluate(
        _state("openai", "model-b"),
        _settings("openai", "model-b"),
        receipt_service=service,
        project_name="Phase 39 Project",
        output_dir=output_dir,
    )
    different = coordinator.evaluate(
        _state("azure", "model-c"),
        _settings("azure", "model-c"),
        receipt_service=service,
        project_name="Phase 39 Project",
        output_dir=output_dir,
    )

    assert accepted.allowed is True
    assert accepted.guard_approval_id == approval.approval_id
    assert "baseline_drift_exception" in accepted.required_acknowledgements
    assert different.allowed is False
    assert different.status == "baseline_guard_blocked"


def test_phase39_expired_approval_cannot_authorize_launch(tmp_path: Path) -> None:
    service, coordinator, output_dir, blocked = _setup(tmp_path)
    approval = _approve(service, blocked)
    payload = json.loads(service._guard_approval_index_path.read_text(encoding="utf-8"))
    payload["approvals"][0]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    service._write_guard_approval_index(payload)

    expired = service.list_guard_approvals(project_name="Phase 39 Project")[0]
    decision = coordinator.evaluate(
        _state("openai", "model-b"),
        _settings("openai", "model-b"),
        receipt_service=service,
        project_name="Phase 39 Project",
        output_dir=output_dir,
    )

    assert expired.approval_id == approval.approval_id
    assert expired.status == "expired"
    assert decision.allowed is False


def test_phase39_revoked_approval_cannot_authorize_launch(tmp_path: Path) -> None:
    service, coordinator, output_dir, blocked = _setup(tmp_path)
    approval = _approve(service, blocked)

    assert service.revoke_guard_approval(approval.approval_id) is True
    decision = coordinator.evaluate(
        _state("openai", "model-b"),
        _settings("openai", "model-b"),
        receipt_service=service,
        project_name="Phase 39 Project",
        output_dir=output_dir,
    )

    assert service.list_guard_approvals(project_name="Phase 39 Project")[0].status == "revoked"
    assert decision.status == "baseline_guard_blocked"


def test_phase39_receipt_records_and_consumes_one_time_approval(tmp_path: Path) -> None:
    service, coordinator, output_dir, blocked = _setup(tmp_path)
    approval = _approve(service, blocked)
    state = _state("openai", "model-b")
    settings = _settings("openai", "model-b")
    confirmation = coordinator.evaluate(
        state,
        settings,
        receipt_service=service,
        project_name="Phase 39 Project",
        output_dir=output_dir,
    )

    path = coordinator.write_receipt(
        confirmation,
        state,
        settings,
        reports_dir=service.reports_dir,
        project_name="Phase 39 Project",
        output_dir=output_dir,
        acknowledged_codes=confirmation.required_acknowledgements,
        receipt_service=service,
    )
    receipt = service.load(path)
    stored = service.list_guard_approvals(project_name="Phase 39 Project")[0]

    assert receipt.guard_approval_id == approval.approval_id
    assert stored.status == "consumed"
    assert stored.used_count == 1
    assert service.verify_payload(json.loads(path.read_text(encoding="utf-8")))[0] == "verified"


def test_phase39_multi_use_approval_tracks_remaining_uses(tmp_path: Path) -> None:
    service, _, _, blocked = _setup(tmp_path)
    approval = _approve(service, blocked, max_uses=2)

    assert approval.remaining_uses == 2
    assert service.consume_guard_approval(approval.approval_id) is True
    updated = service.list_guard_approvals(project_name="Phase 39 Project")[0]

    assert updated.status == "approved"
    assert updated.used_count == 1
    assert updated.remaining_uses == 1


def test_phase39_approval_dialog_creates_and_revokes_exception(
    qt_app: QApplication, tmp_path: Path
) -> None:
    service, _, _, blocked = _setup(tmp_path)
    dialog = GenerationLaunchGuardApprovalDialog(
        service,
        "Phase 39 Project",
        confirmation=blocked,
    )
    dialog.show()
    qt_app.processEvents()
    dialog.approved_by.setText("Release operator")
    dialog.reason.setPlainText("Approved provider migration for this controlled batch.")

    approval = dialog.create_exception()
    dialog.table.selectRow(0)
    revoked = dialog.revoke_selected()

    assert dialog.objectName() == "generationLaunchGuardApprovalDialog"
    assert approval is not None
    assert revoked is True
    assert service.list_guard_approvals(project_name="Phase 39 Project")[0].status == "revoked"
    _dispose_dialog(qt_app, dialog)


def test_phase39_receipt_center_opens_approval_archive(
    qt_app: QApplication, tmp_path: Path
) -> None:
    service, _, _, _ = _setup(tmp_path)
    dialog = GenerationLaunchReceiptDialog(
        service,
        project_name="Phase 39 Project",
    )
    dialog.show()
    qt_app.processEvents()
    dialog.table.selectRow(0)
    qt_app.processEvents()

    child = dialog.open_guard_approvals()
    qt_app.processEvents()

    assert child is not None
    assert child in dialog.guard_approval_dialogs
    assert "Guard exceptions" in dialog.guard_approval_label.text()
    _dispose_dialog(qt_app, child)
    _dispose_dialog(qt_app, dialog)
