from __future__ import annotations

import json
from pathlib import Path

from app.gui.dialogs.generation_launch_dialog import GenerationLaunchDialog
from app.models import AppSettings
from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.models.preflight_state import PreflightIssue, PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator


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


def test_phase35_ready_launch_is_deterministic_and_needs_no_prompt() -> None:
    coordinator = GenerationConfirmationCoordinator()
    settings = AppSettings(provider="elevenlabs", model_id="model-a", voice_id="voice-a")

    first = coordinator.evaluate(_state(), settings)
    second = coordinator.evaluate(_state(), settings)

    assert first.allowed is True
    assert first.status == "ready"
    assert first.requires_user_confirmation is False
    assert first.required_acknowledgements == ()
    assert first.fingerprint == second.fingerprint
    assert any(item.code == "scope" for item in first.checks)


def test_phase35_preflight_warning_preserves_confirmation_contract() -> None:
    state = _state(
        warnings=1,
        issues=[
            PreflightIssue(
                severity="warning",
                row=2,
                filename="two.mp3",
                message="Duplicate text appears in the batch.",
                suggested_action="Confirm this repeated text is intentional.",
                code="duplicate_text",
            )
        ],
    )
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a"),
    )

    assert state.status == "Ready with warnings"
    assert confirmation.allowed is True
    assert confirmation.requires_user_confirmation is True
    assert confirmation.title == "Preflight warnings"
    assert "preflight_warnings" in confirmation.required_acknowledgements


def test_phase35_high_risk_plan_requires_explicit_acknowledgement() -> None:
    state = _state(
        generation_plan=_plan(
            risk_level="high",
            quota_remaining=4_000,
            quota_shortfall=6_000,
            quota_usage_percent=250.0,
            reasons=("Quota is short by 6,000 characters.",),
        )
    )

    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a"),
    )

    risk = next(item for item in confirmation.checks if item.code == "planning_risk")
    assert confirmation.status == "confirmation_required"
    assert risk.tone == "error"
    assert risk.requires_acknowledgement is True
    assert "planning_risk" in confirmation.required_acknowledgements


def test_phase35_existing_outputs_are_explained_by_file_policy() -> None:
    state = _state(existing_outputs=["one.mp3", "two.mp3"])
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a", skip_existing=True),
    )

    output_check = next(item for item in confirmation.checks if item.code == "existing_outputs")
    assert "2 existing output(s) will be skipped" in output_check.detail
    assert output_check.tone == "warning"
    assert output_check.requires_acknowledgement is True


def test_phase35_blocked_preflight_cannot_launch() -> None:
    state = _state(
        blocking_errors=1,
        issues=[
            PreflightIssue(
                severity="hard_error",
                row=1,
                filename="one.mp3",
                message="Text is empty.",
                suggested_action="Enter text.",
                code="empty_text",
            )
        ],
        can_start=False,
    )
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="mock", model_id="mock"),
    )

    assert state.status == "Blocked by errors"
    assert confirmation.allowed is False
    assert confirmation.status == "blocked"
    assert confirmation.title == "Preflight errors"


def test_phase35_launch_receipt_is_secret_free_and_auditable(tmp_path: Path) -> None:
    coordinator = GenerationConfirmationCoordinator()
    state = _state(existing_outputs=[str(tmp_path / "one.mp3")])
    settings = AppSettings(
        provider="elevenlabs",
        api_key="super-secret-api-key",
        model_id="model-a",
        voice_id="voice-a",
        skip_existing=True,
    )
    confirmation = coordinator.evaluate(state, settings)

    receipt = coordinator.write_receipt(
        confirmation,
        state,
        settings,
        reports_dir=tmp_path / "reports",
        project_name="Phase 35 Project",
        output_dir=tmp_path / "output",
        acknowledged_codes=confirmation.required_acknowledgements,
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    encoded = json.dumps(payload)

    assert receipt.name == "generation-launch.json"
    assert payload["launch_fingerprint"] == confirmation.fingerprint
    assert payload["acknowledged_codes"] == sorted(confirmation.required_acknowledgements)
    assert payload["settings"]["provider"] == "elevenlabs"
    assert "super-secret-api-key" not in encoded
    assert receipt.with_name("generation-launch.md").exists()


def test_phase35_launch_dialog_requires_all_acknowledgements(qt_app) -> None:
    state = _state(
        warnings=1,
        existing_outputs=["one.mp3"],
        issues=[
            PreflightIssue(
                severity="warning",
                row=1,
                filename="one.mp3",
                message="Output file already exists.",
                suggested_action="Skip existing output.",
                code="existing_output",
            )
        ],
    )
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a", skip_existing=True),
    )
    dialog = GenerationLaunchDialog(confirmation, state)
    dialog.show()
    qt_app.processEvents()

    assert dialog.start_button.isEnabled() is False
    assert set(dialog.acknowledgement_boxes) == set(confirmation.required_acknowledgements)
    for box in dialog.acknowledgement_boxes.values():
        box.setChecked(True)
    qt_app.processEvents()
    assert dialog.start_button.isEnabled() is True
    assert set(dialog.acknowledged_codes()) == set(confirmation.required_acknowledgements)
    dialog.close()


def test_phase35_launch_dialog_renders_plan_checks_and_outputs(qt_app) -> None:
    state = _state(existing_outputs=["C:/audio/one.mp3", "C:/audio/two.mp3"])
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a", skip_existing=True),
    )
    dialog = GenerationLaunchDialog(confirmation, state)
    dialog.show()
    qt_app.processEvents()

    assert dialog.objectName() == "generationLaunchDialog"
    assert dialog.plan_summary.scenario_table.rowCount() == 3
    assert dialog.check_table.rowCount() == len(confirmation.checks)
    assert dialog.output_table is not None
    assert dialog.output_table.rowCount() == 2
    assert dialog.output_table.item(0, 0).text() == "C:/audio/one.mp3"
    dialog.close()

class _HeadlessNotificationBoundary:
    def __init__(self, accepted: bool) -> None:
        self.accepted = accepted
        self.calls: list[tuple[str, str]] = []

    def confirmation(self, title: str, message: str) -> bool:
        self.calls.append((title, message))
        return self.accepted


class _HeadlessLaunchHost:
    def __init__(self, accepted: bool) -> None:
        self.notifications = _HeadlessNotificationBoundary(accepted)

    def isVisible(self) -> bool:
        return False


def test_phase35_headless_launch_review_uses_notification_boundary(qt_app, monkeypatch) -> None:
    from app.gui import main as main_module

    state = _state(
        warnings=1,
        issues=[
            PreflightIssue(
                severity="warning",
                row=1,
                filename="one.mp3",
                message="Output file already exists.",
                suggested_action="Confirm the file policy.",
                code="existing_output",
            )
        ],
    )
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a"),
    )
    host = _HeadlessLaunchHost(True)

    def fail_if_dialog_is_created(*args, **kwargs):
        raise AssertionError("A modal launch dialog must not open in headless mode.")

    monkeypatch.setattr(main_module, "GenerationLaunchDialog", fail_if_dialog_is_created)
    acknowledged = main_module.MainWindow.review_generation_launch(host, confirmation, state)

    assert acknowledged == confirmation.required_acknowledgements
    assert host.notifications.calls == [(confirmation.title, confirmation.message)]


def test_phase35_headless_launch_review_can_be_cancelled(qt_app) -> None:
    from app.gui.main import MainWindow

    state = _state(existing_outputs=["one.mp3"])
    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(provider="elevenlabs", model_id="model-a", skip_existing=True),
    )
    host = _HeadlessLaunchHost(False)

    assert MainWindow.review_generation_launch(host, confirmation, state) is None
    assert host.notifications.calls == [(confirmation.title, confirmation.message)]

