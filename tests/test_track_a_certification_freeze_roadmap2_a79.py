from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CERT_SCRIPT = ROOT / "scripts" / "track-a-certification.ps1"
DOC = ROOT / "docs" / "TRACK_A_CERTIFICATION_FREEZE_ROADMAP2_A79.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def test_a79_certification_artifacts_exist() -> None:
    assert CERT_SCRIPT.is_file()
    assert DOC.is_file()


def test_a79_is_certification_only_and_points_directly_to_a8() -> None:
    doc = _text(DOC)
    assert "introduces no application feature" in doc
    assert "No additional A7 feature phase is planned" in doc
    assert "A8 — Visual Design System 2.0" in doc


def test_a79_reuses_a78_acceptance_instead_of_synthesis() -> None:
    source = _text(CERT_SCRIPT)
    assert "artifacts/track-a-product-acceptance/latest.json" in source
    assert "total_acceptance_tests -lt 579" in source
    assert "@($Acceptance.scenarios).Count -ne 8" in source
    assert "live_synthesis_performed" in source
    assert "generation_controller.start" not in source


def test_a79_freezes_application_and_packaging_git_trees() -> None:
    source = _text(CERT_SCRIPT)
    assert 'git rev-parse "${ProductSourceCommit}:app"' in source
    assert 'git rev-parse "HEAD:app"' in source
    assert 'git rev-parse "${ProductSourceCommit}:packaging"' in source
    assert 'git rev-parse "HEAD:packaging"' in source
    assert "Application tree changed after the certified A7.8 product source" in source
    assert "Packaging tree changed after the certified A7.8 product source" in source


def test_a79_freezes_authority_without_adding_automatic_actions() -> None:
    source = _text(CERT_SCRIPT)
    for required in (
        "user_selected_target_language",
        "per_job_explicit_language_override",
        "content_based_language_detection_override",
        "automatic_provider_account_voice_model_language_change",
        "automatic_preflight",
        "automatic_generation",
        "automatic_smart_routing_apply",
        "hidden_cross_provider_failover",
    ):
        assert required in source
    assert "automatic_preflight = $false" in source
    assert "automatic_generation = $false" in source
    assert "automatic_smart_routing_apply = $false" in source
    assert "hidden_cross_provider_failover = $false" in source


def test_a79_release_packaging_contract_is_structural_not_a_release_build() -> None:
    source = _text(CERT_SCRIPT)
    for required in (
        "packaging/S-Talking.spec",
        "app/frozen_main.py",
        "scripts/final-release.ps1",
        "scripts/release-check.ps1",
        "PyInstaller --version",
    ):
        assert required in source
    assert "--BuildPackages" not in source


def test_a79_database_schema_contract_remains_23() -> None:
    source = _text(CERT_SCRIPT)
    doc = _text(DOC)
    assert "database_schema = 23" in source
    assert "Database schema contract 23" in doc


def test_a79_preflight_revision_still_uses_explicit_language_override_without_detection() -> None:
    source = _text(ROOT / "app" / "services" / "preflight_service.py")
    request_start = source.index("    def request_revision(")
    request_end = source.find("\n    def ", request_start + 5)
    request_block = source[request_start:] if request_end < 0 else source[request_start:request_end]
    assert "self._key(" in request_block

    key_start = source.index("    def _key(")
    key_end = source.find("\n    def ", key_start + 5)
    key_block = source[key_start:] if key_end < 0 else source[key_start:key_end]
    assert "language_override" in key_block
    for forbidden in ("detect_language(", "language_detector", "guess_language("):
        assert forbidden not in request_block
        assert forbidden not in key_block


def test_a79_required_release_and_authority_files_exist() -> None:
    for relative in (
        "packaging/S-Talking.spec",
        "app/frozen_main.py",
        "scripts/final-release.ps1",
        "scripts/release-check.ps1",
        "app/models/launch_assurance.py",
        "app/services/launch_assurance_service.py",
        "app/services/pronunciation_readiness_service.py",
        "app/services/pronunciation_audit_service.py",
    ):
        assert (ROOT / relative).is_file(), relative


def test_a79_attestation_is_privacy_safe_by_contract() -> None:
    source = _text(CERT_SCRIPT)
    assert "credentials_in_attestation = $false" in source
    assert "raw_source_text_in_attestation = $false" in source
    assert "raw_voice_model_dictionary_ids_required = $false" in source
