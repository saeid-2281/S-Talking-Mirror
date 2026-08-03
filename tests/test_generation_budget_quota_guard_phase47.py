from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QTableWidget

from app.gui.dialogs.generation_budget_guard_dialog import GenerationBudgetGuardDialog
from app.models import AppSettings
from app.models.generation_cost_capacity import (
    GenerationCostBudgetPolicy,
    GenerationCostCapacityDashboard,
    GenerationCostCapacitySnapshot,
)
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_budget_guard_service import GenerationBudgetGuardService
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class _CostService:
    def __init__(
        self,
        *,
        policy: GenerationCostBudgetPolicy,
        daily_spend: float = 0.0,
        weekly_spend: float = 0.0,
        monthly_spend: float = 0.0,
    ) -> None:
        self.policy = policy
        self.daily_spend = daily_spend
        self.weekly_spend = weekly_spend
        self.monthly_spend = monthly_spend

    def dashboard(self, **_kwargs) -> GenerationCostCapacityDashboard:
        now = "2026-08-03T12:00:00+00:00"
        return GenerationCostCapacityDashboard(
            policy=self.policy,
            snapshot=GenerationCostCapacitySnapshot(
                snapshot_id="snapshot",
                project_id=self.policy.project_id,
                period_start=now,
                period_end=now,
                created_at=now,
                currency=self.policy.currency,
                daily_spend=self.daily_spend,
                weekly_spend=self.weekly_spend,
                monthly_spend=self.monthly_spend,
            ),
        )


def _service(
    tmp_path: Path,
    *,
    daily_budget: float = 10.0,
    weekly_budget: float = 50.0,
    monthly_budget: float = 100.0,
    max_queue_cost: float = 20.0,
    warning_percent: float = 80.0,
    daily_spend: float = 0.0,
) -> GenerationBudgetGuardService:
    policy = GenerationCostBudgetPolicy(
        project_id=1,
        enabled=True,
        currency="USD",
        daily_budget=daily_budget,
        weekly_budget=weekly_budget,
        monthly_budget=monthly_budget,
        max_queue_cost=max_queue_cost,
        warning_percent=warning_percent,
        updated_at="policy-v1",
    )
    return GenerationBudgetGuardService(
        tmp_path,
        _CostService(policy=policy, daily_spend=daily_spend),
        now_factory=lambda: datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc),
    )


def _evaluate(
    service: GenerationBudgetGuardService,
    *,
    cost: float = 1.0,
    characters: int = 1_000,
    quota: int | None = 10_000,
    fingerprint: str = "launch-a",
):
    return service.evaluate(
        project_id=1,
        project_name="Alpha",
        provider="elevenlabs",
        model_id="turbo",
        estimated_cost=cost,
        currency="USD",
        required_characters=characters,
        quota_remaining=quota,
        launch_fingerprint=fingerprint,
    )


def _plan(**overrides) -> BatchGenerationPlan:
    values = dict(
        provider="elevenlabs",
        model="turbo",
        files=2,
        characters=1_000,
        provider_requests=2,
        estimated_cost=1.0,
        currency="USD",
        price_per_million_characters=1000.0,
        pricing_source="test",
        estimated_duration_seconds=20.0,
        estimated_completion_at="2026-08-03T12:00:20+00:00",
        throughput_confidence="high",
        limiting_factor="characters",
        historical_session_count=5,
        quota_remaining=10_000,
        quota_shortfall=0,
        quota_usage_percent=10.0,
        max_queue_cost=20.0,
        budget_usage_percent=10.0,
        risk_level="low",
        reasons=("Within configured limits.",),
        scenarios=(
            GenerationPlanScenario("base", "Base", 0, 2, 1_000, 2, 1.0, 20.0),
            GenerationPlanScenario("expected", "Expected", 20, 2, 1_200, 3, 1.2, 24.0),
        ),
    )
    values.update(overrides)
    return BatchGenerationPlan(**values)


def _state(**overrides) -> PreflightState:
    values = dict(
        total_jobs=2,
        valid_jobs=2,
        estimated_files=2,
        estimated_characters=1_000,
        estimated_provider_requests=2,
        estimated_duration_seconds=20.0,
        estimated_cost=1.0,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="preflight",
        settings_revision="settings",
        generation_plan=_plan(),
    )
    values.update(overrides)
    return PreflightState(**values)


def test_budget_guard_ready_when_cost_and_quota_are_available(tmp_path: Path) -> None:
    decision = _evaluate(_service(tmp_path))

    assert decision.status == "ready"
    assert decision.allowed is True
    assert decision.quota_shortfall == 0
    assert decision.projected_daily_spend == 1.0
    assert decision.requires_acknowledgement is False


def test_budget_guard_warns_near_limit_and_for_unknown_quota(tmp_path: Path) -> None:
    decision = _evaluate(_service(tmp_path, daily_spend=7.5), cost=1.0, quota=None)

    assert decision.status == "warning"
    assert decision.allowed is True
    assert decision.requires_acknowledgement is True
    assert "daily_budget_warning" in decision.warning_codes
    assert "quota_unknown" in decision.warning_codes


def test_hard_budget_limit_requires_exact_exception_approval(tmp_path: Path) -> None:
    service = _service(tmp_path, daily_spend=9.5)
    blocked = _evaluate(service, cost=1.0)

    assert blocked.status == "budget_blocked"
    assert blocked.allowed is False
    approval = service.create_approval(
        project_name="Alpha",
        decision_fingerprint=blocked.fingerprint,
        approved_by="Operator",
        reason="Urgent approved production batch",
        duration_minutes=60,
    )
    approved = _evaluate(service, cost=1.0)
    other = _evaluate(service, cost=1.1, fingerprint="launch-b")

    assert approved.status == "approved_exception"
    assert approved.approval_id == approval.approval_id
    assert approved.requires_acknowledgement is True
    assert other.status == "budget_blocked"


def test_provider_quota_shortfall_cannot_be_overridden_by_budget_approval(tmp_path: Path) -> None:
    service = _service(tmp_path)
    blocked = _evaluate(service, characters=12_000, quota=10_000)
    service.create_approval(
        project_name="Alpha",
        decision_fingerprint=blocked.fingerprint,
        approved_by="Operator",
        reason="Budget exception does not change provider quota",
    )
    repeated = _evaluate(service, characters=12_000, quota=10_000)

    assert blocked.status == "quota_blocked"
    assert repeated.status == "quota_blocked"
    assert repeated.allowed is False
    assert repeated.quota_shortfall == 2_000


def test_reservations_are_counted_and_settled_without_double_spend(tmp_path: Path) -> None:
    service = _service(tmp_path)
    first = _evaluate(service, cost=2.0, characters=2_000)
    reservation = service.reserve(first, run_id="run-1", launch_fingerprint="launch-a")
    second = _evaluate(service, cost=1.0, characters=1_000, fingerprint="launch-b")
    settled = service.settle_reservation(
        reservation.reservation_id,
        actual_cost=2.25,
        execution_receipt_id="execution-1",
    )

    assert second.active_reserved_cost == 2.0
    assert second.active_reserved_characters == 2_000
    assert settled.status == "settled"
    assert settled.actual_cost == 2.25
    assert service.summary(project_name="Alpha").active_reservations == 0


def test_confirmation_and_launch_receipt_record_budget_guard_metadata(tmp_path: Path) -> None:
    budget_service = _service(tmp_path)
    coordinator = GenerationConfirmationCoordinator()
    settings = AppSettings(provider="elevenlabs", model_id="turbo", voice_id="voice")
    confirmation = coordinator.evaluate(
        _state(),
        settings,
        budget_guard_service=budget_service,
        project_name="Alpha",
        project_id=1,
        output_dir=tmp_path / "output",
    )
    reservation = budget_service.reserve(
        confirmation.budget_guard_decision,
        run_id="run-1",
        launch_fingerprint=confirmation.fingerprint,
    )
    from dataclasses import replace

    confirmation = replace(confirmation, budget_reservation_id=reservation.reservation_id)
    receipt_path = coordinator.write_receipt(
        confirmation,
        _state(),
        settings,
        reports_dir=tmp_path,
        project_name="Alpha",
        output_dir=tmp_path / "output",
        run_id="run-1",
    )
    receipt = GenerationLaunchReceiptService(tmp_path).load(receipt_path)

    assert receipt.budget_guard_status == "ready"
    assert receipt.budget_reservation_id == reservation.reservation_id
    assert receipt.budget_projected_daily_spend == 1.0
    assert receipt.integrity_status == "verified"


def test_export_is_secret_free_and_approval_consumption_is_audited(tmp_path: Path) -> None:
    service = _service(tmp_path, daily_spend=9.5)
    blocked = _evaluate(service)
    approval = service.create_approval(
        project_name="Alpha",
        decision_fingerprint=blocked.fingerprint,
        approved_by="Operator",
        reason="Urgent run api_key=sk_hidden must proceed",
    )
    consumed = service.consume_approval(approval.approval_id, receipt_id="launch-1")
    exported = service.export(tmp_path / "exports", project_name="Alpha")
    combined = exported.json_path.read_text(encoding="utf-8") + exported.csv_path.read_text(
        encoding="utf-8-sig"
    )

    assert consumed.status == "consumed"
    assert "[REDACTED]" in combined
    assert "sk_hidden" not in combined
    assert "api_key" not in combined.casefold()


def test_budget_guard_dialog_is_scroll_safe_and_releases_qt_widgets(qt_app, tmp_path: Path) -> None:
    service = _service(tmp_path)
    decision = _evaluate(service)
    service.reserve(decision, run_id="run-1", launch_fingerprint="launch-a")
    dialog = GenerationBudgetGuardDialog(service, "Alpha", export_dir=tmp_path / "exports")

    assert dialog.objectName() == "generationBudgetGuardDialog"
    assert dialog.minimumWidth() >= 780
    assert isinstance(dialog.reservation_table, QTableWidget)
    assert dialog.reservation_table.rowCount() == 1
    assert dialog.approval_table.rowCount() == 0
    assert dialog.export_records().json_path.is_file()

    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
