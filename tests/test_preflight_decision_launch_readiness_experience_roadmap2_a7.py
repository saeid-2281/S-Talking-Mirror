from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.generation_launch_dialog import GenerationLaunchDialog
from app.gui.dialogs.preflight_dialog import PreflightDialog
from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.preflight_service import PreflightService


def _state() -> PreflightState:
    return PreflightState(
        total_jobs=1,
        valid_jobs=1,
        blocking_errors=0,
        warnings=0,
        estimated_characters=3,
        estimated_files=1,
        estimated_duration_seconds=1.0,
        estimated_provider_requests=1,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="preflight-revision-abcdef",
        settings_revision="settings-revision-123456",
    )


def test_a7_preflight_service_current_state_is_side_effect_free_and_exact(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = PreflightService(runtime)
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    jobs = [TTSJob(row_number=1, text="Hej", filename="hej.wav")]
    settings = AppSettings(provider="mock", language_code="da-DK")

    state = service.run(jobs=jobs, settings=settings, output_dir=output)

    assert service.current_state(jobs=jobs, settings=settings, output_dir=output) is state
    assert service.is_current(jobs=jobs, settings=settings, output_dir=output) is True
    assert service.current_state(
        jobs=jobs,
        settings=settings.model_copy(update={"language_code": "en-US"}),
        output_dir=output,
    ) is None
    assert service.latest is state


def test_a7_confirmation_records_explicit_preflight_and_resolved_language() -> None:
    state = _state()
    settings = AppSettings(
        provider="mock",
        voice_id="voice-da",
        model_id="model-da",
        language_code="da-DK",
    )

    confirmation = GenerationConfirmationCoordinator().evaluate(state, settings)

    preflight = next(item for item in confirmation.checks if item.code == "preflight_snapshot")
    provider = next(item for item in confirmation.checks if item.code == "provider")
    assert "preflight-re" in preflight.detail
    assert "settings-rev" in preflight.detail
    assert "voice-da" in provider.detail
    assert "model-da" in provider.detail
    assert "da-DK" in provider.detail


def test_a7_launch_fingerprint_changes_when_language_changes() -> None:
    coordinator = GenerationConfirmationCoordinator()
    state = _state()

    danish = coordinator.evaluate(
        state,
        AppSettings(provider="mock", voice_id="v", model_id="m", language_code="da-DK"),
    )
    english = coordinator.evaluate(
        state,
        AppSettings(provider="mock", voice_id="v", model_id="m", language_code="en-US"),
    )

    assert danish.fingerprint != english.fingerprint


def test_a7_preflight_dialog_is_review_only(qt_app, tmp_path: Path) -> None:
    dialog = PreflightDialog(
        _state(),
        export_report=lambda: tmp_path,
        open_output_folder=lambda: None,
        apply_fixes=lambda: None,
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.start_button.text() == "Review complete"
    assert "generation is started separately" in dialog.start_button.toolTip().casefold()
    assert dialog.start_button.isEnabled() is True
    dialog.close()


def test_a7_launch_dialog_shows_current_readiness_snapshot(qt_app) -> None:
    state = _state()
    settings = AppSettings(
        provider="mock",
        voice_id="voice-da",
        model_id="model-da",
        language_code="da-DK",
    )
    confirmation = GenerationConfirmationCoordinator().evaluate(state, settings)
    dialog = GenerationLaunchDialog(confirmation, state, settings=settings)
    dialog.show()
    qt_app.processEvents()

    detail = dialog.readiness_card.detail_label.text()
    assert "Preflight revision" in detail
    assert "Decision trace" in detail
    assert "voice-da" in detail
    assert "model-da" in detail
    assert "da-DK" in detail
    assert "read-only" in detail
    assert dialog.start_button.text() == "Start reviewed generation"
    dialog.close()


def test_a7_invalidation_disables_start_until_explicit_preflight() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def invalidate_preflight", 1)[1].split(
        "def current_preflight_state",
        1,
    )[0]

    assert "self.preflight_service.invalidate()" in method
    assert "self.startb.setEnabled(False)" in method
    assert "Preflight required" in method
    assert "run_preflight(" not in method


def test_a7_start_never_runs_preflight_or_quota_refresh_implicitly() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def start(self):", 1)[1].split("def pause", 1)[0]

    assert "state=self.current_preflight_state(s)" in method
    assert "Run Preflight explicitly" in method
    assert "self.run_preflight(" not in method
    assert "self.refresh_quota_snapshot(" not in method
    assert "self.dry_run(" not in method


def test_a7_show_latest_preflight_does_not_silently_run_it() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def show_latest_preflight", 1)[1].split(
        "def export_preflight",
        1,
    )[0]

    assert "self.current_preflight_state()" in method
    assert "Run Preflight explicitly first" in method
    assert "run_preflight(" not in method


def test_a7_visible_launch_review_is_a_separate_final_action() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def review_generation_launch", 1)[1].split(
        "def request_generation_launch_exception",
        1,
    )[0]

    assert "GenerationLaunchDialog" in method
    assert "settings=self.settings()" in method
    headless_pos = method.index("if platform in {'offscreen','minimal'}")
    return_pos = method.index("if not confirmation.requires_user_confirmation: return ()")
    assert return_pos > headless_pos


def test_a7_onboarding_focuses_preflight_without_running_it() -> None:
    from app.services.first_run_onboarding_service import FirstRunOnboardingService

    step = next(
        item
        for item in FirstRunOnboardingService.steps()
        if item.step_id == "preflight_approval"
    )

    assert step.action_id == "preflight_readiness"
    assert step.action_label == "Focus explicit Preflight"
    assert "never runs Preflight or generation" in step.description


def test_a7_onboarding_action_map_uses_focus_only() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def open_first_run_onboarding", 1)[1].split(
        "def open_quick_setup",
        1,
    )[0]

    assert "'preflight_readiness':self.focus_preflight_readiness" in method
    focus = source.split("def focus_preflight_readiness", 1)[1].split(
        "def review_generation_launch",
        1,
    )[0]
    assert "setFocus()" in focus
    assert "run_preflight(" not in focus
    assert "self.start(" not in focus


def test_a7_generation_region_focus_falls_back_to_explicit_preflight_when_start_is_disabled() -> None:
    source = Path("app/gui/main.py").read_text(encoding="utf-8")
    method = source.split("def focus_workspace_region", 1)[1].split(
        "def apply_density",
        1,
    )[0]

    assert "elif region=='generation':" in method
    assert "not target.isEnabled()" in method
    assert "dry_run_button" in method


def test_a7_database_schema_23_is_preserved(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "a7-schema.db")
    database.initialize()

    assert database.expected_schema_version == 23
    assert database.applied_schema_versions()[-1] == 23


def test_a7_files_have_single_final_newline() -> None:
    paths = (
        Path("app/services/preflight_service.py"),
        Path("app/services/generation_confirmation_service.py"),
        Path("app/gui/dialogs/preflight_dialog.py"),
        Path("app/gui/dialogs/generation_launch_dialog.py"),
        Path("app/gui/main.py"),
        Path("app/services/first_run_onboarding_service.py"),
        Path("docs/PREFLIGHT_DECISION_LAUNCH_READINESS_EXPERIENCE_ROADMAP2_A7.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
