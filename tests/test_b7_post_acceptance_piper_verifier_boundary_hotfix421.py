from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "app" / "frozen_main.py"
MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"


def test_h421_read_only_runtime_verifier_and_synthesis_smoke_are_separate_commands() -> None:
    source = FROZEN.read_text(encoding="utf-8")
    smoke = source.split("def _handle_local_engines_piper_synthesis_smoke", 1)[1].split(
        "def _handle_local_engines_runtime_verify", 1
    )[0]
    verify = source.split("def _handle_local_engines_runtime_verify", 1)[1].split(
        "def _handle_provider_accounts_runtime_verify", 1
    )[0]

    assert "--local-engines-runtime-verify" in verify
    assert "LOCAL_ENGINES_RUNTIME_VERIFY" in verify
    assert ".synthesize(" not in verify
    assert ".warm(" not in verify

    assert "--local-engines-piper-synthesis-smoke" in smoke
    assert 'smoke_provider.synthesize("Hej.", smoke_settings)' in smoke
    assert "LOCAL_ENGINES_PIPER_SYNTHESIS_SMOKE" in smoke


def test_h421_migration_runs_discovery_and_synthesis_as_two_frozen_processes() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "& $PortableExe --local-engines-runtime-verify "
        "--local-engines-require-piper --local-engines-expected-piper-voices 1"
    ) in source
    assert "& $PortableExe --local-engines-piper-synthesis-smoke" in source
    assert "LOCAL_ENGINES_RUNTIME_VERIFY=PASS" in source
    assert "LOCAL_ENGINES_PIPER_SYNTHESIS_SMOKE=PASS" in source


def test_h421_preserves_h3_and_h42_migration_contract_text() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "neither the console wrapper nor the managed Python-module fallback" in source
    assert "no runnable console wrapper, standalone binary, or managed Python-module fallback" in source
