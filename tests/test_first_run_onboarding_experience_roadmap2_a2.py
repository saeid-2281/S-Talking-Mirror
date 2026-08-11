from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.runtime import RuntimeConfig
from app.release import SCHEMA_VERSION
from app.services.first_run_onboarding_service import FirstRunOnboardingService


def _runtime(tmp_path: Path) -> RuntimeConfig:
    data = tmp_path / "data"
    return RuntimeConfig(
        app_root=tmp_path,
        data_dir=data,
        database_path=data / "s_talking.db",
        legacy_database_path=data / "s-talking.db",
        settings_path=data / "settings.json",
        reports_dir=tmp_path / "reports",
        artifacts_dir=tmp_path / "artifacts",
        log_dir=tmp_path / "logs",
        cache_dir=tmp_path / "cache",
        default_output_dir=tmp_path / "outputs",
    )


def _service(tmp_path: Path) -> FirstRunOnboardingService:
    return FirstRunOnboardingService(
        _runtime(tmp_path),
        now=lambda: datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
    )


def test_a2_does_not_change_database_schema() -> None:
    assert SCHEMA_VERSION == 23


def test_a2_defines_six_ordered_first_run_steps(tmp_path: Path) -> None:
    service = _service(tmp_path)
    assert service.step_ids() == (
        "workspace_orientation",
        "provider_readiness",
        "voice_model_choice",
        "project_sources",
        "preflight_approval",
        "generation_output",
    )
    assert all(step.required for step in service.steps())


def test_a2_missing_state_is_side_effect_free(tmp_path: Path) -> None:
    service = _service(tmp_path)
    state = service.load_state()
    assert state.first_run_completed is False
    assert state.completed_steps == ()
    assert not service.state_path.exists()


def test_a2_mark_reviewed_is_explicit_and_persistent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    state = service.mark_step_complete("provider_readiness")
    assert state.completed_steps == ("provider_readiness",)
    assert service.state_path.exists()
    assert service.load_state().completed_steps == ("provider_readiness",)


def test_a2_marking_step_does_not_auto_complete_onboarding(tmp_path: Path) -> None:
    service = _service(tmp_path)
    for step_id in service.step_ids():
        service.mark_step_complete(step_id)
    state = service.load_state()
    assert service.all_required_steps_complete(state.completed_steps)
    assert state.first_run_completed is False


def test_a2_completion_requires_all_explicit_reviews(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.mark_step_complete("workspace_orientation")
    with pytest.raises(ValueError, match="All required onboarding steps"):
        service.complete_onboarding()


def test_a2_completion_sets_persistent_first_run_completed(tmp_path: Path) -> None:
    service = _service(tmp_path)
    for step_id in service.step_ids():
        service.mark_step_complete(step_id)
    completed = service.complete_onboarding()
    assert completed.first_run_completed is True
    assert completed.completed_at == "2026-08-11T12:00:00Z"
    assert service.should_offer(completed) is False


def test_a2_mark_incomplete_reopens_completed_onboarding(tmp_path: Path) -> None:
    service = _service(tmp_path)
    for step_id in service.step_ids():
        service.mark_step_complete(step_id)
    service.complete_onboarding()
    state = service.mark_step_incomplete("voice_model_choice")
    assert state.first_run_completed is False
    assert "voice_model_choice" not in state.completed_steps


def test_a2_reset_changes_only_onboarding_state(tmp_path: Path) -> None:
    service = _service(tmp_path)
    database_path = service.runtime.database_path
    service.mark_step_complete("workspace_orientation")
    state = service.reset_progress()
    assert state.completed_steps == ()
    assert state.first_run_completed is False
    assert not database_path.exists()


def test_a2_unknown_step_is_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="Unknown onboarding step"):
        service.mark_step_complete("automatic-provider-migration")


def test_a2_corrupt_state_falls_back_without_overwrite(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.state_path.parent.mkdir(parents=True, exist_ok=True)
    service.state_path.write_text("{broken", encoding="utf-8")
    before = service.state_path.read_bytes()
    state = service.load_state()
    assert state.completed_steps == ()
    assert service.state_path.read_bytes() == before


def test_a2_incompatible_state_schema_falls_back_read_only(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"document_schema_version": 999, "first_run_completed": True}
    service.state_path.write_text(json.dumps(payload), encoding="utf-8")
    state = service.load_state()
    assert state.first_run_completed is False
    assert json.loads(service.state_path.read_text(encoding="utf-8"))["document_schema_version"] == 999


def test_a2_safety_contract_keeps_execution_authority_explicit() -> None:
    contract = FirstRunOnboardingService.safety_contract()
    assert contract["automatic_provider_switch"] is False
    assert contract["automatic_account_change"] is False
    assert contract["automatic_catalog_refresh"] is False
    assert contract["automatic_provider_probe"] is False
    assert contract["automatic_preflight_run"] is False
    assert contract["automatic_generation_start"] is False
    assert contract["automatic_generation_restart"] is False
    assert contract["automatic_cross_provider_failover"] is False
    assert contract["automatic_database_write"] is False


def test_a2_service_contains_no_network_or_generation_execution_calls() -> None:
    source = Path("app/services/first_run_onboarding_service.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import httpx" not in source
    assert "urllib.request" not in source
    assert ".synthesize(" not in source
    assert ".refresh(" not in source
    assert ".start(" not in source


def test_a2_service_is_wired_into_container_and_application_context() -> None:
    container = Path("app/container.py").read_text(encoding="utf-8")
    bootstrap = Path("app/bootstrap.py").read_text(encoding="utf-8")
    assert "first_run_onboarding_service: FirstRunOnboardingService" in container
    assert "first_run_onboarding_service = FirstRunOnboardingService(config)" in container
    assert "first_run_onboarding_service: FirstRunOnboardingService" in bootstrap
    assert "first_run_onboarding_service=services.first_run_onboarding_service" in bootstrap


def test_a2_main_window_exposes_persistent_getting_started_surface() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "self.first_run_completed=" in source
    assert "Getting Started / First-run Onboarding" in source
    assert "firstRunOnboardingStatusButton" in source
    assert "def open_first_run_onboarding" in source
    assert "def refresh_first_run_onboarding_status" in source


def test_a2_onboarding_is_available_from_command_palette() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "Help: Getting Started / First-run Onboarding" in source


def test_a2_dialog_does_not_execute_guided_actions_on_open() -> None:
    source = Path("app/gui/dialogs/first_run_onboarding_dialog.py").read_text(encoding="utf-8")
    init_body = source.split("def __init__", 1)[1].split("def _build", 1)[0]
    assert "open_selected_tool" not in init_body
    assert "mark_step_complete" not in init_body
    assert "complete_onboarding" not in init_body
    assert "self.refresh_view()" in init_body


def test_a2_guided_actions_are_existing_ui_handoffs_only() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def open_first_run_onboarding", 1)[1].split("def open_quick_setup", 1)[0]
    assert "self.open_provider_accounts" in method
    assert "self.open_unified_voice_model_catalog" in method
    assert "self.open_project_continuity" in method
    assert "self.focus_generation_workflow" in method
    assert "self.focus_generation_live_operations" in method
    assert "self.start(" not in method
    assert "refresh_provider" not in method


def test_a2_closes_a1_persistent_first_run_state_opportunity() -> None:
    audit = Path("app/services/product_ux_audit_service.py").read_text(encoding="utf-8")
    main = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert '"first_run_completed"' in audit
    assert "first_run_completed" in main


def test_a2_preserves_phase112_provider_ga_boundary_source() -> None:
    source = Path("app/services/provider_ga_certification_service.py").read_text(encoding="utf-8")
    assert "automatic_cross_provider_failover" in source
    assert '"human_release_promotion_required": True' in source
    assert "EXPECTED_BUILTIN_PROVIDER_IDS" in source


def test_a2_documentation_declares_a3_as_next_product_phase() -> None:
    docs = Path("docs/FIRST_RUN_ONBOARDING_EXPERIENCE_ROADMAP2_A2.md").read_text(encoding="utf-8")
    assert "A3 — Provider Setup Wizard" in docs
    assert "Database schema remains **23**" in docs
    assert "hidden cross-provider failover" in docs
