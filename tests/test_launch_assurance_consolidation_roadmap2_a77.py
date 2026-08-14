from __future__ import annotations

from pathlib import Path

import pytest

from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.launch_assurance_service import (
    LaunchAssuranceContextChanged,
    LaunchAssuranceService,
)
from app.services.preflight_service import PreflightService


ROOT = Path(__file__).resolve().parents[1]


def _job(row: int = 1, **updates) -> TTSJob:
    return TTSJob(
        row_number=row,
        text="Hej verden",
        filename=f"row-{row}.mp3",
        **updates,
    )


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="sk_PRIVATE_TEST_KEY",
        voice_id="voice-a",
        model_id="model-a",
        language_code="da",
        active_api_profile_id="profile-a",
        generation_scope="row_range",
        execution_order="csv",
        pronunciation_dictionary_locators=[
            {"pronunciation_dictionary_id": "dict-a", "version_id": "v1"}
        ],
        active_pronunciation_dictionary_id="dict-a:v1",
    )
    return base.model_copy(update=updates)


def _revision(job: TTSJob | None = None, settings: AppSettings | None = None) -> str:
    service = object.__new__(PreflightService)
    return service.request_revision(
        [job or _job()],
        settings or _settings(),
        Path("output"),
        Path("source.csv"),
        7,
    )


def _state(revision: str = "revision-a", **updates) -> PreflightState:
    state = PreflightState(
        total_jobs=1,
        estimated_files=1,
        estimated_characters=11,
        estimated_provider_requests=1,
        estimated_cost=0.0123,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision=revision,
        quota_snapshot={"remaining_characters": 1000, "catalog_revision": "cat-a"},
        language_lock_languages=("da",),
        language_assurance_level="verified",
        pronunciation_current_review_rows=(1,),
    )
    for key, value in updates.items():
        setattr(state, key, value)
    return state


def test_a77_preflight_revision_covers_explicit_per_job_provider_voice_model_overrides() -> None:
    baseline = _revision()
    for field, value in (
        ("provider_override", "openai"),
        ("voice_override", "voice-b"),
        ("model_override", "model-b"),
        ("language_override", "en"),
        ("pronunciation_override", "original@a74:abcdef"),
    ):
        assert _revision(_job(**{field: value})) != baseline


def test_a77_preflight_revision_covers_provider_account_voice_model_language_and_scope() -> None:
    baseline = _revision()
    variants = (
        _settings(provider="openai"),
        _settings(api_key="sk_OTHER"),
        _settings(active_api_profile_id="profile-b"),
        _settings(voice_id="voice-b"),
        _settings(model_id="model-b"),
        _settings(language_code="en"),
        _settings(generation_scope="selected"),
        _settings(execution_order="filename_asc"),
        _settings(active_pronunciation_dictionary_id="dict-a:v2"),
    )
    for settings in variants:
        assert _revision(settings=settings) != baseline


def test_a77_preflight_revision_covers_output_source_and_project_identity() -> None:
    service = object.__new__(PreflightService)
    jobs = [_job()]
    settings = _settings()
    baseline = service.request_revision(jobs, settings, Path("output"), Path("source.csv"), 7)
    assert service.request_revision(jobs, settings, Path("other-output"), Path("source.csv"), 7) != baseline
    assert service.request_revision(jobs, settings, Path("output"), Path("other.csv"), 7) != baseline
    assert service.request_revision(jobs, settings, Path("output"), Path("source.csv"), 8) != baseline


def test_a77_launch_and_generation_checkpoints_verify_same_revision() -> None:
    service = LaunchAssuranceService()
    state = _state()
    launch = service.verify_launch(state, "revision-a")
    assert launch.launch_matches_preflight is True
    assert launch.fully_verified is False
    generation = service.verify_generation(launch, state, "revision-a")
    assert generation.generation_matches_launch is True
    assert generation.fully_verified is True
    assert generation.preflight_revision == generation.launch_revision == generation.generation_revision


def test_a77_launch_checkpoint_fails_closed_when_request_changed_after_preflight() -> None:
    with pytest.raises(LaunchAssuranceContextChanged, match="changed after Preflight"):
        LaunchAssuranceService().verify_launch(_state(), "revision-b")


def test_a77_generation_checkpoint_fails_closed_when_request_changed_after_launch_review() -> None:
    service = LaunchAssuranceService()
    state = _state()
    launch = service.verify_launch(state, "revision-a")
    with pytest.raises(LaunchAssuranceContextChanged, match="changed after launch review"):
        service.verify_generation(launch, state, "revision-b")


def test_a77_generation_checkpoint_detects_changed_preflight_planning_evidence() -> None:
    service = LaunchAssuranceService()
    state = _state()
    launch = service.verify_launch(state, "revision-a")
    state.estimated_cost = 0.999
    with pytest.raises(LaunchAssuranceContextChanged, match="evidence changed"):
        service.verify_generation(launch, state, "revision-a")


def test_a77_service_has_no_provider_preflight_generation_or_routing_authority() -> None:
    source = (ROOT / "app/services/launch_assurance_service.py").read_text(encoding="utf-8")
    for forbidden in (
        "create_provider(",
        ".synthesize(",
        ".run_preflight(",
        "generation_controller.start",
        "provider.setCurrentText",
        "voice.setText",
        "set_model_value",
        "set_language_value",
        "detect_language",
        "smart_provider_routing",
    ):
        assert forbidden not in source


def test_a77_main_checks_context_before_launch_review_and_immediately_before_generation() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def start(self):")
    end = source.index("    def sync_execution_session", start)
    block = source[start:end]
    assert block.count("launch_assurance_service.verify_launch(") >= 3
    assert "launch_assurance_service.verify_generation(" in block
    assert block.index("launch_assurance_service.verify_generation(") < block.index("generation_controller.start(")
    assert "Preflight == Launch == Generation" in block


def test_a77_context_change_invalidates_preflight_without_automatic_rerun() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("    def reject_launch_context_change")
    end = source.index("    def current_preflight_state", start)
    block = source[start:end]
    assert "invalidate_preflight()" in block
    assert "Run Preflight explicitly again" in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block


def test_a77_preflight_and_launch_use_one_public_request_revision_function() -> None:
    preflight = (ROOT / "app/services/preflight_service.py").read_text(encoding="utf-8")
    main = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    assert "def request_revision(" in preflight
    assert "revision = self.request_revision(" in preflight
    assert "self.preflight_service.request_revision(" in main


def test_a77_generation_mismatch_releases_budget_and_cancels_session_before_start() -> None:
    source = (ROOT / "app/gui/main.py").read_text(encoding="utf-8")
    start = source.index("        try:\n            launch_assurance=self.launch_assurance_service.verify_generation(")
    end = source.index("        if not self.generation_controller.start", start)
    block = source[start:end]
    assert "release_reservation" in block
    assert "reason='launch_context_changed'" in block
    assert "finish_execution_session('cancelled')" in block
    assert "reject_launch_context_change(exc)" in block


def test_a77_document_preserves_authority_schema_and_fixed_next_step() -> None:
    text = (ROOT / "docs/LAUNCH_ASSURANCE_CONSOLIDATION_ROADMAP2_A77.md").read_text(encoding="utf-8")
    assert "Preflight Context == Launch Context == Generation Context" in text
    assert "never silently reruns Preflight" in text
    assert "Database schema 23 is unchanged" in text
    assert "A7.8 — Track A End-to-End Product Acceptance" in text


def test_a77_checked_dimensions_include_quota_cost_pronunciation_and_output() -> None:
    dimensions = " ".join(LaunchAssuranceService.CHECKED_DIMENSIONS).casefold()
    for term in ("quota", "cost", "pronunciation", "output", "provider", "voice", "model", "language"):
        assert term in dimensions


def test_a77_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/launch_assurance.py"),
        Path("app/services/launch_assurance_service.py"),
        Path("app/services/preflight_service.py"),
        Path("app/gui/main.py"),
        Path("docs/LAUNCH_ASSURANCE_CONSOLIDATION_ROADMAP2_A77.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
