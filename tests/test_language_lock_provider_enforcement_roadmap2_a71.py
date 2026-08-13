from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.generation_confirmation_service import GenerationConfirmationCoordinator
from app.services.language_assurance_service import LanguageAssuranceService
from app.services.preflight_service import PreflightService


def _job(row: int = 1, *, language: str | None = None) -> TTSJob:
    return TTSJob(
        row_number=row,
        text="10",
        filename=f"{row}.wav",
        language_override=language,
    )


def test_a71_user_language_is_authoritative_and_provider_token_only_changes_syntax() -> None:
    service = LanguageAssuranceService()
    settings = AppSettings(
        provider="cartesia",
        language_code="da-DK",
        model_id="sonic-3.5",
        voice_id="voice",
    )

    resolved = service.settings_for_job(_job(), settings)

    assert settings.language_code == "da-DK"
    assert resolved.language_code == "da"
    assert resolved.provider == "cartesia"
    assert resolved.model_id == "sonic-3.5"
    assert resolved.voice_id == "voice"


def test_a71_explicit_job_language_override_wins_without_mutating_project_settings() -> None:
    service = LanguageAssuranceService()
    settings = AppSettings(
        provider="cartesia",
        language_code="en-US",
        model_id="sonic-3.5",
        voice_id="voice",
    )

    resolved = service.settings_for_job(_job(language="da-DK"), settings)

    assert resolved.language_code == "da"
    assert settings.language_code == "en-US"


def test_a71_cartesia_danish_is_strong_explicit_enforcement() -> None:
    decision = LanguageAssuranceService().assess(
        AppSettings(
            provider="cartesia",
            language_code="da-DK",
            model_id="sonic-3.5",
            voice_id="voice",
        ),
        "da-DK",
    )

    assert decision.blocking is False
    assert decision.assurance_level == "strong"
    assert decision.enforcement_mode == "explicit_parameter"
    assert decision.provider_language == "da"


def test_a71_elevenlabs_multilingual_v2_is_not_falsely_certified_as_hard_lock() -> None:
    decision = LanguageAssuranceService().assess(
        AppSettings(
            provider="elevenlabs",
            language_code="da",
            model_id="eleven_multilingual_v2",
            voice_id="voice",
        ),
        "da",
    )

    assert decision.blocking is False
    assert decision.assurance_level == "best_effort"
    assert decision.requires_acknowledgement is True
    assert decision.code == "language_lock_model_limited"


def test_a71_openai_modern_generation_settings_add_language_instruction_without_translation() -> None:
    service = LanguageAssuranceService()
    settings = AppSettings(
        provider="openai",
        language_code="da-DK",
        model_id="gpt-4o-mini-tts",
        voice_id="alloy",
        provider_options={"instructions": "Speak calmly."},
    )

    resolved = service.settings_for_job(_job(), settings)
    instructions = resolved.provider_options["instructions"]

    assert "Speak calmly." in instructions
    assert "da-DK pronunciation" in instructions
    assert "Do not translate" in instructions
    assert settings.provider_options == {"instructions": "Speak calmly."}


def test_a71_openai_legacy_model_is_visible_as_non_enforceable() -> None:
    decision = LanguageAssuranceService().assess(
        AppSettings(
            provider="openai",
            language_code="da-DK",
            model_id="tts-1",
            voice_id="alloy",
        ),
        "da-DK",
    )

    assert decision.assurance_level == "none"
    assert decision.blocking is False
    assert decision.requires_acknowledgement is True


def test_a71_deepgram_language_model_mismatch_blocks() -> None:
    decision = LanguageAssuranceService().assess(
        AppSettings(
            provider="deepgram",
            language_code="da",
            model_id="aura-2-thalia-en",
            voice_id="aura-2-thalia-en",
        ),
        "da",
    )

    assert decision.blocking is True
    assert decision.code == "language_model_mismatch"


def test_a71_azure_locale_coded_voice_mismatch_blocks() -> None:
    decision = LanguageAssuranceService().assess(
        AppSettings(
            provider="azure",
            language_code="da-DK",
            voice_id="en-US-AvaNeural",
        ),
        "da-DK",
    )

    assert decision.blocking is True
    assert decision.code == "language_voice_mismatch"


def test_a71_preflight_cache_becomes_stale_when_job_language_override_changes(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    preflight = PreflightService(runtime)
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)
    job = _job(language="da-DK")
    settings = AppSettings(provider="mock", language_code="en-US")

    state = preflight.run(jobs=[job], settings=settings, output_dir=output)

    assert preflight.current_state(jobs=[job], settings=settings, output_dir=output) is state
    job.language_override = "en-US"
    assert preflight.current_state(jobs=[job], settings=settings, output_dir=output) is None


def test_a71_preflight_persists_machine_readable_language_assurance(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    output = tmp_path / "output"
    output.mkdir(exist_ok=True)

    state = PreflightService(runtime).run(
        jobs=[_job(language="da-DK")],
        settings=AppSettings(provider="mock", language_code="en-US"),
        output_dir=output,
    )

    assert state.language_lock_languages == ("da-DK",)
    assert state.language_assurance_level == "strong"
    assert "da-DK" in state.language_assurance_summary


def test_a71_launch_confirmation_surfaces_language_assurance_and_acknowledges_weak_lock() -> None:
    state = PreflightState(
        total_jobs=1,
        valid_jobs=1,
        blocking_errors=0,
        warnings=0,
        estimated_characters=2,
        estimated_files=1,
        estimated_provider_requests=1,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision="preflight",
        settings_revision="settings",
        language_lock_languages=("da-DK",),
        language_assurance_level="best_effort",
        language_assurance_summary="da-DK · assurance best effort · enforcement instruction",
    )

    confirmation = GenerationConfirmationCoordinator().evaluate(
        state,
        AppSettings(
            provider="openai",
            language_code="da-DK",
            model_id="gpt-4o-mini-tts",
            voice_id="alloy",
        ),
    )

    check = next(item for item in confirmation.checks if item.code == "language_assurance")
    assert check.requires_acknowledgement is True
    assert "language_assurance" in confirmation.required_acknowledgements


def test_a71_worker_applies_job_language_in_both_serial_and_concurrent_paths() -> None:
    source = Path("app/gui/worker.py").read_text(encoding="utf-8")

    assert source.count("self.language_assurance.settings_for_job(job,") == 2
    assert "PronunciationService().prepare_job(job, job_settings)" in source
    assert "provider.synthesize(prepared.provider_text, job_settings)" in source


def test_a71_no_auto_detection_provider_switch_or_hidden_failover() -> None:
    source = Path("app/services/language_assurance_service.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "detect_language",
        "langdetect",
        "setCurrentText",
        "smart_provider_routing",
        "create_provider(",
        "set_active(",
    )
    for token in forbidden:
        assert token not in source


def test_a71_database_schema_23_is_preserved(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "a71-schema.db")
    database.initialize()

    assert database.expected_schema_version == 23
    assert database.applied_schema_versions()[-1] == 23


def test_a71_files_have_single_final_newline() -> None:
    paths = (
        Path("app/models/language_assurance.py"),
        Path("app/services/language_assurance_service.py"),
        Path("app/models/preflight_state.py"),
        Path("app/services/preflight_service.py"),
        Path("app/services/generation_confirmation_service.py"),
        Path("app/gui/worker.py"),
        Path("docs/LANGUAGE_LOCK_PROVIDER_ENFORCEMENT_ROADMAP2_A71.md"),
        Path(__file__),
    )

    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
