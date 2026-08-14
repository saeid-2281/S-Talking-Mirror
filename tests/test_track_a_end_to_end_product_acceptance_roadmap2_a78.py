from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.preflight_state import PreflightState
from app.services.launch_assurance_service import LaunchAssuranceService
from app.services.preflight_service import PreflightService


ROOT = Path(__file__).resolve().parents[1]


def _settings(**updates) -> AppSettings:
    base = AppSettings(
        provider="elevenlabs",
        api_key="sk_PRIVATE_ACCEPTANCE_KEY",
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


def _job(row: int, **updates) -> TTSJob:
    return TTSJob(
        row_number=row,
        text=f"Acceptancetekst {row}",
        filename=f"a78-{row:04d}.mp3",
        **updates,
    )


def _revision(jobs: list[TTSJob], settings: AppSettings | None = None) -> str:
    service = object.__new__(PreflightService)
    return service.request_revision(
        jobs,
        settings or _settings(),
        Path("output"),
        Path("source.csv"),
        78,
    )


def test_a78_large_batch_4001_revision_is_deterministic_and_non_mutating() -> None:
    jobs = [_job(row) for row in range(1, 4002)]
    before = [job.model_dump() for job in jobs]
    first = _revision(jobs)
    second = _revision(jobs)
    after = [job.model_dump() for job in jobs]
    assert first == second
    assert before == after
    changed = list(jobs)
    changed[-1] = changed[-1].model_copy(update={"voice_override": "voice-last"})
    assert _revision(changed) != first


def test_a78_explicit_mixed_language_overrides_are_revision_authoritative() -> None:
    jobs = [
        _job(1, language_override="da"),
        _job(2, language_override="en"),
        _job(3, language_override="de"),
    ]
    baseline = _revision(jobs)
    assert baseline == _revision(jobs)
    changed = list(jobs)
    changed[1] = changed[1].model_copy(update={"language_override": "sv"})
    assert _revision(changed) != baseline


def test_a78_cloud_and_local_provider_contexts_remain_explicitly_distinct() -> None:
    jobs = [_job(1)]
    revisions = {
        provider: _revision(jobs, _settings(provider=provider, active_api_profile_id=f"{provider}-profile"))
        for provider in ("elevenlabs", "openai", "piper")
    }
    assert len(set(revisions.values())) == 3


def test_a78_launch_assurance_accepts_same_large_batch_evidence_across_all_checkpoints() -> None:
    revision = _revision([_job(1), _job(2, language_override="en")])
    state = PreflightState(
        total_jobs=4001,
        estimated_files=4001,
        estimated_characters=64000,
        estimated_provider_requests=4001,
        estimated_cost=12.34,
        provider_ready=True,
        output_directory_ready=True,
        can_start=True,
        revision=revision,
        quota_snapshot={"remaining_characters": 100000, "catalog_revision": "a78"},
        language_lock_languages=("da", "en"),
        language_assurance_level="verified",
        pronunciation_current_review_rows=(1, 2),
    )
    service = LaunchAssuranceService()
    launch = service.verify_launch(state, revision)
    generation = service.verify_generation(launch, state, revision)
    assert generation.fully_verified is True
    assert generation.preflight_revision == generation.launch_revision == generation.generation_revision


def test_a78_acceptance_operations_do_not_mutate_source_jobs() -> None:
    jobs = [_job(1, pronunciation_override="original@a74:abcdef"), _job(2)]
    snapshot = deepcopy([job.model_dump() for job in jobs])
    _ = _revision(jobs)
    assert [job.model_dump() for job in jobs] == snapshot


def test_a78_preflight_revision_has_no_content_based_language_detection_authority() -> None:
    source = (ROOT / "app/services/preflight_service.py").read_text(encoding="utf-8")

    request_start = source.index("    def request_revision(")
    request_end = source.find("\n    def ", request_start + 5)
    request_block = source[request_start:] if request_end < 0 else source[request_start:request_end]

    key_start = source.index("    def _key(")
    key_end = source.find("\n    def ", key_start + 5)
    key_block = source[key_start:] if key_end < 0 else source[key_start:key_end]

    combined = f"{key_block}\n{request_block}"
    for forbidden in ("detect_language(", "language_detector", "guess_language("):
        assert forbidden not in combined

    assert "job.language_override" in key_block
    assert "payload = self._key" in request_block


def test_a78_acceptance_harness_covers_all_required_real_world_lanes() -> None:
    script = (ROOT / "scripts/track-a-product-acceptance.ps1").read_text(encoding="utf-8")
    required_labels = (
        "First-run / provider / voice-model",
        "Text-source / queue / batch preparation",
        "Pronunciation / Preflight / launch assurance",
        "Generation lifecycle / pause-resume-stop / recovery",
        "Audio output / review / export",
        "Cloud-local provider matrix / Danish authority",
        "4001-row / mixed-language acceptance",
        "QProcess / release compatibility",
    )
    for label in required_labels:
        assert label in script
    assert "--junitxml" in script
    normalized = script.replace("\\", "/")
    assert "artifacts/track-a-product-acceptance" in normalized
    assert "latest.json" in normalized


def test_a78_harness_requires_a2_through_a77_contract_tests() -> None:
    script = (ROOT / "scripts/track-a-product-acceptance.ps1").read_text(encoding="utf-8")
    required = (
        "test_first_run_onboarding_experience_roadmap2_a2.py",
        "test_provider_setup_wizard_roadmap2_a3.py",
        "test_voice_model_discovery_selection_ux_roadmap2_a4.py",
        "test_preflight_decision_launch_readiness_experience_roadmap2_a7.py",
        "test_language_lock_provider_enforcement_roadmap2_a71.py",
        "test_short_utterance_pronunciation_hardening_roadmap2_a72.py",
        "test_pronunciation_review_workspace_roadmap2_a73.py",
        "test_pronunciation_decision_freshness_revalidation_roadmap2_a74.py",
        "test_pronunciation_decision_audit_trail_evidence_roadmap2_a75.py",
        "test_pronunciation_coverage_project_readiness_roadmap2_a76.py",
        "test_launch_assurance_consolidation_roadmap2_a77.py",
    )
    for name in required:
        assert name in script


def test_a78_harness_and_document_preserve_user_authority_and_schema_23() -> None:
    script = (ROOT / "scripts/track-a-product-acceptance.ps1").read_text(encoding="utf-8")
    document = (ROOT / "docs/TRACK_A_END_TO_END_PRODUCT_ACCEPTANCE_ROADMAP2_A78.md").read_text(encoding="utf-8")
    combined = f"{script}\n{document}"
    for phrase in (
        "Automatic Preflight: DISABLED",
        "Automatic generation: DISABLED",
        "Automatic Smart Routing apply: DISABLED",
        "Hidden cross-provider failover: NOT INTRODUCED",
        "Database schema 23: PRESERVED",
        "A7.9 — Track A Certification & Freeze",
    ):
        assert phrase in combined


def test_a78_phase_is_acceptance_only_and_does_not_patch_production_source() -> None:
    document = (ROOT / "docs/TRACK_A_END_TO_END_PRODUCT_ACCEPTANCE_ROADMAP2_A78.md").read_text(encoding="utf-8")
    assert "Production application source changed by A7.8: NO" in document
    assert "acceptance-only" in document.casefold()


def test_a78_files_have_single_final_newline() -> None:
    paths = (
        Path("scripts/track-a-product-acceptance.ps1"),
        Path("docs/TRACK_A_END_TO_END_PRODUCT_ACCEPTANCE_ROADMAP2_A78.md"),
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
