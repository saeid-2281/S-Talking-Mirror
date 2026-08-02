from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.preflight_dialog import PreflightDialog
from app.gui.widgets.batch_plan_summary import BatchPlanSummary
from app.models import AppSettings, TTSJob
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightState
from app.services.generation_planning_service import GenerationPlanningService
from app.services.preflight_service import PreflightService


class FakeCostService:
    def __init__(self, *, rate: float = 100.0, max_queue_cost: float = 0.0, duration: float = 120.0) -> None:
        self.rate = rate
        self.max_queue_cost = max_queue_cost
        self.duration = duration

    def estimate_cost(self, *, project_id, provider, model, characters, retry_characters=0):  # noqa: ANN001
        billable = max(0, int(characters)) + max(0, int(retry_characters))
        return billable / 1_000_000 * self.rate, self.rate, "USD", "test-rate"

    def get_policy(self, project_id):  # noqa: ANN001
        return SimpleNamespace(max_queue_cost=self.max_queue_cost)

    def capacity_forecast(self, *, project_id, provider, model, queued_jobs, queued_characters):  # noqa: ANN001
        return SimpleNamespace(
            estimated_duration_seconds=self.duration,
            estimated_completion_at="2026-08-02T12:02:00+00:00",
            confidence="high",
            limiting_factor="characters",
            historical_session_count=6,
        )


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
            GenerationPlanScenario("expected", "Expected retries", 20, 10, 12_000, 12, 1.2, 144.0),
            GenerationPlanScenario("stress", "Stress test", 25, 10, 12_500, 12, 1.25, 150.0),
        ),
    )
    values.update(overrides)
    return BatchGenerationPlan(**values)


def test_phase34_planning_scenarios_are_deterministic() -> None:
    service = GenerationPlanningService(
        FakeCostService(),
        now_factory=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )

    plan = service.build(
        project_id=7,
        provider="elevenlabs",
        model="model-a",
        files=10,
        characters=10_000,
        provider_requests=10,
        fallback_duration_seconds=30,
        quota_snapshot={"remaining": 20_000},
        max_retries=4,
        delay_seconds=0.5,
    )

    assert [item.retry_reserve_percent for item in plan.scenarios] == [0, 20, 25]
    assert [item.characters for item in plan.scenarios] == [10_000, 12_000, 12_500]
    assert plan.scenarios[1].estimated_cost == pytest.approx(1.2)
    assert plan.estimated_duration_seconds == pytest.approx(124.5)
    assert plan.throughput_confidence == "high"


def test_phase34_quota_shortfall_is_high_risk() -> None:
    service = GenerationPlanningService(FakeCostService())
    plan = service.build(
        project_id=None,
        provider="elevenlabs",
        model="model-a",
        files=5,
        characters=10_000,
        provider_requests=5,
        fallback_duration_seconds=15,
        quota_snapshot={"remaining": 4_000},
        max_retries=2,
        delay_seconds=0,
    )

    assert plan.risk_level == "high"
    assert plan.quota_shortfall == 6_000
    assert any("short by 6,000" in reason for reason in plan.reasons)


def test_phase34_queue_budget_limit_is_reported() -> None:
    service = GenerationPlanningService(FakeCostService(rate=200.0, max_queue_cost=1.0))
    plan = service.build(
        project_id=3,
        provider="openai",
        model="tts-1",
        files=10,
        characters=10_000,
        provider_requests=10,
        fallback_duration_seconds=30,
        quota_snapshot=None,
        max_retries=0,
        delay_seconds=0,
    )

    assert plan.estimated_cost == pytest.approx(2.0)
    assert plan.budget_usage_percent == pytest.approx(200.0)
    assert plan.risk_level == "high"


def test_phase34_preflight_attaches_plan_and_reports_scenarios(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path / "runtime")
    runtime.ensure_directories()
    output = tmp_path / "output"
    output.mkdir()
    preflight = PreflightService(runtime, cost_capacity_service=FakeCostService())

    state = preflight.run(
        jobs=[TTSJob(row_number=1, filename="one.wav", text="x" * 10_000)],
        settings=AppSettings(
            provider="mock",
            model_id="model-a",
            voice_id="mock",
            file_extension=".wav",
            max_retries=4,
            delay_seconds=0,
        ),
        output_dir=output,
        project_id=1,
    )

    assert state.generation_plan is not None
    assert state.estimated_cost == pytest.approx(1.0)
    assert "## Planning scenarios" in preflight.markdown(state)
    assert "Expected retries" in preflight.html(state)


def test_phase34_preflight_json_serializes_nested_plan(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path / "runtime")
    runtime.ensure_directories()
    preflight = PreflightService(runtime)
    state = PreflightState(total_jobs=1, generation_plan=_plan())

    payload = preflight._state_json(state)
    encoded = json.dumps(payload)

    assert payload["generation_plan"]["risk_level"] == "low"
    assert payload["generation_plan"]["scenarios"][1]["retry_reserve_percent"] == 20
    assert "Expected retries" in encoded


def test_phase34_plan_summary_renders_metrics_and_scenarios(qt_app) -> None:
    widget = BatchPlanSummary()
    widget.show()
    widget.set_plan(_plan())
    qt_app.processEvents()

    assert widget.scope_card.value_label.text() == "10 files"
    assert "USD 1.0000" in widget.cost_card.value_label.text()
    assert widget.quota_card.property("tone") == "success"
    assert widget.scenario_table.rowCount() == 3
    assert widget.scenario_table.item(1, 0).text() == "Expected retries"
    widget.close()


def test_phase34_plan_summary_exposes_high_risk_visually(qt_app) -> None:
    widget = BatchPlanSummary()
    widget.set_plan(
        _plan(
            risk_level="high",
            quota_remaining=4_000,
            quota_shortfall=6_000,
            quota_usage_percent=250.0,
            reasons=("Quota is short by 6,000 characters.",),
        )
    )

    assert widget.risk_card.property("tone") == "error"
    assert widget.quota_card.property("tone") == "error"
    assert "6,000" in widget.reason_label.text()


def test_phase34_preflight_dialog_includes_batch_plan_section(qt_app) -> None:
    state = PreflightState(
        total_jobs=10,
        valid_jobs=10,
        estimated_files=10,
        estimated_characters=10_000,
        estimated_provider_requests=10,
        estimated_duration_seconds=120,
        estimated_cost=1.0,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        generation_plan=_plan(),
    )
    dialog = PreflightDialog(
        state,
        export_report=lambda: Path("report"),
        open_output_folder=lambda: None,
        apply_fixes=lambda: None,
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.plan_summary.objectName() == "batchPlanSummary"
    assert dialog.plan_summary.scenario_table.rowCount() == 3
    assert "USD 1.0000" in dialog.summary.text()
    assert dialog.start_button.isEnabled() is True
    dialog.close()
